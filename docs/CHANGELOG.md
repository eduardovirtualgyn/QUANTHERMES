# Changelog — QUANT HERMES
Todas as alterações notáveis deste projeto serão documentadas neste arquivo.
O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/) e adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

---

## [0.5.0-phase4] — 2026-11-07

### Adicionado
* **FASE 4 — Estratégias Quantitativas Concluída:**
  * Implementação da biblioteca matemática de indicadores e features (`data/features/indicators.py`):
    * `calc_sma`, `calc_ema`, `calc_atr`, `calc_bollinger_bands`, `calc_rsi`, `calc_macd`, `calc_adx`, `calc_zscore`, `calc_donchian`.
    * Algoritmo determinístico de detecção de fractais de swing (`detect_swings`).
    * Algoritmo objetivo de quebra de estrutura (`detect_bos_choch`).
  * Implementação da classe base `BaseStrategy` (`strategies/base.py`):
    * Validação formal de contratos, coerência de Stop Loss e corte obrigatório por Risco/Retorno mínimo (`min_rr_ratio`).
  * Implementação das 7 famílias de estratégias quantitativas:
    * `MicroMomentumScalpingStrategy` (`strategies/scalping/micro_momentum.py`): micro-momentum M1/M5, alinhamento EMA 9/21 e aceleração RSI (RR 1.5x).
    * `VolatilityBreakoutStrategy` (`strategies/breakout/volatility_breakout.py`): expansão de volatilidade a partir de Bollinger Squeeze com rompimento Donchian (RR 2.0x).
    * `MomentumSurgeStrategy` (`strategies/momentum/momentum_surge.py`): aceleração direcional com ADX > 25 e expansão do histograma MACD (RR 2.0x).
    * `TrendPullbackStrategy` (`strategies/pullback/trend_pullback.py`): tendência EMA 50/200, retração na EMA 21 e rejeição por pavio (RR 2.0x).
    * `StatisticalMeanReversionStrategy` (`strategies/mean_reversion/statistical_reversion.py`): mercados laterais (ADX < 25), desvio Z-Score >= 2.2 e retorno à média (RR 1.8x).
    * `SMCStructureStrategy` (`strategies/smc/structure_break.py`): quebras determinísticas de estrutura BOS/CHoCH e varredura de liquidez (RR 2.5x).
    * `MacroSwingStrategy` (`strategies/swing/macro_swing.py`): alinhamento triplo de médias H1/H4 (EMA 50, 100, 200) e RR assimétrico de 3.0x.
  * Implementação do motor de backtesting histórico determinístico (`strategies/backtest/engine.py`):
    * Simulação cronológica estrita com garantia contra viés futuro (*Anti-Lookahead Bias*).
    * Integração com o `RiskEngine` e apuração de métricas de performance (Win Rate, Profit Factor, Drawdown, Sharpe, curva de equity).
  * Criação de 21 novos testes automatizados:
    * `tests/unit/test_indicators.py` (10 testes).
    * `tests/unit/test_strategies.py` (8 testes).
    * `tests/unit/test_backtest_engine.py` (3 testes).
  * Total de testes automatizados do projeto elevado para **126 testes (100% PASS em 2.48s)**.

---

## [0.4.0-phase3] — 2026-11-07

### Adicionado
* **FASE 3 — Risk e Portfolio Concluída:**
  * Implementação do `risk/position_sizer.py` (`PositionSizer`):
    * Cálculo exato de perda por lote a partir de `tick_size` e `tick_value`.
    * Arredondamento estritamente para baixo (*Floor*) no passo de volume (`volStep`), prevenindo sobrealavancagem acidental.
    * Postura Fail-Safe retornando 0.0 se volume calculado for menor que o lote mínimo (`volMin`).
  * Implementação do `risk/circuit_breakers.py` (`CircuitBreakers`):
    * `DailyLossGuard`: trava novas ordens se perda diária atingir 1.50% (reseta às 00:00 UTC).
    * `WeeklyLossGuard`: trava novas ordens se perda semanal atingir 3.00% (reseta na segunda-feira 00:00 UTC).
    * `EmergencyDrawdownGuard`: desarma o sistema se drawdown atingir 8.00% (piso inviolável).
    * `WeekendRiskGuard`: bloqueia operações na sexta-feira após 20:00 UTC e aos finais de semana.
    * `CircuitBreakerManager`: verificação encadeada prioritária de todos os guardiões.
  * Implementação do `risk/kill_switch.py` (`KillSwitch`):
    * Trava de emergência global com persistência atômica em disco (`data/storage/kill_switch_state.json`), sobrevivendo a reinicializações.
    * Desarme restrito com token de operador humano.
    * Rotina assíncrona de liquidação compulsória (`execute_emergency_liquidation`) de todas as posições em aberto no terminal.
  * Implementação do `risk/engine.py` (`RiskEngine`):
    * Autoridade soberana que centraliza todas as aprovações de ordens (`RiskAuthorization`).
    * Validação em 9 etapas: Fail-Safe em estado nulo da conta, Kill Switch, Circuit Breakers, limite de 3 posições abertas totais e 1 por símbolo, Stop Loss mandatório, filtro de spread anômalo (> 2.0x média), limite de risco agregado de 1.00% da conta e dimensionamento de lote.
  * Implementação do `portfolio/correlation.py` (`CorrelationMonitor`):
    * Monitoramento de correlação de Pearson e concentração cambial na moeda USD.
    * Bloqueio de novas operações caso exceda o limite de 2 pares correlacionados na mesma direção.
  * Implementação do `portfolio/allocator.py` (`CapitalAllocator`):
    * Alocação e controle de orçamento de risco por família de estratégia (Trend, Breakout, Momentum, Mean Reversion, SMC, Scalping, Swing).
    * Garantia dos tetos invioláveis de 0.50% por operação e 1.00% agregado.
  * Implementação do `portfolio/manager.py` (`PortfolioManager`):
    * Arbitragem e filtragem de deliberações de consenso (AG08).
    * Deduplicação de sinais idênticos dentro de janela de cooldown (60s).
    * Geração estruturada de `TradeProposal` e submissão ao `RiskEngine`.
  * Implementação do `portfolio/reconciler.py` (`PositionReconciler`):
    * Auditoria periódica comparando estado do broker com registro interno.
    * Detecção de posições órfãs, posições fantasma e descompasso de Stop Loss.
    * Auto-correção de divergências de Stop Loss via `modify_position`.
  * Criação de 60 novos testes automatizados:
    * `tests/risk/test_position_sizer.py` (7 testes).
    * `tests/risk/test_circuit_breakers.py` (15 testes).
    * `tests/risk/test_kill_switch.py` (7 testes).
    * `tests/risk/test_risk_engine.py` (9 testes).
    * `tests/unit/test_correlation_monitor.py` (5 testes).
    * `tests/unit/test_capital_allocator.py` (6 testes).
    * `tests/unit/test_portfolio_manager.py` (4 testes).
    * `tests/unit/test_reconciler.py` (4 testes).
    * `tests/contract/test_schemas.py` (+3 testes para `TradeProposal`).
  * Total de testes automatizados do projeto elevado para **105 testes (100% PASS em 2.29s)**.

