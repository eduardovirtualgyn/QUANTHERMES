# Status do Projeto QUANT HERMES
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Última Atualização:** 19 de Novembro de 2026  
**Conta-alvo:** RoboForex ProCent (moeda USC, alavancagem até 1:2000, stop-out 30%)  
**Prontidão:** paper e backtest offline corrigidos; **não homologado** em terminal MT5 ao vivo. Nenhuma ordem real é enviada por esta revisão.

## 0. Correção de 19/11/2026 — o que o código faz de verdade

As seções históricas abaixo registram o que foi construído por fase. Várias delas diziam VALIDADO além do que o código sustentava. O estado executável hoje é:

* O orquestrador chama o Portfolio Manager e o Risk Engine com a assinatura real. Um teste paper (sinal → risco → lote → ordem → fill → estado) produz ordem no adapter em memória.
* PnL diário/semanal do adapter Windows sai de `history_deals_get` mais o flutuante das posições abertas e alimenta os circuit breakers.
* Preenchimento parcial (retcode 10010), requote, preço mudado e off-quotes são tratados com retentativa limitada. A chave de idempotência não é reenviada depois do resultado final.
* O lote gravado na idempotência é o lote autorizado, não o percentual de risco.
* Recuperação casa magic number com o símbolo lógico (sufixo do broker). O pico de equity fica no estado em disco.
* `config/*.yaml` é carregado e validado no construtor do orquestrador. Configuração inválida aborta.
* Símbolos lógicos passam por `execution/symbols.py` (sufixo configurável). O lote usa `volume_min` / `volume_step` / `volume_max` do terminal, arredonda para baixo e rejeita abaixo do mínimo. Não há arredondamento para cima até o mínimo do YAML.
* Há checagem de margem (`order_calc_margin` / margem livre) com teto de uso e stop-out de 30%.
* Swap (`swap_long` / `swap_short`, dia triplo) entra no dimensionamento quando o spec traz a taxa e no backtest (catálogo ProCent se o spec vier zerado).
* Endpoints que alteram estado exigem `HERMES_OPERATOR_TOKEN`. Não há token padrão. A API escuta em 127.0.0.1.
* Deploy suportado: uma máquina Windows com o terminal RoboForex aberto na mesma sessão de usuário (`docs/deploy/WINDOWS.md`, `deploy/windows/setup.ps1`). O gateway remoto fica desligado. Docker e os scripts Linux são opcionais ou obsoletos. Wine não é caminho.
* O backtest cobra spread (médias públicas ProCent: XAUUSD ~0,18 USD, majors ~1,3–1,9 pips, comissão zero), slippage e swap. Gap no stop preenche no open. Stop e alvo na mesma barra assumem o stop. Sharpe usa a frequência da barra. O relatório inclui profit factor, expectância em R, drawdown, trades e t-stat/IC.
* O walk-forward avalia as estratégias fora da amostra, com Deflated Sharpe e Bonferroni (estratégias × conjuntos de parâmetros). Não simula mais ganho fictício do classificador.
* Pacotes vazios, **não implementados** (não importar como se existissem): `agents/`, `api/`, `dashboard/`, `backtesting/`, `execution/mt5/`, `execution/mql5/`, `execution/paper/`, `execution/backtest/`. O dashboard real está em `monitoring/`. O paper adapter está em `execution/adapters/paper.py`. O backtest está em `strategies/backtest/`.

**Fase atual do código:** execução paper corrigida; demo/live no MT5 continua não homologada.  

---

## 1. Quadro Geral de Fases

