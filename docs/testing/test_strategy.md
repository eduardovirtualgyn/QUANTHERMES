# Estratégia de Testes e Matriz de Validação
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/testing/test_strategy.md`  

---

## 1. Princípios da Estratégia de Testes

Seguindo as **Regras Inegociáveis de Engenharia (Seções 2, 4 e 21)**:
* **Nenhum módulo é considerado pronto apenas porque executou uma vez.**
* **Proibição de Testes Ocos:** É terminantemente proibido criar arquivos de teste que apenas realizem asserções de existência de arquivo (`assert file.exists()`) ou importação de módulo (`assert mod is not None`), conforme o vício detectado no repositório auditado *Nexus*.
* **Padrão AAA (Arrange, Act, Assert):** Todo teste deve preparar um cenário determinístico, executar a ação do componente e validar rigorosamente o comportamento esperado através de limites numéricos e estados.
* **Isolamento Total:** Testes unitários e de risco rodam 100% offline, utilizando mocks de adaptadores e bancos de dados SQLite em memória (`:memory:`), sem depender de rede externa ou de terminal MT5 aberto.

---

## 2. A Pirâmide de Testes do QUANT HERMES

```
           / \
          /   \         Testes de Aceitação / Forward Testing (Paper Trading MT5 Demo)
         /     \        ─────────────────────────────────────────────────────────────
        /       \       Testes de Recuperação e Reconciliação (Reconexão, Crash, Timeout)
       /         \      ─────────────────────────────────────────────────────────────────
      /           \     Testes de Integração e Risco (Circuit Breakers, Kill Switch, Guards)
     /             \    ─────────────────────────────────────────────────────────────────────
    /               \   Testes Unitários Puros (Cálculo de Lote, Consenso, Features, Indicadores)
   /─────────────────\  ─────────────────────────────────────────────────────────────────────────
```

---

## 3. Matriz dos Vinte Modos de Falha Obrigatórios

A suíte de testes automatizados do QUANT HERMES valida compulsoriamente os seguintes 20 cenários críticos de falha antes de qualquer liberação de versão:

| ID | Cenário de Falha / Estresse | Módulo Avaliado | Comportamento Esperado do Sistema |
| :--- | :--- | :--- | :--- |
| **TC-01** | Dados de mercado corrompidos, NaNs ou preços negativos | Data Engine / Features | Sanitização automática ou rejeição do candle; sinal não é gerado. |
| **TC-02** | Perda súbita de conexão com o terminal MT5 | Execution Engine / Adapter | Detecção pelo Heartbeat Veto; transição para estado OFFLINE; suspensão de novas ordens. |
| **TC-03** | Reconexão após queda temporária de rede | Adapter / Reconciler | Reautenticação suave; sincronização do estado da conta e das posições abertas. |
| **TC-04** | Emissão de múltiplos sinais idênticos pelo mesmo agente | Consensus Engine | Deduplicação automática com base em janela temporal e hash de sinal. |
| **TC-05** | Envio concorrente de ordens duplicadas | Execution Engine | Bloqueio por `idempotency_key` único; apenas uma ordem é despachada. |
| **TC-06** | Corretora rejeita ordem (ex: Mercado fechado, Preço mudou) | Execution Engine | Captura do código de erro (retcode); registro auditável; sem retry cego infinito. |
| **TC-07** | Spread momentâneo excede 2.5× a média histórica | Risk Engine | Bloqueio imediato da operação antes do envio ao mercado. |
| **TC-08** | Slippage real excede a tolerância máxima permitida | Execution Engine | Alerta de desvio de execução registrado na telemetria; atualização do modelo de custos. |
| **TC-09** | Saldo ou margem livre insuficiente para a operação | Risk Engine / OrderCheck | Ordem abortada no pré-vôo com código `REJEITADA_MARGEM_INSUFICIENTE`. |
| **TC-10** | Proposta de trade sem Stop Loss ou com SL inválido/invertido | Risk Engine | Rejeição compulsória; nenhuma ordem trafega sem Stop Loss numérico válido. |
| **TC-11** | Falha de conexão ou crash do serviço Redis | Infrastructure / Events | Fallback para fila em memória (`asyncio.Queue`); preservação do estado local. |
| **TC-12** | Indisponibilidade do banco de dados relacional PostgreSQL | Storage / Telemetria | Gravação em cache local WAL (Write-Ahead Log) em SQLite/Parquet sem interromper o risco. |
| **TC-13** | Reinicialização súbita do processo do QUANT HERMES | State Recovery Engine | Recuperação completa do estado ao iniciar (equity inicial, perdas do dia, tickets ativos). |
| **TC-14** | Reconciliação de posições órfãs na corretora | Portfolio / Reconciler | Identificação de ordens executadas sem confirmação local; sincronização ativa. |
| **TC-15** | Violação dos limites de perda diária (1.5%) ou semanal (3.0%)| Risk Engine | Disparo do Daily/Weekly Guard; transição para bloqueio de novas entradas. |
| **TC-16** | Disparo manual ou autônomo do Kill Switch | Kill Switch Controller | Fechamento imediato de todas as posições a mercado; cancelamento de pendentes; freeze global. |
| **TC-17** | Múltiplos agentes emitindo sinais no mesmo instante | Consensus Engine | Processamento assíncrono thread-safe sem corrupção de estado ou deadlocks. |
| **TC-18** | Consenso contraditório (ex: 50% BUY e 50% SELL com mesma força)| Consensus Engine | Composite Score próximo de zero; decisão final obrigatória de **HOLD**. |
| **TC-19** | Falta ou corrupção de dados da conta (`account_state is None`)| Risk Engine / Guard | **Fail-Safe Imediato:** Rejeição da ordem e bloqueio operacional (correção do bug do Multi-Agent Quant). |
| **TC-20** | Transição brusca de regime de mercado (ex: Tendência para Volatilidade Extrema)| Regime / Portfolio | Redução instantânea de exposição em 50% ou zeragem de posições scalper. |

---

## 4. Testes de Não-Antecipação (*Anti-Lookahead Bias*)

Para garantir que os backtests e validações estatísticas reflitam a realidade operacional:
1. **Verificação de Timestamps:** Toda função que processa indicadores históricos é testada com dados cuja última barra é $T$. O teste injeta artificialmente uma barra em $T+1$ e valida que a saída numérica em $T$ permanece estritamente invariável.
2. **Auditoria de Calendário Econômico:** Garante que o indicador de notícias retorne `None` para qualquer evento cujo horário de divulgação seja posterior ao timestamp da barra de teste.

