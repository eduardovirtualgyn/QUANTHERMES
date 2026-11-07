# Decisões de Reuso e Engenharia de Componentes
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/research/reuse_decisions.md`  

---

## 1. Classificação das Decisões de Engenharia

Conforme exigido pelo Protocolo de Engenharia do QUANT HERMES, dividimos todos os componentes analisados nos 6 repositórios de referência em três categorias estritas:

1. **Componentes Aproveitáveis (Princípios / Padrões Adotados):** Conceitos técnicos validados que serão reimplementados de forma limpa (*clean-room*) com tipagem moderna.
2. **Componentes a Reescrever:** Ideias quantitativas ou arquiteturais que continham falhas graves, bugs conceituais ou fragilidades nos repositórios originais e que exigem reconstrução matemática completa.
3. **Componentes Rejeitados:** Código descartado por contaminação de licença (AGPL/GPL), complexidade injustificada (*bloat*), ou incompatibilidade operacional.

---

## 2. Detalhamento por Repositório

### 2.1 Samvid Trading Core
* **Aproveitáveis:**
  * Padrão de *Heartbeat Veto*: monitoramento contínuo da integridade das conexões e dados; se um batimento cardíaco expirar, as operações são suspensas.
  * Padrão de *Friction Veto*: rejeição imediata de propostas de trade onde a relação Risco:Retorno líquida não cobre spread + slippage + comissões.
  * Metodologia de testes unitários isolados com SQLite em memória (`:memory:`) simulando banco de ordens sem tocar no disco ou na rede.
* **A Reescrever:**
  * O barramento de inteligência: o Samvid usa um modelo assíncrono genérico; no QUANT HERMES construiremos um barramento com contratos tipados Pydantic V2 e garantia de ordem temporal de mensagens.
* **Rejeitados:**
  * Módulos experimentais: `audio/`, `vr/`, `ios/`, `android/`, `cuda/`, `hardware/`, `voice/`.
  * O stub fictício de MetaTrader 5 em `console.py`.

### 2.2 Nexus Trading System MT5
* **Aproveitáveis (Conceitualmente — Clean-Room):**
  * Conceito de *Pisos Invioláveis de Risco (`_HARDCODED_MIN`)*: limites de segurança codificados no motor de risco que nenhuma configuração em YAML ou decisão de agente pode afrouxar.
  * Mapeamento de sufixos de símbolos de corretora (`EURUSD.m`, `EURUSD_i`) via dicionário de aliases normalizado.
  * Tratamento do código de retorno MT5 `10027` (*AutoTrading disabled by client*).
* **A Reescrever:**
  * Camada de execução assíncrona do MT5: eliminar o `ThreadPoolExecutor(max_workers=4)` e substituir por um executor single-thread dedicado (`max_workers=1`) com fila serializada, eliminando erros de colisão COM/STA no Windows.
* **Rejeitados:**
  * **Todo o código-fonte** (impedimento legal intransponível da licença AGPL-3.0).
  * A suíte de testes superficial que apenas valida existência de arquivos (`test_file_exists`).

### 2.3 Multi-Agent Quant
* **Aproveitáveis:**
  * Estruturação modular de guardas de risco independentes (`AccountGuard`, `DailyGuard`, `ExposureGuard`, `CorrelationGuard`).
* **A Reescrever:**
  * **Motor de Consenso e Fusão:** Reescrever totalmente a formulação. No Multi-Agent Quant, a confiança é ignorada no cálculo do voto; no QUANT HERMES, a confiança calibrada multiplicará diretamente a direção do sinal:
    $$\text{Score} = \sum_{i} \left( w_i \times \text{dir}_i \times \text{conf}_i \times \text{qualidade}_i \right)$$
  * **Tratamento de Falha no Account Guard:** No Multi-Agent Quant, a ausência de estado da conta (`account_state is None`) deixa o sinal passar livremente. No QUANT HERMES, a falta de dados da conta ativa o modo **Fail-Safe** com rejeição total e bloqueio de novas operações.
* **Rejeitados:**
  * Limites de risco e drawdown irresponsáveis (ex: drawdown máximo de 50%).

### 2.4 MT5 Portfolio Framework
* **Aproveitáveis:**
  * Lógica matemática de dimensionamento de lote de `PositionSizer.mqh`: cálculo exato via `OrderCalcProfit` em tempo de execução, respeito estrito a `volMin`, `volMax` e arredondamento para baixo com base no `volStep` (`MathFloor`).
  * Filosofia fundamental: estratégias apenas geram sinais analíticos; o Portfolio Manager aloca capital; o Risk Engine autoriza a execução.
  * Suíte de testes unitários nativa para validação numérica de lotes em MQL5.
* **A Reescrever:**
  * Registro de posições (`PositionRegistry`): expandir o rastreamento por `magic number` para permitir reconciliação virtual em contas do tipo **Netting** (além das contas **Hedging** nativas).
* **Rejeitados:**
  * Estratégias demonstrativas simples baseadas em cruzamento de médias móveis sem validação estatística fora da amostra.

### 2.5 TradingAgents
* **Aproveitáveis:**
  * Orquestração em grafo de agentes com LangGraph, utilizando checkpoints de estado persistentes.
  * Mecanismo de debate dialético adversarial entre pesquisadores com vieses opostos (Bull vs. Bear) e debatores de risco (Conservador vs. Agressivo).
  * Protocolo estrito de prevenção de *Lookahead Bias* com testes automatizados garantindo que nenhuma informação futura seja vazada para os analistas.
* **A Reescrever:**
  * Estratégia de invocação dos LLMs: o TradingAgents aciona LLMs síncronos em todas as decisões. No QUANT HERMES, o sistema operará em **Duplo Modo**:
    1. *Fast Quant Path:* Decisão de scalping ultra-rápida (sub-segundo) baseada exclusivamente em modelos matemáticos determinísticos, XGBoost/LightGBM e regras estruturais.
    2. *Deep Research Path:* Acionamento periódico e assíncrono dos LLMs para contextualização macroeconômica, análise de calendário e revisão de regime, sem bloquear a esteira de execução de ordens.
* **Rejeitados:**
  * Chamadas de LLM bloqueantes durante a execução de ordens em timeframes curtos (M1/M5).

### 2.6 EA31337
* **Aproveitáveis:**
  * Padronização de structs e contratos de parâmetros de indicadores técnicos em MQL5.
* **A Reescrever:**
  * Nenhuma reescrita direta.
* **Rejeitados:**
  * **Todo o código-fonte** (impedimento legal da licença GPL-3.0 e complexidade legada com código MQL4/MQL5 híbrido e submódulos Git fragmentados).

---

## 3. Resumo das Decisões de Engenharia para o QUANT HERMES

| Componente | Origem Inspiracional | Ação Adotada | Impacto Arquitetural |
| :--- | :--- | :--- | :--- |
| **Event Bus & Heartbeat** | Samvid | Clean-room Pydantic V2 + asyncio | Resiliência assíncrona com veto por inatividade |
| **Risk Floor Inviolável** | Nexus | Clean-room Python | Impossibilidade de IA/YAML degradar segurança |
| **MT5 Single-Thread Worker** | Diagnóstico próprio sobre o Nexus | Clean-room Python com fila serializada | Eliminação de falhas COM/STA no Windows |
| **Consenso Ponderado Real** | Correção de falha do Multi-Agent Quant | Formulação matemática original com calibração | Votos ponderados por confiança e regime |
| **Fail-Safe Account Guard** | Correção de falha do Multi-Agent Quant | Bloqueio compulsório se dados da conta faltarem | Zero risco de execução desprotegida |
| **Position Sizer Preciso** | MT5 Portfolio Framework | Reimplementação Python + MQL5 | Lote exato via `OrderCalcProfit` sem rounding up |
| **Reconciliação Hedging/Netting** | Extensão sobre MT5 Portfolio Framework | Mapeamento virtual de posições | Compatibilidade com qualquer modalidade de corretora |
| **LangGraph Adversarial Assíncrono**| TradingAgents | Clean-room LangGraph desacoplado do scalping | Inteligência de ponta sem latência no tick rápido |
| **Auditoria Anti-Lookahead** | TradingAgents | Testes de integridade temporal de dados | Eliminação de vazamento de dados futuros no backtest |