| Fase | Título | Status | Entregáveis Principais | Evidências |
| :--- | :--- | :--- | :--- | :--- |
| **FASE 0** | **Auditoria e Planejamento** | **VALIDADO** | Auditoria dos 6 repositórios, checagem de licenças, arquitetura, ADRs, plano de testes, AGENTS.md | `docs/research/`, `docs/architecture/`, `docs/decisions/` |
| **FASE 1** | **Fundação** | **VALIDADO** | Estrutura de pacotes, schemas Pydantic V2, logging higienizado, loader com pisos invioláveis, Event Bus priorizado | `core/`, `intelligence/schemas/`, `tests/` |
| **FASE 2** | **MT5 e Data Engine** | **VALIDADO** | `TradingPlatformAdapter` abstrato, `PaperTradingAdapter` em memória, `WindowsMT5Adapter` com fila serializada single-thread, `MarketDataCollector` com detecção de gaps, `HistoricalDataStore` Parquet com garantia anti-lookahead | `execution/adapters/`, `data/`, `tests/` (45/45 PASS) |
| **FASE 3** | **Risk e Portfolio** | **VALIDADO** | `PositionSizer` (loss-per-lot, floor step), `CircuitBreakers` (perda diária/semanal/drawdown/fim de semana), `KillSwitch` (persistência em disco, liquidação compulsória), `RiskEngine` (autoridade soberana), `CorrelationMonitor`, `CapitalAllocator`, `PortfolioManager`, `PositionReconciler` | `risk/`, `portfolio/`, `tests/` (105/105 PASS) |
| **FASE 4** | **Estratégias** | **VALIDADO** | 7 famílias de estratégias quantitativas (Forex + XAUUSD), biblioteca matemática de indicadores, motor de backtesting histórico determinístico | `data/features/`, `strategies/`, `tests/` (126/126 PASS) |
| **FASE 5** | **Inteligência Multiagente** | **VALIDADO** | 8 agentes especializados (AG01 a AG08), matriz de pesos por regime, calibração Platt Scaler, motor de consenso ponderado e orquestrador de fluxo | `intelligence/`, `tests/` (139/139 PASS) |
| **FASE 6** | **Quantitative Engine e Learning** | **VALIDADO** | HMM de regimes estocásticos (GaussianHMM), classificador supervisionado XGBoost/LightGBM, Validação Purgada com Embargo (López de Prado), Simulação de Estresse Monte Carlo e Registro de Modelos com Rollback Atômico (Regra 15) | `intelligence/regime/`, `intelligence/learning/`, `tests/` (161/161 PASS) |
| **FASE 7** | **Execução Autônoma** | **VALIDADO** | Orquestrador Central Autônomo ponta-a-ponta, OrderExecutor soberano com trava constitucional, StateManager com escrita atômica, reconciliação contínua e Paper Trading session | `execution/`, `tests/` (173/173 PASS) |
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

---

## 5. Síntese dos Entregáveis da Fase 5 (Inteligência Multiagente)

1. **Os 8 Agentes Especializados de Inteligência (`intelligence/agents/`):**
   * **AG01 — TREND INTELLIGENCE (`ag01_trend.py`):** Análise multi-timeframe (M15/H1), alinhamento de médias exponenciais, força direcional ADX e confluência estrutural.
   * **AG02 — MARKET STRUCTURE INTELLIGENCE (`ag02_structure.py`):** Mapeamento objetivo de BOS, CHoCH e varredura de liquidez (RR 2.5x).
   * **AG03 — MOMENTUM AND BREAKOUT (`ag03_momentum.py`):** Compressão de volatilidade (Bollinger Squeeze), expansão de range e rompimento Donchian.
   * **AG04 — MEAN REVERSION (`ag04_mean_reversion.py`):** Desvios estatísticos Z-Score $\ge 2.0$, exaustão de RSI e veto estrito em tendências fortes (ADX $\ge 25$).
   * **AG05 — GOLD AND MACRO INTELLIGENCE (`ag05_gold_macro.py`):** Especialização em XAUUSD, correlação com DXY e filtro de blackout de notícias macroeconômicas de alto impacto (15 minutos antes e depois).
   * **AG06 — QUANTITATIVE INTELLIGENCE (`ag06_quantitative.py`):** Classificação de regimes estocásticos (`RegimeClassification`), probabilidades a posteriori e cálculo de incerteza via Entropia de Shannon.
   * **AG07 — ADVERSARIAL RESEARCH (`ag07_adversarial.py`):** Investigação dialética (Advogado do Diabo: Bull vs Bear), detecção de armadilhas institucionais e cálculo do fator de penalidade de risco.
   * **AG08 — PORTFOLIO INTELLIGENCE (`intelligence/consensus/engine.py`):** Motor de consenso governado pela equação $\text{Score} = \sum (w_i(R) \times D_i \times C_i \times Q_i)$.
