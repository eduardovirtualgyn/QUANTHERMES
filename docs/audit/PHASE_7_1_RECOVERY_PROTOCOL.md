# PROTOCOLO DE RECUPERAÇÃO E RECONCILIAÇÃO PÓS-CRASH (FASE 7.1)
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Documento:** `docs/audit/PHASE_7_1_RECOVERY_PROTOCOL.md`  
**Data:** 07 de Novembro de 2026  
**Classificação:** Manual Operacional de Recuperação / Procedimento Padrão  

---

## 1. PRINCÍPIO OPERACIONAL FUNDAMENTAL

> **"A segurança financeira do capital tem precedência absoluta sobre a disponibilidade do sistema. Diante de qualquer ambiguidade de execução ou interrupção de processo, o sistema bloqueia novos envios e exige confirmação factual antes de reestabelecer o ciclo de ordens."**

---

## 2. FLUXO DETALHADO DO PROTOCOLO DE INICIALIZAÇÃO

Ao iniciar ou reiniciar o `AutonomousTradingOrchestrator`, a seguinte sequência determinística de 6 etapas é obrigatoriamente executada antes que qualquer tick ou sinal de mercado seja processado:

```
                  ┌────────────────────────────────────────┐
                  │ 1. Inicialização do Orquestrador       │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ 2. Abertura do Banco SQLite WAL        │
                  │    (PRAGMA integrity_check)            │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ 3. Conexão ao Terminal / Broker MT5    │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ 4. Varredura de Intenções Não          │
                  │    Resolvidas (SUBMITTING/AMBIGUOUS)   │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ 5. Consulta e Cruzamento com Posições  │
                  │    Abertas no MT5 (Magic + Símbolo)    │
                  └───────────────────┬────────────────────┘
                                      │
                      ┌───────────────┴───────────────┐
                      │                               │
        [Posição Localizada no Broker]   [Posição Ausente no Broker]
                      │                               │
                      ▼                               ▼
        ┌──────────────────────────┐    ┌──────────────────────────┐
        │ Atualiza estado SQLite   │    │ Marca como               │
        │ para FILLED ou           │    │ RECONCILIATION_REQUIRED  │
        │ PARTIALLY_FILLED         │    │ Bloqueia reenvio cego    │
        │ Vincula ticket da ordem  │    │ Exige auditoria          │
        └─────────────┬────────────┘    └─────────────┬────────────┘
                      │                               │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ 6. Reconciliação Geral de Posições     │
                  │    (Detecção de Órfãs e Fantasmas)     │
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ 7. Sistema Liberado para Operação      │
                  │    (system_status = "RUNNING")         │
                  └────────────────────────────────────────┘
```

---

## 3. IDENTIFICAÇÃO DE OPERAÇÕES AMBÍGUAS

Uma ordem é classificada como **ambígua** quando ocorre:
1. `ConnectionResetError`, `TimeoutError` ou perda de socket durante `send_order`.
2. Interrupção abrupta de energia ou encerramento compulsório do processo Python enquanto o estado persistido for `SUBMITTING` ou `SUBMITTED`.
3. Ausência de confirmação imediata da corretora após o envio da mensagem ao servidor.

### Procedimento de Mitigação:
- A intenção permanece registrada com a chave `idempotency_key` no banco de dados.
- O estado é gravado como `RECONCILIATION_REQUIRED`.
- **Regra Inegociável:** Sob nenhuma hipótese o sistema reenvia uma ordem ambígua de forma cega. Uma nova ordem com os mesmos parâmetros é sumariamente descartada como duplicata.

---

## 4. DIRETRIZES PARA INTERVENÇÃO HUMANA

Quando o relatório de inicialização contiver itens com status `MARKED_RECONCILIATION_REQUIRED`, o operador humano ou analista de risco deve:
1. Abrir o terminal MetaTrader 5 e verificar o histórico de ordens (`Histórico` / `Deals`) para o horário correspondente.
2. Confirmar se a ordem foi rejeitada pela corretora ou se foi aberta sob um ticket específico.
3. Se confirmada rejeição no broker, o operador pode atualizar manualmente o registro ou purgar a intenção através de comando administrativo.
4. Se a ordem foi aberta no broker, o ticket deve ser inserido no gerenciador de estado.

