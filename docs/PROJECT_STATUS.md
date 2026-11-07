# Status do Projeto QUANT HERMES
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Última Atualização:** 07 de Novembro de 2026  
**Fase Atual:** FASE 4 — Estratégias (VALIDADO)  
**Próxima Fase:** FASE 5 — Inteligência Multiagente (Aguardando autorização)  

---

## 1. Quadro Geral de Fases

| Fase | Título | Status | Entregáveis Principais | Evidências |
| :--- | :--- | :--- | :--- | :--- |
| **FASE 0** | **Auditoria e Planejamento** | **VALIDADO** | Auditoria dos 6 repositórios, checagem de licenças, arquitetura, ADRs, plano de testes, AGENTS.md | `docs/research/`, `docs/architecture/`, `docs/decisions/` |
| **FASE 1** | **Fundação** | **VALIDADO** | Estrutura de pacotes, schemas Pydantic V2, logging higienizado, loader com pisos invioláveis, Event Bus priorizado | `core/`, `intelligence/schemas/`, `tests/` |
| **FASE 2** | **MT5 e Data Engine** | **VALIDADO** | `TradingPlatformAdapter` abstrato, `PaperTradingAdapter` em memória, `WindowsMT5Adapter` com fila serializada single-thread, `MarketDataCollector` com detecção de gaps, `HistoricalDataStore` Parquet com garantia anti-lookahead | `execution/adapters/`, `data/`, `tests/` (45/45 PASS) |
| **FASE 3** | **Risk e Portfolio** | **VALIDADO** | `PositionSizer` (loss-per-lot, floor step), `CircuitBreakers` (perda diária/semanal/drawdown/fim de semana), `KillSwitch` (persistência em disco, liquidação compulsória), `RiskEngine` (autoridade soberana), `CorrelationMonitor`, `CapitalAllocator`, `PortfolioManager`, `PositionReconciler` | `risk/`, `portfolio/`, `tests/` (105/105 PASS) |
| **FASE 4** | **Estratégias** | **VALIDADO** | 7 famílias de estratégias quantitativas (Forex + XAUUSD), biblioteca matemática de indicadores, motor de backtesting histórico determinístico | `data/features/`, `strategies/`, `tests/` (126/126 PASS) |
| **FASE 5** | **Inteligência Multiagente** | **NÃO INICIADO** | 8 agentes especializados, motor de consenso ponderado, LangGraph assíncrono | Depende da Fase 4 |
| **FASE 6** | **Quantitative Engine e Learning** | **NÃO INICIADO** | HMM de regimes, XGBoost/LightGBM, calibração, Walk-Forward, Monte Carlo | Depende da Fase 5 |
| **FASE 7** | **Execução Autônoma** | **NÃO INICIADO** | Integração ponta-a-ponta, paper trading, forward testing demo, reconciliação | Depende da Fase 6 |
| **FASE 8** | **Dashboard** | **NÃO INICIADO** | Painel operacional FastAPI + WebSockets, métricas em tempo real, controle de Kill Switch | Depende da Fase 7 |
| **FASE 9** | **Preparação Linux** | **NÃO INICIADO** | Dockerização, scripts de VPS Linux, túnel seguro de execução, backup | Depende da Fase 8 |
| **FASE 10**| **Homologação** | **NÃO INICIADO** | Execução dos 20 modos de falha, auditoria final de segurança, relatório de aprovação | Depende da Fase 9 |

---

## 2. Inventário do Ambiente Local Verificado

* **Sistema Operacional:** Windows 11 Pro 64-bit
* **Python Runtime:** Python 3.11.3 (Ambiente base verificado e configurado)
* **Pacotes Instalados:** `MetaTrader5-5.0.6231`, `pyarrow-15.0.2`, `pandas-3.0.6`, `pydantic-2.13.5`, `pytest-9.2.0`, `pytest-asyncio-1.4.1.post1`, `pyyaml-6.0.3`
* **Controle de Versão:** Git 2.55.0.windows.5 com commits atômicos por fase
* **Terminal MetaTrader 5:** `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe` (Versão 64-bit build 4200+ identificada)
* **Banco Relacional:** PostgreSQL instalado localmente em `C:\Program Files\PostgreSQL`

---

## 3. Síntese dos Entregáveis da Fase 3 (Risk e Portfolio)

1. **Dimensionador Matemático de Lotes (`risk/position_sizer.py`):**
   * Cálculo exato do risco monetário e distância do Stop Loss por lote padrão.
   * Arredondamento estritamente para baixo (*Floor*) no passo de volume (`volStep`), eliminando risco de sobrealavancagem.
   * Postura Fail-Safe: retorna 0.0 se lote for inferior ao mínimo da corretora (`volMin`).
2. **Circuit Breakers de Proteção de Capital (`risk/circuit_breakers.py`):**
   * `DailyLossGuard`: trava novas ordens se perda diária atingir 1.50% (reseta às 00:00 UTC).
   * `WeeklyLossGuard`: trava novas ordens se perda semanal atingir 3.00% (reseta na segunda-feira 00:00 UTC).
   * `EmergencyDrawdownGuard`: desarma o sistema se drawdown atingir o piso absoluto de 8.00%.
   * `WeekendRiskGuard`: bloqueia operações na sexta-feira após 20:00 UTC e no fim de semana.
   * `CircuitBreakerManager`: verificação encadeada prioritária.