2. **Calibração Probabilística de Platt (`intelligence/calibration/platt_scaler.py`):**
   * Mapeamento sigmoidal de pontuações de convicção em probabilidades estatisticamente calibradas $P(\text{Sucesso} \mid \text{Score})$.
3. **Matriz de Pesos Dinâmica por Regime (`intelligence/consensus/weights.py`):**
   * Calibração de pesos $w_i(R)$ específicos para cada estado de mercado e fatores de qualidade histórica fora da amostra $Q_i$.
4. **Orquestrador de Fluxo Multiagente (`intelligence/langgraph/workflow.py`):**
   * Grafo de execução coordenando detecção de regime, inferência analítica paralela, investigação adversarial e deliberação de consenso.
5. **Evidência de Qualidade Automatizada:**
   * **139 testes automatizados aprovados (100% PASS em 3.72s)**.

---

## 6. Síntese dos Entregáveis da Fase 6 (Quantitative Engine e Learning)

1. **Detector de Regimes Estocásticos via HMM (`intelligence/regime/hmm_detector.py`):**
   * Implementação de `GaussianHMM` (via `hmmlearn.hmm`) com 4 componentes latentes.
   * Extração de features quantitativas: log-retornos, volatilidade realizada móvel (20 barras), ATR ratio e ADX 14.
   * Mapeamento determinístico e interpretável de estados ocultos para `MarketRegimeType` (`TREND_BULL_STRONG`, `TREND_BEAR_STRONG`, `RANGING_LOW_VOL`, `EXPANSION_HIGH_VOL`).
   * Cálculo de probabilidades a posteriori $P(S_t = k \mid X)$ e incerteza estocástica via Entropia de Shannon normalizada.
   * Fallback heurístico fail-safe caso o HMM enfrente dados insuficientes ou falha de convergência.
   * Integração bidirecional com o agente AG06 (`QuantitativeAgent`).

2. **Classificador Supervisionado de Machine Learning (`intelligence/learning/classifier.py`):**
   * Engine de classificação supervisionada para previsão direcional de mercado (`SignalDirection.BUY`, `SELL`, `HOLD`).
   * Suporte nativo a `XGBoost` e `LightGBM` com calibração sigmoidal de probabilidades e fallback automático resiliente.
   * Pipeline de 10 features técnicas padronizadas (RSI 14, histograma MACD, distâncias de EMA 20/50 normalizadas pelo ATR, ADX 14, Bollinger Band Width, Z-Score 20, retornos de 1 e 5 barras, ATR percentual).
   * Rotulagem rigorosa por *Triple-Barrier Method* / Forward Returns em horizonte temporal parametrizável ($H$ barras, $k \times ATR$).

3. **Validação Purgada e com Embargo Walk-Forward (`intelligence/learning/validation.py`):**
   * Implementação estrita da metodologia de Marcos López de Prado (*Advances in Financial Machine Learning*).
   * **Purging:** Eliminação sistemática de sobreposição temporal entre janelas de previsão e teste, erradicando viés de antecipação (*lookahead leakage*).
   * **Embargo:** Margem de segurança pós-teste (2% a 5% da série) para eliminar contaminação por autocorrelação serial.
   * Cálculo de métricas fora da amostra (OOS): Profit Factor OOS, Win Rate OOS, Sharpe Ratio OOS, Max Drawdown OOS.
   * **Portão Constitucional:** Bloqueio compulsório de aprovação para produção caso o modelo apresente `profit_factor < 1.30`, `win_rate < 0.50`, `max_drawdown > 0.08` ou amostra OOS estatisticamente insuficiente.

4. **Simulador de Estresse Monte Carlo (`intelligence/learning/monte_carlo.py`):**
   * Bootstrapping não-paramétrico com reposição de distribuições de trades (500 a 10.000 iterações).
   * Cálculo da **Probabilidade de Ruína** $P(\text{Drawdown} \ge 8.00\%)$ vinculada ao circuit breaker constitucional inviolável.
   * Mensuração de cauda gorda (*Fat-Tails*): Value at Risk (VaR 95%, VaR 99%) e Conditional VaR / Expected Shortfall (CVaR 95%).
   * Intervalo de confiança empírico (95%) para a curva de patrimônio terminal e cálculo de expectância matemática.
   * Portão de Robustez: Rejeição automática se a probabilidade de ruína for $\ge 1.0\%$ ou se o drawdown no percentil 99 violar 8.00%.

