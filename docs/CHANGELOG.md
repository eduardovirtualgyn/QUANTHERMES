# Changelog — QUANT HERMES
Todas as alterações notáveis deste projeto serão documentadas neste arquivo.
O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/) e adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

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
