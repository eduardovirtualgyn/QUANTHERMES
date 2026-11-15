# PROPOSTA DA PRÓXIMA MISSÃO ESTRATÉGICA
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Documento:** `docs/audit/NEXT_MISSION.md`  
**Data:** 07 de Novembro de 2026  
**Auditor Responsável:** Auditoria Técnica Independente / Antigravity  

---

## 1. DIRETRIZ ESTRATÉGICA FUNDAMENTAL

A auditoria técnica demonstrou que o QUANT HERMES possui código executável robusto e 173 testes aprovados cobrindo as Fases 1 a 7. No entanto, avançar imediatamente para a construção de interfaces visuais (Fase 8), conteinerização Linux (Fase 9) ou operação com capital real (Fase 10) violaria as regras inegociáveis de engenharia financeira devido à existência de duas dívidas técnicas graves:
1. **Dívida de Risco de Execução (P0):** A janela de idempotência do `OrderExecutor` reside na memória RAM, suscetível a envios duplicados de ordens em caso de crash e reinicialização rápida.
2. **Dívidas de Integridade Quantitativa (P1):** A purga do Walk-Forward por índice discreto e a premissa IID no Monte Carlo subestimam caudas grossas e riscos de drawdown em regimes extremos.

Portanto, a próxima missão técnica **NÃO DEVE SER A FASE 8**.  
A próxima missão deve ser estritamente focada na **Remediação Técnica das Fases 6.1 e 7.1**.

---

## 2. ESCOPO DA PRÓXIMA MISSÃO: MISSÃO DE REMEDIAÇÃO TÉCNICA E HOMOLOGAÇÃO DE EXECUÇÃO (FASES 6.1 E 7.1)

### Objetivo da Missão:
Blindar a integridade matemática e a segurança de execução do QUANT HERMES antes de qualquer integração visual ou implantação em infraestrutura externa.

### 2.1. Bloco de Remediação de Execução Soberana (Fase 7.1)
1. **Persistência Atômica de Idempotência:**
   - Criar `SqliteIdempotencyStore` em modo WAL (`journal_mode=WAL`) para registro transacional e síncrono de todas as chaves de ordem antes do despacho ao MT5.
   - Garantir que um crash do processo Python seguido de reinicialização imediata rejeite qualquer ordem duplicada submetida na janela de segurança de 60 segundos.
2. **Persistência de Cooldown do Portfolio Manager:**
   - Salvar o mapa de timestamps do último trade por símbolo em disco de forma atômica para impedir que reinicializações do orquestrador burlem o cooldown.
3. **Simulador de Falhas de Comunicação MT5 (Fault Injection Harness):**
   - Criar suíte de testes de estresse que injeta timeouts de socket, respostas parciais (*partial fills*) e erros de requote durante o envio de ordens.
   - Validar que o reconciliador de posições detecta descompassos e aciona o Kill-Switch preventivo em $< 100\text{ ms}$.

### 2.2. Bloco de Remediação da Integridade Quantitativa (Fase 6.1)
1. **Correção do Motor de Monte Carlo:**
   - Implementar *Block Bootstrap* (preservando dependência temporal em blocos de $N$ trades) ou simulação baseada em matriz de transição de Markov para modelar clustering de volatilidade e sequências de perdas.
2. **Purga Temporal Contínua no Walk-Forward:**
   - Substituir o corte por índice ordinal no `PurgedWalkForwardValidator` por intervalo temporal real baseado em `pd.Timedelta`, eliminando vazamento de dados em fins de semana e feriados.
3. **Avaliação Econômica Real de Folds:**
   - Conectar o `BacktestEngine` à rotina de avaliação de folds de validação cruzada para computar custos de spread dinâmico e slippage fracionário.

### 2.3. Saneamento do Módulo de Monitoramento (Fase 8)
1. **Correção do Loop de Telemetria WebSocket:**
   - Refatorar o endpoint `/ws/telemetry` em `monitoring/server.py` para utilizar cancelamento cooperativo via `asyncio.Event` e tratamento limpo de `WebSocketDisconnect`.
   - Garantir que a suíte `tests/unit/test_monitoring_api.py` execute em $< 3$ segundos sem congelar o runner do pytest.

---

## 3. CRITÉRIOS DE ACEITAÇÃO PARA CONCLUSÃO DA PRÓXIMA MISSÃO

Para que a missão de remediação seja considerada concluída, as seguintes evidências deverão ser apresentadas:
1. **Suíte Completa Executada:** Todos os 173 testes atuais + novos testes de persistência de idempotência e falha de socket passando com 100% de sucesso.
2. **Prova de Recuperação de Crash:** Teste automatizado demonstrando que após `os.kill(process_id)` no momento do despacho da ordem, o sistema reinicia e bloqueia a duplicata da ordem com sucesso.
3. **Relatório de Estresse de Monte Carlo Atualizado:** Comparativo estatístico comprovando o aumento da probabilidade estimada de ruína sob o regime de caudas grossas (*Block Bootstrap*).
4. **Fase 8 Estabilizada:** Endpoint de telemetria rodando sem vazamento de memória ou travamento em testes automatizados.

---

## 4. SEQUÊNCIA DE FASES PROPOSTA

```
[Auditoria Concluída]
         │
         ▼
[Missão Fases 6.1 e 7.1: Remediação de Idempotência e Matemática]  ◄─── (PRÓXIMA MISSÃO OBRIGATÓRIA)
         │
         ▼
[Fase 8: Dashboard, API e Telemetria Estabilizados]
         │
         ▼
[Fase 9: Arquitetura de Implantação Linux / Dual-Node Bridge]
         │
         ▼
[Fase 10: Homologação em MetaTrader 5 Demo por 30 Dias]
```

