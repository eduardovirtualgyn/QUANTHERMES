# PROTOCOLO OPERACIONAL DE PAPER TRADING DE 30 DIAS (FASE 10)
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Documento:** `docs/audit/PHASE_10_PAPER_TRADING_PROTOCOL.md`  
**Data:** 15 de Novembro de 2026  
**Auditor Responsável:** Engenharia de Sistemas e Arquitetura Quantitativa / Antigravity  
**Ambiente Alvo:** MetaTrader 5 Demo (RoboForex-Demo / Broker Institucional)  
**Conformidade:** Constituição de Engenharia (`AGENTS.md`) — Regras 1 a 15  

---

## 1. OBJETIVO DO PROTOCOLO

Este protocolo estabelece as diretrizes obrigatórias para a execução do ciclo de **30 dias ininterruptos de Paper Trading** do QUANT HERMES antes de qualquer deliberação sobre transição para contas de produção com capital real.

O objetivo do período de 30 dias não é unicamente medir lucratividade, mas comprovar a **robustez operacional, a estabilidade de rede, a resiliência a anomalias de mercado e a imunidade a falhas humanas ou técnicas** sob condições de mercado ativas.

---

## 2. CRITÉRIOS QUANTITATIVOS DE ACEITAÇÃO (GO / NO-GO)

Para que a homologação da Fase 10 seja considerada formalmente aprovada para transição à produção, o sistema deve atender rigorosamente a todos os seguintes KPIs durante a janela de 30 dias:

| Métrica / Invariante | Meta Estrita (GO) | Limite Tolerado | Ação em Caso de Violação (NO-GO) |
| :--- | :---: | :---: | :--- |
| **Erros Não Tratados (Crashes)** | **0** | **0** | Reset imediato da contagem dos 30 dias; auditoria de código. |
| **Ordens Duplicadas Despachadas** | **0** | **0** | Falha crítica de idempotência; paralisação do sistema. |
| **Violações de Limites de Risco** | **0** | **0** | Veto soberano violado; suspensão mandatória. |
| **Drawdown Máximo Acumulado** | $\le 4.00\%$ | $< 8.00\%$ | Se atingir $8.00\%$, Kill Switch permanente e encerramento. |
| **Perda Diária Máxima Registrada** | $\le 1.00\%$ | $< 1.50\%$ | Se atingir $1.50\%$, desarme do `DailyLossGuard` até o dia seguinte. |
| **Discrepância de Slippage Médio** | $\le 0.8\text{ pips}$ | $\le 1.5\text{ pips}$ | Revisão dos limites de slippage por ativo. |
| **Latência Média de Execução** | $< 80\text{ ms}$ | $< 250\text{ ms}$ | Auditoria do túnel de rede / broker VPS. |
| **Reconciliação com Broker** | $100\%$ Sincronizada | $\Delta \le 1\text{ barra}$ | Auto-correção atômica; alerta em caso de desvio persistente. |
| **Profit Factor Líquido (30 dias)**| $\ge 1.30$ | $\ge 1.15$ | Re-calibração purgada fora da amostra (Fase 6.1). |

---

## 3. ROTINA OPERACIONAL DIÁRIA (CHECKLIST DO OPERADOR)

### 3.1. Pré-Abertura (06:00 UTC)
1. **Verificação de Integridade do Banco de Idempotência:**
   - Executar `python scripts/run_preflight_checks.py`.
   - Confirmar `PRAGMA integrity_check = ok` no SQLite WAL.
2. **Auditoria de Estado do Kill Switch:**
   - Verificar `data/storage/kill_switch_state.json`. Confirmar `is_active = false`.
3. **Reconciliação Inicial de Posições:**
   - O orquestrador executa `recover_unresolved_orders()` e `PositionReconciler.reconcile()`.
   - Confirmar ausência de tickets órfãos ou fantasmas.

### 3.2. Operação Ativa Contínua (24/5)
1. **Monitoramento via Dashboard Telemetria (Porta 8000):**
   - Telemetria de ticks em tempo real via WebSocket `/ws/telemetry`.
   - Acompanhamento do estado dos Circuit Breakers (`DailyLossGuard`, `WeeklyLossGuard`).
   - Monitoramento do uso de CPU e memória RAM do contêiner Docker ($< 70\%$).
2. **Reconciliação Cíclica Autônoma:**
   - Executada automaticamente a cada 30 barras M15 fechadas.

### 3.3. Fechamento de Fim de Semana (Sexta-feira 20:00 UTC)
1. **Ativação Compulsória do Weekend Risk Guard:**
   - Bloqueio automático de novas propostas de ordens após as 20:00 UTC.
2. **Geração e Backup do Diário de Operações:**
   - Executar `python scripts/backup_state.py`.
   - Exportação do diário `data/storage/trade_journal_{YYYYMMDD}.json`.
   - Rotação e retenção de logs com compressão `gzip`.

---

## 4. RUNBOOKS DE RESPOSTA A INCIDENTES E CONTINGÊNCIAS

### Cenário A: Queda da Conexão com o MetaTrader 5 (Socket Timeout)
1. **Comportamento Automático:**
   - O `LinuxMT5BridgeAdapter` detecta desconexão e entra em fail-closed.
   - Novas intenções são bloqueadas.
   - Ordens em trânsito são marcadas como `RECONCILIATION_REQUIRED`.
2. **Ação Operacional:**
   - Inspecionar logs em `data/logs/hermes_gateway.log`.
   - Se o terminal MT5 reiniciou, o orquestrador reconecta e roda reconciliação imediata.

### Cenário B: Acionamento do Circuit Breaker Diário (Perda Diária $\ge 1.50\%$)
1. **Comportamento Automático:**
   - `DailyLossGuard` desarma e veta novas autorizações de risco.
   - Posições em aberto continuam protegidas pelos seus respectivos Stop Losses.
2. **Ação Operacional:**
   - Nenhuma intervenção manual necessária. O freio desarma automaticamente à meia-noite (00:00 UTC).
   - Proibido forçar a reativação antes do reset programado.

### Cenário C: Acionamento Compulsório de Kill Switch (Drawdown $\ge 8.00\%$)
1. **Comportamento Automático:**
   - `EmergencyDrawdownGuard` ativa o `KillSwitch`.
   - O estado de parada compulsória é gravado atomicamente em disco.
   - Todas as posições abertas são sumariamente liquidadas a mercado.
2. **Ação Operacional:**
   - O sistema congela permanentemente.
   - É instaurada comissão de auditoria técnica.
   - O desarme do Kill Switch exige comando assinado com token seguro do operador (`HERMES_OPERATOR_TOKEN`).

---

## 5. RASTREABILIDADE E AUDITORIA COMPLETA

Todas as transações, sinais dos 8 agentes, decisões do comitê de consenso, autorizações de risco e mensagens de preenchimento são persistidas com timestamps UTC, hashes SHA-256 e vínculos de auditoria relacional, garantindo 100% de reproducibilidade para auditoria posterior.