5. **Registro de Modelos e Mecanismo de Rollback Atômico (`intelligence/learning/registry.py`):**
   * **Conformidade Estrita com a Regra 15 da Constituição de Engenharia (`AGENTS.md`):**
     * *"Não implementar aprendizado online não supervisionado em produção: Modelos de produção só são substituídos após aprovação em testes de validação purgada fora da amostra com mecanismo de rollback."*
   * Ciclo de vida estrito de 5 estágios: `CANDIDATE` $\rightarrow$ `STAGING` $\rightarrow$ `PRODUCTION` $\rightarrow$ `ARCHIVED` / `REJECTED`.
   * Integridade criptográfica via hash SHA-256 gravado nos metadados auditáveis (`metadata.json`).
   * Trava de promoção: Modelos reprovados na validação purgada ou no Monte Carlo lançam `PermissionError` e são rebaixados para `REJECTED`.
   * **Rollback Atômico:** Método `rollback_production_model` reverte instantaneamente o modelo defeituoso para `REJECTED`, reativa a versão anterior `ARCHIVED` como `PRODUCTION` e atualiza os ponteiros de disco e cache em memória.

6. **Evidência de Qualidade Automatizada:**
   * **161 testes automatizados aprovados (100% PASS em 7.66s)** cobrindo todos os módulos do sistema, sem qualquer stub ou teste vazio.

---

## 7. Síntese dos Entregáveis da Fase 7 (Execução Autônoma)

1. **Executor Soberano de Ordens (`execution/order_executor.py`):**
   * Concretização do Princípio Fundamental Inviolável da Constituição de Engenharia (`AGENTS.md`).
   * Bloqueio incondicional com `PermissionError` para qualquer tentativa de envio de ordem sem `RiskAuthorization` aprovada ou com lote nulo.
   * Validação de integridade entre `TradeProposal` e `RiskAuthorization` (ativo, direção e preços).
   * Proteção por **idempotência temporal (60 segundos)**, impedindo reenvios duplicados de ordens decorrentes de repetições de ticks ou oscilações de rede.
   * Rastreamento auditável de todo o ciclo de vida do envio e preenchimento da ordem (`OrderResult`).

2. **Gerenciador de Estado Operacional (`execution/state_manager.py`):**
   * Persistência em disco e recuperação atômica do estado operacional (`ExecutionState`) em `data/storage/execution_state.json`.
   * Gravação à prova de falhas com escrita intermediária em arquivo temporário (`.tmp`) e renomeação atômica (`os.replace`), garantindo que nenhuma queda de energia ou terminação abrupta de processo corrompa o estado do sistema.
   * Rastreamento de tickets ativos, contagem diária de trades, PnL realizado acumulado e timestamp da última reconciliação.

3. **Orquestrador Central Autônomo (`execution/orchestrator.py`):**
   * Conexão ponta-a-ponta e assíncrona de todas as camadas do sistema:
     $$\text{Market Data Collector} \rightarrow \text{HMM Regimes} \rightarrow \text{7 Estratégias} \rightarrow \text{Multi-Agent Consensus (AG01..AG08)} \rightarrow \text{Portfolio Manager} \rightarrow \text{Sovereign Risk Engine} \rightarrow \text{Order Executor} \rightarrow \text{Reconciler}$$
   * Rotina assíncrona de inicialização e validação de contratos e especificações de símbolos.
   * Ciclo contínuo de processamento de ticks e barras OHLCV fechadas.
   * Execução periódica autônoma de reconciliação de posições para detecção e correção de posições órfãs, posições fantasma e desvios de Stop Loss no broker.
   * Método de simulação autônoma `run_simulation_session` executando sessões completas de mercado em modo Paper Trading com geração consolidada de `SessionSummary`.
   * Parada graciosa (`shutdown`) com desconexão segura e persistência do estado como `STOPPED`.

4. **Evidência de Qualidade Automatizada:**
   * **173 testes automatizados aprovados (100% PASS em 19.01s)** cobrindo todas as Fases 1 a 7 com 0 falhas e 0 erros.
