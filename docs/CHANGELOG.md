# Changelog — QUANT HERMES
Todas as alterações notáveis deste projeto serão documentadas neste arquivo.
O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/) e adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

---

## [0.2.0-phase1] — 2026-11-07

### Adicionado
* **FASE 1 — Fundação Concluída:**
  * Instalação e validação do ambiente: `MetaTrader5-5.0.6231`, `pytest-9.2.0`, `pytest-asyncio-1.4.1.post1`.
  * Criação da árvore completa de 35 diretórios com arquivos de pacote `__init__.py`.
  * Criação do pacote `core/models/` com contratos Pydantic V2 imutáveis (`HermesBaseModel`):
    * `MarketTick` e `MarketBar` com cálculo automático de spread e validações de coerência OHLC.
    * `AgentSignal` e `ConsensusDecision` com validações direcionais rígidas (SL < Entrada para BUY, SL > Entrada para SELL).
    * `RiskAuthorization` soberano com exigência obrigatória de Stop Loss numérico e lote positivo.
    * `AccountState`, `Position`, `OrderRequest`, `OrderResult`, `RegimeClassification`.
  * Exportação canônica em `intelligence/schemas/`.
  * Sistema de logging estruturado `core/logger.py` com sanitização recursiva de senhas, chaves de API e tokens em strings e dicionários.
  * Carregador de configurações tipado `core/config.py` com garantia irrevogável do `_HARDCODED_FLOOR` (risco máximo de 0.50%, perda diária máxima de 2.0%, Stop Loss mandatório).
  * Barramento de eventos assíncrono `core/event_bus.py` com fila de prioridades estrita (`EMERGENCY = 0`), rastreamento de heartbeats e Dead-Letter Queue.
  * Suíte de testes automatizados com 28 testes reais em `tests/contract/`, `tests/security/`, `tests/unit/` com 100% de sucesso (`28 passed in 0.25s`).

---

## [0.1.0-phase0] — 2026-11-07

### Adicionado
* **FASE 0 — Auditoria e Planejamento Concluída:**
  * Clonagem e inspeção forense dos 6 repositórios de referência (`Samvid`, `Nexus`, `Multi-Agent Quant`, `MT5 Portfolio Framework`, `TradingAgents`, `EA31337`).
  * Relatório de Auditoria Forense com caminhos e referências de linhas de código (`docs/research/repository_audit.md`).
  * Matriz Comparativa Sistemática dos repositórios (`docs/research/repository_comparison.md`).
  * Auditoria de Licenças e parecer de risco de copyleft (`docs/research/license_audit.md`).
  * Matriz de Decisões de Reuso e Engenharia Clean-Room (`docs/research/reuse_decisions.md`).
  * Especificação da Arquitetura Geral das 10 camadas do sistema (`docs/architecture/system_architecture.md`).
  * Mapeamento do Fluxo de Dados e contratos de mensagens (`docs/architecture/data_flow.md`).
  * Arquitetura e topologia dos 8 agentes especializados (`docs/architecture/agent_architecture.md`).
  * Arquitetura da Camada de Execução e Adaptador MT5 COM (`docs/architecture/execution_architecture.md`).
  * Modelo de Segurança e Inviolabilidade do Motor de Risco (`docs/security/security_model.md`).
  * Estratégia de Testes cobrindo os 20 modos de falha e testes anti-lookahead (`docs/testing/test_strategy.md`).
  * Registros de Decisões Arquiteturais ADR-001 a ADR-008 (`docs/decisions/architecture_decisions.md`).
  * Constituição de Engenharia do projeto (`AGENTS.md`).
  * Mapeamento de status e inventário de ambiente (`docs/PROJECT_STATUS.md`).
