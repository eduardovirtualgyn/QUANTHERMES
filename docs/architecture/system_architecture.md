# Arquitetura Geral do Sistema QUANT HERMES
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/architecture/system_architecture.md`  

---

## 1. Visão Geral e Princípio de Soberania do Risco

O **QUANT HERMES** é uma infraestrutura quantitativa autônoma multiagente, projetada para operar no MetaTrader 5 (Forex e XAUUSD), modularizada em 10 camadas lógicas desacopladas e orientadas a eventos.

### Princípio Fundamental de Arquitetura:
> **Agentes analisam, estratégias propõem, o Portfolio Manager aloca, mas SOMENTE o Risk Engine autoriza e despacha a execução.**
> Nenhum modelo de IA, agente LLM ou algoritmo quantitativo tem permissão de alterar seus próprios limites de risco, acessar diretamente a API da corretora ou afrouxar parâmetros de proteção de capital.

```
+-----------------------------------------------------------------------------------+
|                            CAMADAS DO QUANT HERMES                                |
+-----------------------------------------------------------------------------------+
|  [Camada A] Market Data Engine        (Ticks, Bars, Book, Macro Calendar)         |
|         │                                                                         |
|         ▼                                                                         |
|  [Camada B] Feature Engineering Engine(Volatilidade, Estrutura SMC, Z-Score, EMA)|
|         │                                                                         |
|         ├───────────────────────────────────┬─────────────────────────────────────┤
|         ▼                                   ▼                                     ▼
|  [Camada C] AI Multi-Agent Engine   [Camada D] Quant Intelligence  [Camada E] Strategy Engine
|  (8 Agentes Especializados)         (HMM, XGBoost, Regimes)        (7 Famílias Técnicas)
|         │                                   │                                     │
|         └───────────────────────────────────┼─────────────────────────────────────┘
|                                             ▼
|                                   [Camada F] Portfolio Manager
|                                   (Consenso, Correlação, Alocação)
|                                             │ (Proposta de Ordem)
|                                             ▼
|                                   [Camada G] RISK ENGINE (Autoridade Suprema)
|                                   * Pisos Invioláveis (_HARDCODED_MIN)
|                                   * Fail-Safe (Falta de dados = Bloqueio)
|                                   * Kill Switch & Circuit Breakers
|                                   * Dimensionamento Preciso (OrderCalcProfit)
|                                             │ (Ordem Autorizada)
|                                             ▼
|                                   [Camada H] Execution Engine
|                                   * TradingPlatformAdapter (Abstração)
|                                   * Single-Thread Worker (MT5 Windows COM)
|                                   * Reconciliação Hedging / Netting
|                                             │ (Feedback de Execução)
|         ┌───────────────────────────────────┴─────────────────────────────────────┐
|         ▼                                                                         ▼
|  [Camada I] Learning Engine                                            [Camada J] Monitoring & Dashboard
|  (Walk-Forward, Monte Carlo, Model Registry)                           (Métricas em Tempo Real, Kill Switch)
+-----------------------------------------------------------------------------------+
```

---

## 2. As Dez Camadas Arquiteturais

### Camada A: Market Data Engine
* **Responsabilidade:** Ingestão de ticks e candles em tempo real, download de séries históricas, detecção de lacunas, validação de timestamps e ingestão de calendário macroeconômico.
* **Integridade:** Barreira estrita contra *lookahead bias* — nenhum dado com timestamp superior ao tempo de decisão é propagado para as etapas subsequentes.

### Camada B: Feature Engineering Engine
* **Responsabilidade:** Cálculo determinístico e vetorial de indicadores técnicos (EMA, ADX, ATR, Z-Score, Bandas de Bollinger), mapeamento de estrutura de mercado (BOS, CHoCH, Sweeps de Liquidez) e normalização estatística.
* **Tecnologia:** NumPy, Pandas, Polars e implementações vetorizadas puras em Python.

### Camada C: AI Multi-Agent Engine
* **Responsabilidade:** Rede de 8 agentes independentes que analisam o mercado sob perspectivas especializadas (Trend, Structure, Breakout, Reversion, Gold/Macro, Quantitative, Adversarial e Portfolio).
* **Duplo Caminho:** Separação entre o caminho rápido (sub-segundo para scalping) e o caminho aprofundado (assíncrono via LangGraph para regime macro e validação de swing).

### Camada D: Quantitative Intelligence Engine
* **Responsabilidade:** Modelagem estatística, detecção probabilística de regimes de mercado via Hidden Markov Models (HMM), classificação supervisionada (XGBoost / LightGBM) e calibração de probabilidades (Brier Score, Platt Scaling).

### Camada E: Strategy Engine
* **Responsabilidade:** Execução das regras operacionais das 7 famílias de estratégias (Scalping, Momentum, Breakout, Pullback, SMC, Mean Reversion e Swing). As estratégias são computacionalmente puras e geram unicamente intenções de sinal tipadas.

### Camada F: Portfolio Manager
* **Responsabilidade:** Consolidação do consenso ponderado, filtragem de sinais concorrentes, avaliação de correlação entre instrumentos (EURUSD, GBPUSD, USDJPY, XAUUSD) e definição do capital de risco a alocar.

### Camada G: Risk Engine (Autoridade Superior)
* **Responsabilidade:** Validação soberana e irrevogável de cada proposta de trade. Possui regras invioláveis codificadas (`_HARDCODED_MIN`), verifica saldo, margem, limite de perda diária, perda semanal, drawdown global, spread máximo, slippage tolerável e aciona circuit breakers imediatos.
* **Fail-Safe Garantido:** Se qualquer dado de conta ou conexão for omitido ou inválido, a ordem é rejeitada e o sistema é bloqueado.

### Camada H: Execution Engine
* **Responsabilidade:** Tradução da ordem autorizada em chamadas para a corretora via `TradingPlatformAdapter`.
* **Segurança de Concorrência:** As chamadas para a DLL do MetaTrader 5 no Windows rodam em uma única thread dedicada (`max_workers=1`) com fila serializada assíncrona, eliminando colisões de COM Apartment.
* **Reconciliação:** Suporta contas Hedging e Netting, com rastreamento de tickets e verificação ativa do preenchimento real.

### Camada I: Learning Engine
* **Responsabilidade:** Aprendizado contínuo controlado e auditével. Armazena a trilha completa de cada operação (condições, regime, agentes, pesos, slippage, PnL), executa testes de Walk-Forward e simulações de Monte Carlo.
* **Regra de Produção:** Nenhum modelo é re-treinado e promovido para produção de forma automática sem atender a métricas rígidas de aprovação fora da amostra e manter versão de rollback.

### Camada J: Monitoring and Dashboard
* **Responsabilidade:** Interface operacional para acompanhamento em tempo real (FastAPI + WebSockets + Dashboard frontend).
* **Controles Operacionais:** Exibição do estado de conexão, posições, equity, drawdown, sinais e botão de Kill Switch global (que força o fechamento imediato e suspende novas entradas). Nenhum controle da UI pode contornar as validações do Risk Engine.

---

## 3. Comunicação Assíncrona e Contratos Tipados

* Todas as mensagens entre camadas trafegam na forma de modelos imutáveis `Pydantic V2`.
* O ciclo de vida de uma operação respeita a máquina de estados desacoplada:
  $$\text{Signal} \longrightarrow \text{Consensus} \longrightarrow \text{Proposal} \longrightarrow \text{Risk Authorization} \longrightarrow \text{Order Send} \longrightarrow \text{Broker Execution} \longrightarrow \text{Position State} \longrightarrow \text{Reconciliation}$$
* O barramento interno utiliza `asyncio.Queue` com prioridade para comandos de emergência (Kill Switch e cancelamento de ordens têm prioridade máxima).

