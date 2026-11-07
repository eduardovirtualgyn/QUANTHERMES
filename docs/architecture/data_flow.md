# Fluxo de Dados e Ciclo de Vida da Informação
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/architecture/data_flow.md`  

---

## 1. Diagrama Sequencial de Fluxo de Dados

O fluxo de dados do QUANT HERMES é estritamente unidirecional nas decisões e bidirecional na telemetria e reconciliação:

```
[MT5 Terminal / Broker]
         │ (Ticks, Book, Candles M1-H4, AccountInfo)
         ▼
[Market Data Engine]
   ├─► Validação de Timestamp (Sem Lookahead Bias)
   ├─► Detecção de Lacunas / Filtro de Spikes
   └─► Cache em Memória + Persistência Parquet/DuckDB
         │
         ▼
[Feature Engineering Engine]
   ├─► Médias Móveis, ATR, ADX, Z-Scores, Bollinger
   └─► Estrutura SMC (BOS, CHoCH, Liquidity Sweeps)
         │
         ├─────────────────────────────────────────┐
         ▼                                         ▼
[Fast Quant Path (M1-M5)]               [Deep Research Path (H1-D1)]
   ├─► AG01 (Trend)                        ├─► AG05 (Gold & Macro)
   ├─► AG02 (Market Structure)             ├─► AG07 (Adversarial LLM)
   ├─► AG03 (Breakout/Momentum)            └─► AG06 (HMM / Regime Shift)
   ├─► AG04 (Mean Reversion)                       │
   └─► AG06 (Quant / ML Inference)                 │ (Atualização periódica
         │                                         │  de pesos e limites)
         └────────────────────┬────────────────────┘
                              ▼
                   [Consensus Engine (AG08)]
                     ├─► Ponderação: Score = Σ (w_i × dir_i × conf_i × qual_i)
                     ├─► Calibração Probabilística (Platt / Isotonic)
                     └─► Filtro de Conflitos e Invalidações
                              │ (TradeProposal)
                              ▼
                   [Portfolio Manager]
                     ├─► Checagem de Correlação de Pares (EUR/GBP/USD/XAU)
                     ├─► Alocação de Risco por Estratégia
                     └─► Deduplicação de Sinais
                              │ (ProposedOrderRequest)
                              ▼
                   [RISK ENGINE (Autoridade Soberana)]
                     ├─► Checagem do Estado da Conta (Fail-Safe se nulo)
                     ├─► Pisos Invioláveis (_HARDCODED_MIN)
                     ├─► Dimensionamento Exato de Lote (OrderCalcProfit)
                     ├─► Circuit Breaker: Perda Diária / Semanal / Drawdown
                     └─► Filtro de Spread e Slippage Máximo
                              │
                    ┌─────────┴─────────┐
                    │ APROVADO          │ REJEITADO
                    ▼                   ▼
          [Execution Engine]       [Log de Rejeição]
            ├─► Serialização COM    └─► Aprendizado de Causa
            ├─► MT5 order_send
            └─► Reconciliação
                    │
                    ▼
          [TradeLog & Telemetria] ──► [Learning Engine] ──► [Dashboard]
```

---

## 2. Contratos Tipados das Mensagens

### 2.1 Contrato de Sinal do Agente (`AgentSignal`)
```python
class AgentSignal(BaseModel):
    signal_id: UUID
    timestamp: datetime
    agent_id: str             # ex: "AG01_TREND", "AG02_STRUCTURE"
    symbol: str               # ex: "EURUSD", "XAUUSD"
    timeframe: str            # ex: "M5", "M15", "H1"
    direction: Literal["BUY", "SELL", "HOLD"]
    confidence: float         # 0.0 a 1.0 (calibrada)
    suggested_entry: float
    suggested_stop: float
    suggested_target: float
    invalidation_level: float
    rationale: dict[str, Any]
    model_version: str
```

### 2.2 Contrato de Decisão do Consenso (`ConsensusDecision`)
```python
class ConsensusDecision(BaseModel):
    decision_id: UUID
    timestamp: datetime
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"]
    composite_score: float    # -1.0 a +1.0
    calibrated_prob: float    # 0.0 a 1.0
    active_regime: str        # ex: "TREND_BULL_STRONG", "RANGING_LOW_VOL"
    participating_agents: list[str]
    dissenting_agents: list[str]
    invalidation_criteria: list[str]
```

### 2.3 Contrato de Autorização de Risco (`RiskAuthorization`)
```python
class RiskAuthorization(BaseModel):
    auth_id: UUID
    timestamp: datetime
    decision_id: UUID
    symbol: str
    action: Literal["BUY", "SELL"]
    authorized_lot: float     # Lote normalizado estritamente (OrderCalcProfit)
    stop_loss: float          # SL obrigatório
    take_profit: float
    max_slippage_points: int
    account_equity: float
    calculated_risk_amount: float
    risk_percentage: float    # ex: 0.25%
    approved: bool
    rejection_reason: str | None
```

---

## 3. Garantias de Não-Vazamento Temporal (*Anti-Lookahead Protocol*)

1. **Janela Deslizante Estrita:** Durante backtesting e forward testing, a geração de features no tempo $T$ tem acesso exclusivamente a dados com timestamp $t \le T - \Delta_{\text{bar}}$.
2. **Separação de Séries de Fechamento:** Nenhuma decisão em candle aberto pode utilizar o preço de fechamento (`Close`) do candle em formação; utiliza-se o fechamento do candle anterior ou ticks consolidados.
3. **Calendário Macroeconômico Ponto-no-Tempo:** Dados de eventos econômicos (ex: Payroll, CPI) só são visibilizados para os agentes exatamente após o horário oficial de divulgação da notícia, nunca antes.

