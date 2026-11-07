# Comparativo Sistemático dos Repositórios Auditados
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/research/repository_comparison.md`  

---

## 1. Matriz Comparativa Geral

A tabela a seguir consolida a avaliação técnica dos seis repositórios auditados, cruzando arquitetura, segurança, execução e maturidade de testes:

| Dimensão Técnica | Samvid Trading Core | Nexus Trading MT5 | Multi-Agent Quant | MT5 Portfolio Framework | TradingAgents | EA31337 | **QUANT HERMES (Meta)** |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Padrão de Arquitetura** | Monólito modular assíncrono | Microsserviços independentes | Pipeline orientado a estágios | Framework nativo MQL5 | Grafo de estados (LangGraph) | Monólito modular MQL híbrido | **Monólito Modular Assíncrono com Camadas Tipadas** |
| **Comunicação Interna** | Pub/Sub local (`asyncio`) | Redis Streams | Chamadas síncronas em pipeline | Chamadas de método diretas MQL | Propagação de estado em DAG/grafo | Chamadas de funções legadas | **Event Bus Assíncrono Tipado com Pydantic** |
| **Orquestração de Agentes** | Votação por quórum | Pipeline linear por agente | Média de votos ponderada simples | Sem agentes (Estratégias puras) | Grafo dialético (Bull vs Bear) | Sem agentes (Regras técnicas) | **Consenso Ponderado Bidirecional (Confiança + Regime)** |
| **Adequação para Scalping** | Média (sem MT5 real) | Baixa (latência Redis + concorrência) | Inadequada (LLM síncrono lento) | Alta (MQL5 puro no terminal) | Inadequada (LLM síncrono multi-turn) | Alta (MQL puro) | **Duplo Modo: Fast Quant (M1-M5) + Deep Research (Macro)** |
| **Rigor de Gestão de Risco** | Médio (Friction veto, Tail risk) | Alto em conceito (Pisos invioláveis) | **Baixo/Perigoso** (Drawdown 50%, bypass sem conta) | Alto (OrderCalcProfit, clamps, normalizações) | Médio (Debate qualitativo de risco) | Médio (SL/TP clássicos) | **Autoridade Superior Inviolável (Pisos rígidos + Kill Switch)** |
| **Integração Real MT5** | Falso stub (`console.py`) | Nativa via Python (`MetaTrader5`) | Nativa via Python (`MetaTrader5`) | Nativa direta em MQL5 | Nenhuma (Foco em ações/crypto) | Nativa direta em MQL | **TradingPlatformAdapter Abstrato + WindowsMT5 + Paper/Backtest** |
| **Qualidade da Suíte de Testes** | Alta (124 testes, SQLite isolado) | **Muito Baixa** (Testes apenas de importação/arquivo) | Média (Guarda e fusão testados) | Alta (Asserts matemáticos e de lote) | Alta (90 testes, lookahead bias testado) | Baixa (Incompleta sem submódulos) | **Pirâmide de Testes Completa: Unitário, Risco, Integração e Reconciliação** |
| **Licença Legal** | MIT | **AGPL-3.0 (Restritiva)** | MIT | MIT | Apache 2.0 | **GPL-3.0 (Restritiva)** | **Original Próprio (Clean-Room)** |

---

## 2. Análise Detalhada por Domínio de Engenharia

### 2.1 Orquestração Multiagente e Fusão de Sinais
* **TradingAgents vs. Multi-Agent Quant:**
  * O *TradingAgents* implementa o estado da arte em debate adversarial via LangGraph, permitindo que agentes com teses opostas (Bull vs. Bear) apontem pontos cegos em relatórios macroeconômicos e fundamentalistas. Entretanto, cada iteração leva de 15 a 45 segundos, inviabilizando qualquer timing em timeframes M1/M5.
  * O *Multi-Agent Quant* tentou construir um sistema de fusão multi-LLM, mas cometeu o erro matemático de calcular a confiança separadamente do directional score, de modo que uma confiança de 10% tem o mesmo peso de voto de uma de 99%.
  * **Solução QUANT HERMES:** Adotaremos a modelagem de grafos em LangGraph inspirada no TradingAgents para a inteligência profunda, mas criaremos um **Motor de Consenso Ponderado** formal onde o Score de Sinal é:
    $$\text{Score} = \sum_{i=1}^{n} \left( \text{peso}_i \times \text{direção}_i \times \text{confiança\_calibrada}_i \times \text{qualidade\_histórica}_i \right)$$
    com validação instantânea sem LLM em tempo de scalping.

### 2.2 Arquitetura de Risco e Segurança de Capital
* **Nexus Trading System vs. Multi-Agent Quant:**
  * O *Nexus* estabeleceu o conceito correto de **Pisos Invioláveis de Risco (`_HARDCODED_MIN`)**, onde arquivos externos de configuração podem apenas tornar as regras mais rígidas, nunca mais frouxas do que os limites de segurança codificados.
  * O *Multi-Agent Quant* exibiu falhas inaceitáveis: limites permissivos de 50% de drawdown e um bypass catastrófico em `account_guard.py` que não bloqueia operações quando a conta não responde.
  * O *MT5 Portfolio Framework* forneceu a melhor implementação de cálculo de lote, usando chamadas à API da corretora para calcular a perda financeira real de 1 lote e arredondando para baixo com respeito aos passos de volume (`volStep`).
  * **Solução QUANT HERMES:** O **Risk Engine** será construído como autoridade superior e autônoma. Conterá pisos rígidos no código, bloqueio imediato se o estado da conta for nulo ou desatualizado, cálculo dinâmico baseado em `OrderCalcProfit` e controle rígido de margem e correlação.

### 2.3 Camada de Execução MT5 e Restrições de Sistema Operacional
* **Problema COM no Windows:** O *Nexus* tentou usar `ThreadPoolExecutor(max_workers=4)` para o MetaTrader 5 no Windows, o que causa colisões na camada COM STA da DLL do MT5. A API Python do MetaTrader 5 não é thread-safe entre múltiplas threads concorrentes.
* **Solução QUANT HERMES:** Criaremos um ator/worker de execução com uma fila serializada (`Queue` assíncrona) rodando em uma única thread dedicada (`max_workers=1`), garantindo integridade de todas as chamadas `order_send`, `positions_get` e `account_info`.
* **Portabilidade para Linux:** Como o pacote oficial `MetaTrader5` roda nativamente apenas no Windows, o QUANT HERMES criará a interface abstrata `TradingPlatformAdapter`. A lógica quantitativa, de agentes e de risco será 100% agnóstica de sistema operacional, permitindo futura execução do cérebro quantitativo no Linux conectando via gRPC/ZeroMQ/FastAPI a um terminal MT5 rodando em Windows ou Wine validado.

---

## 3. Diretrizes de Projeto Derivadas do Comparativo

1. **Clean-Room Obrigatório:** Proibição de incorporação de trechos de código do *Nexus* (AGPL-3.0) e do *EA31337* (GPL-3.0).
2. **Zero Testes Ocos:** A suíte de testes do QUANT HERMES não se limitará a `test_file_exists` ou `test_importable`. Todo teste de risco deve validar valores limítrofes, falhas induzidas e rejeições seguras.
3. **Decisão do Portfólio Centralizada:** Estratégias e agentes sugerem; somente o Portfolio Manager aloca e o Risk Engine autoriza.
4. **Isolamento de Viés Temporal:** Adotar testes estritos contra lookahead bias para qualquer dado histórico, espelhando os padrões maduros do *TradingAgents*.