---

## [0.3.0-phase2] — 2026-11-07

### Adicionado
* **FASE 2 — MT5 e Data Engine Concluída:**
  * Instalação e integração do `pyarrow-15.0.2` para suporte colunar com NumPy 1.x.
  * Criação da interface abstrata `execution/adapters/base.py` (`TradingPlatformAdapter`).
  * Implementação do `execution/adapters/paper.py` (`PaperTradingAdapter`):
    * Simulação completa em memória com recálculo de margem livre, equity, balanço e drawdown.
    * Atualização de PnL flutuante por tick e gatilhos automáticos de Stop Loss / Take Profit.
    * Rejeição por falta de margem e idempotência com cache de ordens.
  * Implementação do `execution/adapters/windows_mt5.py` (`WindowsMT5Adapter`):
    * Executor single-thread dedicado (`max_workers=1`, ADR-003) para chamadas COM MT5 no Windows.
    * Resolução de aliases de sufixos de ativos de corretoras.
    * Seleção dinâmica de modo de preenchimento de ordem (`IOC`, `FOK`, `RETURN`).
    * Tratamento de erro 10027 (*AutoTrading disabled*) e idempotência de envio.
  * Implementação do `data/ingestion/collector.py` (`MarketDataCollector`):
    * Sanitização de ticks anômalos e desduplicação em tempo real.
    * Algoritmo de detecção de lacunas (*gaps*) em barras temporais.
  * Implementação do `data/storage/parquet_store.py` (`HistoricalDataStore`):
    * Armazenamento particionado em formato Parquet por ativo e timeframe.
    * Método `get_bars_as_of` com garantia matemática estrita contra viés de antecipação (*Anti-Lookahead Bias*).
  * Criação de 17 novos testes unitários e de integração (`test_paper_adapter.py`, `test_windows_mt5_adapter.py`, `test_data_collector.py`, `test_parquet_store.py`).
  * Suíte de testes expandida para 45 testes com 100% de sucesso (`45 passed in 2.52s`).

---

## [0.2.0-phase1] — 2026-11-07

### Adicionado
* **FASE 1 — Fundação Concluída:**
  * Instalação e validação do ambiente: `MetaTrader5-5.0.6231`, `pytest-9.2.0`, `pytest-asyncio-1.4.1.post1`.
  * Criação da árvore completa de 35 diretórios com arquivos de pacote `__init__.py`.
  * Criação do pacote `core/models/` com contratos Pydantic V2 imutáveis (`HermesBaseModel`).
  * Exportação canônica em `intelligence/schemas/`.
  * Sistema de logging estruturado `core/logger.py` com sanitização recursiva de senhas, chaves de API e tokens.
  * Carregador de configurações tipado `core/config.py` com garantia irrevogável do `_HARDCODED_FLOOR`.
  * Barramento de eventos assíncrono `core/event_bus.py` com fila de prioridades estrita (`EMERGENCY = 0`).
  * Suíte de testes automatizados com 28 testes reais com 100% de sucesso.

---

## [0.1.0-phase0] — 2026-11-07

### Adicionado
* **FASE 0 — Auditoria e Planejamento Concluída:**
  * Clonagem e inspeção forense dos 6 repositórios de referência.
  * Relatórios de auditoria, comparação, licenças, decisões de reuso, arquitetura e segurança.
  * Registros de Decisões Arquiteturais ADR-001 a ADR-008.
  * Constituição de Engenharia do projeto (`AGENTS.md`).
