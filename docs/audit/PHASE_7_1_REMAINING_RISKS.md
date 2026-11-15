# INVENTÁRIO DE LIMITAÇÕES E RISCOS REMANESCENTES (PÓS-FASE 7.1)
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Documento:** `docs/audit/PHASE_7_1_REMAINING_RISKS.md`  
**Data:** 07 de Novembro de 2026  
**Auditor Responsável:** Engenharia Quantitativa / Antigravity  

---

## 1. RISCOS MITIGADOS PELA FASE 7.1

A conclusão da Fase 7.1 eliminou os seguintes riscos críticos:
1. **Duplicação de Ordens por Crash de Processo:** Mitigado via `SqliteIdempotencyStore` (WAL) com escrita pré-socket e restrição `UNIQUE` em banco de dados.
2. **Reenvio Cego em Perda de Conexão:** Mitigado via estado `RECONCILIATION_REQUIRED`.
3. **Inconsistência de Execuções Parciais:** Mitigado com distinção de `PARTIALLY_FILLED` e retenção de volumes remanescentes.
4. **Vulnerabilidade de Inicialização Desassistida:** Mitigado com cruzamento automático de ordens pendentes contra posições abertas no MT5 no startup.

---

## 2. RISCOS E LIMITAÇÕES TÉCNICAS REMANESCENTES

Apesar da eliminação da vulnerabilidade P0 de idempotência, persistem limitações estruturais que impedem a operação autônoma com capital real antes da conclusão das fases subsequentes:

### 2.1. Limitação de Histórico de Ordens Fechadas no MT5 (Risco P1)
- **Descrição:** O método atual de recuperação no startup (`recover_unresolved_orders`) consulta `adapter.get_open_positions()`. Se a ordem ambígua tiver sido aberta no broker, preenchida e fechada imediatamente por Stop Loss em $< 1$ segundo antes do reinício do sistema, ela não constará em `open_positions`.
- **Mitigação Atual:** O sistema marca a intenção como `RECONCILIATION_REQUIRED` e bloqueia reenvio.
- **Melhoria Futura (Fase 10):** Implementar consulta ao histórico de negócios fechados (`history_deals_get`) via adapter MT5 para identificar preenchimentos ultra-rápidos que já foram encerrados.

### 2.2. Suposição IID no Monte Carlo e Purga Walk-Forward (Risco P1 — Fase 6.1)
- **Descrição:** O motor analítico ainda possui as dívidas conceituais identificadas na auditoria:
  1. Monte Carlo utiliza bootstrap IID, subestimando sequências de perdas por agrupamento de volatilidade.
  2. Validação cruzada purga por contagem de barras e não por intervalo de tempo contínuo.
- **Ação Requerida:** Execução da **Fase 6.1 (Remediação Quantitativa)** antes de homologação financeira.

### 2.3. Estabilização do Módulo de Telemetria e Dashboard (Risco P1 — Fase 8)
- **Descrição:** O arquivo `monitoring/server.py` ainda necessita de ajuste no loop de WebSocket para suportar desconexões limpas de clientes sem travamento de testes de CI/CD.
- **Ação Requerida:** Execução da **Fase 8**.

### 2.4. Portabilidade para Linux VPS (Risco P2 — Fase 9)
- **Descrição:** A API oficial `MetaTrader5` continua sendo exclusiva para Windows 64-bit, exigindo arquitetura de nó duplo ou Wine para implantação em servidores Linux.

---

## 3. TABELA CONSOLIDADA DE PRONTIDÃO PÓS-FASE 7.1

| Nível Operacional | Status Atual | Condição para Liberação |
| :--- | :---: | :--- |
| **Paper Trading Simulado** | `LIBERADO E VALIDADO` | Pronto para testes contínuos de estresse |
| **MetaTrader 5 Demo** | `HOMOLOGAÇÃO SUPERVISIONADA` | Liberado para testes com operador presente monitorando logs |
| **MetaTrader 5 Live (Capital Real)** | `ESTRITAMENTE PROIBIDO` | Requer saneamento da Fase 6.1, Fase 8 e 30 dias de Paper Trading ininterrupto |