3. **Trava de Emergência Global (`risk/kill_switch.py`):**
   * Bloqueio imediato com persistência atômica em disco (`data/storage/kill_switch_state.json`), sobrevivendo a reinicializações.
   * Rotina assíncrona de liquidação compulsória (`execute_emergency_liquidation`) de todas as posições em aberto no terminal.
   * Desarme restrito a operadores humanos autorizados.
4. **Motor Soberano de Risco (`risk/engine.py`):**
   * Concretização do Princípio Fundamental: somente o Risk Engine autoriza ordens.
   * Checagem em 9 etapas: Fail-Safe em telemetria nula, Kill Switch, Circuit Breakers, limites de posições (máx 3 total, 1 por ativo), Stop Loss obrigatório, filtro de spread anômalo (> 2.0x), limite de risco agregado (<= 1.00%), dimensionamento com clamping e emissão de `RiskAuthorization`.
5. **Monitor de Correlação e Exposição USD (`portfolio/correlation.py`):**
   * Mapeamento de exposição cambial oculta em Dólar nos pares Forex e Ouro.
   * Bloqueio de novas ordens quando o número de ativos fortemente correlacionados na mesma direção atinge o limite.
6. **Alocador Prudencial de Capital (`portfolio/allocator.py`):**
   * Gestão de orçamento de risco por família de estratégia (Trend, Breakout, Momentum, Mean Reversion, SMC, Scalping, Swing).
   * Clamping ao teto de 0.50% por trade e 1.00% de risco agregado da conta.
7. **Gerenciador Central de Portfólio (`portfolio/manager.py`):**
   * Arbitragem e filtragem de deliberações de consenso (AG08).
   * Deduplicação inteligente de sinais por janela de cooldown (60s).
   * Construção formal de `TradeProposal` e submissão ao `RiskEngine`.
8. **Reconciliador Autônomo de Posições (`portfolio/reconciler.py`):**
   * Detecção de posições órfãs (no broker sem registro interno).
   * Detecção de posições fantasma (fechadas no broker por SL/TP).
   * Auto-correção de divergências de Stop Loss via `modify_position`.
9. **Evidência de Qualidade Automatizada:**
   * **105 testes automatizados aprovados (100% PASS em 2.29s)** cobrindo todos os cenários de risco, limites e falhas.

---

## 4. Síntese dos Entregáveis da Fase 4 (Estratégias Quantitativas)

1. **Biblioteca Matemática de Indicadores (`data/features/indicators.py`):**
   * Implementações puras e vetorizadas via NumPy e Pandas para SMA, EMA, ATR, Bandas de Bollinger, RSI, MACD, ADX, Z-Score e Canais Donchian.
   * Algoritmo determinístico de detecção de fractais de swing (`detect_swings`).
   * Algoritmo 100% objetivo e reprodutível de Quebra de Estrutura e Mudança de Caráter (`detect_bos_choch`).
2. **Interface Abstrata Soberana (`strategies/base.py`):**
   * Classe `BaseStrategy` com validação de coerência de Stop Loss, razão Risco/Retorno mínima (`min_rr_ratio`) e emissão padronizada de `AgentSignal`.
3. **As 7 Famílias de Estratégias Quantitativas Implementadas:**
   * **Scalping (`strategies/scalping/micro_momentum.py`):** Aceleração de micro-momentum (M1/M5), alinhamento EMA 9/21, RSI dinâmico e RR 1.5x.
   * **Volatility Breakout (`strategies/breakout/volatility_breakout.py`):** Compressão de volatilidade (Bollinger Squeeze) + expansão de range com rompimento de canais Donchian (RR 2.0x).
   * **Momentum Surge (`strategies/momentum/momentum_surge.py`):** Filtro direcional ADX > 25, expansão de histograma MACD e inclinação de EMA 20 (RR 2.0x).
   * **Trend Pullback (`strategies/pullback/trend_pullback.py`):** Alinhamento maior EMA 50/200, retração na EMA 21 e rejeição por pavio (RR 2.0x).
   * **Statistical Mean Reversion (`strategies/mean_reversion/statistical_reversion.py`):** Regimes estritamente laterais (ADX < 25), desvios extremos de Z-Score $\ge 2.2$ e retorno à média (RR 1.8x).
   * **SMC Structure Break (`strategies/smc/structure_break.py`):** Mapeamento objetivo de BOS/CHoCH e varredura de liquidez (RR 2.5x).
   * **Macro Swing (`strategies/swing/macro_swing.py`):** Confluência tripla de médias de longo prazo (EMA 50, 100, 200), ADX e RR assimétrico de 3.0x.
4. **Motor Determinístico de Backtesting (`strategies/backtest/engine.py`):**
   * Simulação cronológica estrita sem viés de antecipação (*Anti-Lookahead Bias*).
   * Avaliação integrada ao `RiskEngine` e consolidação de métricas: Win Rate %, Profit Factor, Max Drawdown %, Sharpe Ratio e curva de equity.
5. **Evidência de Qualidade Automatizada:**
   * **126 testes automatizados aprovados (100% PASS em 2.48s)**.
