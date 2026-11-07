# Relatório de Auditoria Forense dos Repositórios de Referência
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Data da Auditoria:** 07 de Novembro de 2026  
**Auditor Principal:** Equipe de Engenharia e Arquitetura Quantitativa HERMES  

---

## 1. Visão Geral da Auditoria

Em estrito cumprimento às **Regras Inegociáveis de Engenharia (Seção 2 e 3.7)** do projeto QUANT HERMES, foi executada a auditoria aprofundada dos 6 repositórios de referência. Cada repositório foi clonado em branch oficial, permitindo inspeção estática de código-fonte, mapeamento de dependências, checagem de licenças e validação da integridade dos testes automatizados.

---

## 2. Repositório 1: Samvid Trading Core

* **URL Oficial:** `https://github.com/AshishTalpada/samvid-trading-core`
* **Commit Auditado:** `0f40e76cadadf857cebba65303fb4154afc40b0a`
* **Branch:** `main`
* **Data do Commit:** Quinta-feira, 25 de Junho de 2026 (por Ashishkumar Talpada)
* **Licença:** MIT License (Permissiva)

### 2.1 Estrutura e Pontos de Entrada
* **Entrada Principal:** `src/demonstration.py`, `src/dashboard/console.py`
* **Estrutura de Diretórios:** `src/` modularizado em `brain/`, `execution/`, `risk/`, `macro/`, `feeds/`, `resilience/`, além de pastas experimentais/infladas (`audio/`, `vr/`, `ios/`, `android/`, `cuda/`, `wallets/`).
* **Dependências Chave:** `uv`, `pydantic`, `asyncio`, `sqlite3`, `questdb` (opcional).

### 2.2 Auditoria de Implementação vs. Documentação
1. **Falsa Integração MT5:** O README e o painel de status (`src/dashboard/console.py`, linha 19) anunciam integração com MetaTrader 5:
   ```python
   # src/dashboard/console.py linhas 19-27
   if component == "mt5":
       if (hasattr(system, "mt5_client") and system.mt5_client and system.mt5_client.terminal_info()):
           return "🟢 ONLINE"
   ```
   No entanto, em `src/execution/` **não existe nenhum adaptador real de MetaTrader 5** implementado. O sistema apenas verifica a existência dinâmica do atributo `mt5_client`. É um stub / funcionalidade declarada na documentação mas ausente no código.
2. **Complexidade Excessiva e Dispersão:** O repositório contém código não quantitativo (dublagem de áudio, realidade virtual, apps móveis nativos) que diluem o foco de um trading core robusto.

### 2.3 Análise de Testes Automatizados
* **Quantidade de Testes:** 124 arquivos de teste em `tests/`.
* **Pontos Fortes Encontrados:**
  * `tests/test_brain_execution_position.py`: Excelente padrão de teste com SQLite em memória (`:memory:`) desacoplado de corretora real para validar `_log_trade_exit`, R-múltiplo e lógica de Heartbeat Veto.
  * Testes de resiliência e estresse com injeção assíncrona (`stress_test_5000.py`, `test_black_swan_wiring.py`).

### 2.4 Veredito para o QUANT HERMES
* **Aproveitável (Conceitual):** Arquitetura assíncrona de barramento de eventos (Pub/Sub Intelligence Bus), conceito de Heartbeat Veto em posições abertas, testes isolados com banco de dados em memória.
* **Rejeitado:** Módulos periféricos irrelevantes (áudio, VR, hardware wallets) e o stub vazio de MT5.

---

## 3. Repositório 2: Nexus Trading System MT5

* **URL Oficial:** `https://github.com/MirandaCR/Nexus-Trading-System-MT5`
* **Commit Auditado:** `4c5e94975678c776f4e1fc7b3e2eaceeceb7fbe5`
* **Branch:** `main`
* **Data do Commit:** Quarta-feira, 28 de Outubro de 2026 (por MirandaCR)
* **Licença:** **GNU Affero General Public License v3 (AGPL-3.0)** — **ALERTA CRÍTICO**

### 3.1 Licença e Restrições Legais
* **Restrição Inegociável:** Sob a licença AGPL-3.0, qualquer código ou biblioteca incorporada obriga a distribuição de todo o sistema sob os mesmos termos de copyleft estrito, inclusive em redes/serviços de nuvem.
* **Decisão:** **REJEIÇÃO COMPLETA DE REUTILIZAÇÃO DIRETA DE CÓDIGO.** O QUANT HERMES adotará implementação 100% *clean-room* (reconstrução independente e original de ideias arquiteturais, sem importação de linhas de código).

### 3.2 Arquitetura de Microsserviços e Pontos de Entrada
* **Microsserviços:** Separados em `services/nexus_api`, `services/nexus_data`, `services/nexus_features`, `services/nexus_ml`, `services/nexus_agents`, `services/nexus_news`, `services/nexus_risk`, `services/nexus_executor`, `services/nexus_monitor`.
* **Mensageria:** Redis Streams para eventos entre serviços.

### 3.3 Auditoria de Código, Falhas e Vulnerabilidades Críticas
1. **Conflito Grave de Concorrência COM / MT5 no Windows:**
   Em `services/nexus_executor/mt5_executor.py`:
   ```python
   # Linhas 34-37
   _MT5_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
       max_workers=4,  # parallel order execution for scalping speed
       thread_name_prefix="mt5-executor-com",
   )

   async def _mt5_call(fn: Callable[[], Any]) -> Any:
       """Run all MetaTrader5 calls on one dedicated COM thread."""
       loop = asyncio.get_running_loop()
       return await loop.run_in_executor(_MT5_EXECUTOR, fn)
   ```
   **Vulnerabilidade Encontrada:** A docstring afirma executar em *"one dedicated COM thread"*, mas instancia `ThreadPoolExecutor(max_workers=4)`. A biblioteca oficial do MetaTrader 5 em Python no Windows opera via chamadas IPC/COM acopladas a Single-Threaded Apartments (STA). O envio de ordens simultâneas por 4 threads concorrentes causa erros frequentes de `IPC communication failure` ou perda de ponteiro de inicialização. Para MT5 no Windows, chamadas de API devem ser estritamente sequenciadas em uma fila de thread única dedicada (`max_workers=1`).
2. **Fraqueza Severa na Cobertura de Testes ("Testes Ocos"):**
   Em `tests/test_risk/test_rules_engine.py` e `tests/test_executor/test_broker_adapters.py`:
   ```python
   # Linhas 19-38
   def test_file_exists(self, filename: str):
       assert (RISK_SVC / filename).exists(), f"Missing risk file: {filename}"

   def test_importable(self):
       import importlib
       mod = importlib.import_module("services.nexus_risk.position_sizer")
       assert mod is not None
   ```
   Os testes da suíte apenas verificam se os arquivos existem no disco e se conseguem ser importados! Quase não há asserções dinâmicas de dimensionamento de lote, violação de drawdown, rejeição por spread ou circuit breakers.

### 3.4 Veredito para o QUANT HERMES
* **Aproveitável (Conceito Original Clean-Room):** Pisos invioláveis de risco protegidos contra alterações por arquivo YAML (`_HARDCODED_MIN`), tratamento de retcode 10027 (`AutoTrading disabled by client`), mapeamento de sufixos de símbolos via `MT5_SYMBOL_ALIASES`.
* **Rejeitado:** Código-fonte (proibição legal AGPL-3.0), pool multi-thread concorrente para API MT5 (risco de falha COM), testes superficiais sem validação de regras reais.

---

## 4. Repositório 3: Multi-Agent Quant

* **URL Oficial:** `https://github.com/Caesarcph/multi-agent-quant`
* **Commit Auditado:** `9acd48a075e127f1aa5a1c7b80acb54eacf2a186`
* **Branch:** `master`
* **Data do Commit:** Terça-feira, 03 de Novembro de 2026 (por Peihao Chen)
* **Licença:** MIT License (Permissiva)

### 4.1 Estrutura e Componentes
* **Componentes:** `agents/` (agentes LLM para GPT, Claude, Gemini, DeepSeek), `fusion/` (`fusion_engine.py`, `dynamic_weighting.py`), `risk/` (`account_guard.py`, `correlation_guard.py`, `daily_guard.py`, `exposure_guard.py`).

### 4.2 Auditoria de Vulnerabilidades Críticas e Confirmação de Falhas
1. **FALHA CRÍTICA CONFIRMADA — Separação Inadequada entre Confiança e Votação:**
   Em `fusion/fusion_engine.py` (linhas 77-94):
   ```python
   for signal in signal_list:
       action = signal.get("action")
       model = signal.get("model")
       weight = float(weights.get(model, 1.0))
       ...
       directional_score += ACTION_SCORE[action] * weight
       weighted_confidence += weight * float(signal.get("confidence", 0.0))
   ...
   normalized_score = directional_score / total_weight if total_weight else 0.0
   avg_confidence = weighted_confidence / total_weight if total_weight else 0.0

   if normalized_score >= buy_threshold:
       action = "BUY"
   elif normalized_score <= sell_threshold:
       action = "SELL"
   else:
       action = "HOLD"
   ```
   **Evidência:** O cálculo de `normalized_score` considera **apenas** `ACTION_SCORE[action] * weight`. A confiança do agente (`signal.get("confidence")`) é calculada à parte apenas como métrica estatística passiva (`avg_confidence`), e **não pondera a força do voto nem modula a decisão de compra/venda**! Um sinal emitido com confiança mínima (ex: 0.1) tem exatamente o mesmo poder de fogo de um voto com confiança 0.99. No QUANT HERMES, a formulação matemática do consenso multiplicará rigorosamente `peso_i × direcao_i × confianca_calibrada_i × qualidade_historica_i`.

2. **FALHA CRÍTICA CONFIRMADA — Ausência de Dados da Conta Permite Execução:**
   Em `risk/account_guard.py` (linhas 27-29):
   ```python
   def apply_account_limits(signal, account_state, config):
       output = deepcopy(signal)
       notes = []
       if not account_state:
           return output, notes  # <-- FALHA GRAVE: Deixa passar sem checar!
   ```
   **Evidência:** Se a conexão com o broker cair, se o MT5 não responder ou se `account_state` for `None`/vazio, o sistema silenciosamente retorna a ordem desprotegida e intacta para execução! No QUANT HERMES, vigora a regra inegociável de **Fail-Safe**: falta de informação da conta = **BLOQUEIO IMEDIATO E REJEIÇÃO TOTAL DA ORDEM**.

3. **FALHA DE ENGENHARIA DE RISCO — Drawdown Permissivo Irrealista:**
   Em `config/risk_config.yaml` (linhas 10-21):
   ```yaml
   account_level:
     max_drawdown: 0.50          # 50% de drawdown permitido!
     capital_preservation:
       trigger_drawdown: 0.50
   ```
   **Evidência:** Um limite de 50% de drawdown em conta antes de ativar preservação de capital é incompatível com qualquer padrão quantitativo institucional sério.

### 4.3 Veredito para o QUANT HERMES
* **Aproveitável (Conceitual):** Módulos especializados de proteção (`daily_guard`, `exposure_guard`, `correlation_guard`).
* **Rejeitado e Corrigido:** O motor de fusão que ignora confiança, a brecha de segurança de `account_state is None`, e limites de risco negligentes.

---

## 5. Repositório 4: MT5 Portfolio Framework

* **URL Oficial:** `https://github.com/matitorri/mt5-portfolio-framework`
* **Commit Auditado:** `13c5588db1b59c36d2d347d6bd204425c180257a`
* **Branch:** `main`
* **Data do Commit:** Segunda-feira, 27 de Julho de 2026 (por Trading-hood / Matias Torrilla)
* **Licença:** MIT License (Permissiva)

### 5.1 Estrutura e Componentes MQL5
* **Arquivos Chave:**
  * `Portfolio.mq5`: Ponto de orquestração no terminal.
  * `Backend/Allocation/CapitalAllocator.mqh`: Alocação de risco percentual entre estratégias.
  * `Backend/Risk/PortfolioRiskManager.mqh`: Gestão de drawdown e exposição agregada.
  * `Backend/Execution/PositionSizer.mqh`: Cálculo preciso de volume em lotes.
  * `Backend/Execution/PositionRegistry.mqh`: Registro em tempo real de posições indexadas por `magic number`.
  * `Backend/Risk/CorrelationMonitor.mqh`: Verificação de sobreposição de pares correlacionados.

### 5.2 Avaliação Técnica e Rigor Matemático
1. **Excelente Dimensionamento de Posição:**
   Em `Backend/Execution/PositionSizer.mqh`:
   * Em tempo de execução, utiliza `OrderCalcProfit` do MT5 para mensurar a perda financeira exata de 1 lote entre a entrada e o Stop Loss, evitando erros de conversão cambial (especialmente em índices e metais).
   * Função estática pura `NormalizeLot`: arredonda estritamente para baixo respeitando o `volStep` (`MathFloor(rawLot / volStep + 1e-9) * volStep`), restringe a `volMin` e `volMax`, e calcula casas decimais dinâmicas via logaritmo da base 10.
2. **Excelente Cobertura de Testes Unitários Nativos MQL5:**
   Em `Tests/TestPositionSizer.mq5`:
   * Testa caso base, risco insuficiente para lote mínimo (retorna 0.0 com segurança), clamp para volume máximo, arredondamento correto de passos (ex: 0.665 vira 0.66) e proteção contra distância SL zero ou tick value zero.
3. **Limitação em Contas Hedging vs. Netting:**
   O `PositionRegistry.mqh` indexa posições por `POSITION_MAGIC` e `POSITION_SYMBOL`. Em contas do tipo **Hedging**, cada estratégia possui seu ticket isolado. Em contas do tipo **Netting**, o MT5 consolida múltiplas ordens no mesmo símbolo em uma única posição agregada, quebrando o rastreamento individual direto por magic number nativo. O QUANT HERMES deverá implementar camada de reconciliação virtual para contas netting.

### 5.3 Veredito para o QUANT HERMES
* **Aproveitável (Alta Reutilização de Padrão):** O padrão matemático de `PositionSizer.mqh`, a separação entre Strategy (emite sinal) e Portfolio (autoriza e aloca capital), os testes de verificação do MQL5.

---

## 6. Repositório 5: TradingAgents

* **URL Oficial:** `https://github.com/TauricResearch/TradingAgents`
* **Commit Auditado:** `9fa1196fffbcfd9de5146d2dd2869df84ab99838`
* **Branch:** `main`
* **Data do Commit:** Quarta-feira, 04 de Novembro de 2026 (por Tauric-Research)
* **Licença:** Apache License 2.0 (Permissiva com concessão de patentes)

### 6.1 Estrutura e Componentes LangGraph
* **Arquitetura:** Grafo acíclico dirigido (DAG) e cíclico orquestrado via `LangGraph`:
  * Analistas: `market_analyst.py`, `news_analyst.py`, `sentiment_analyst.py`, `fundamentals_analyst.py`.
  * Pesquisa Adversarial: `bull_researcher.py` vs. `bear_researcher.py` (confronto dialético com histórico estruturado).
  * Gestão de Risco: `aggressive_debator.py`, `conservative_debator.py`, `neutral_debator.py`.
  * Gerência e Execução: `research_manager.py`, `portfolio_manager.py`, `trader.py`.
  * Persistência: Checkpoints de estado via `langgraph-checkpoint-sqlite`.

### 6.2 Avaliação Técnica e Lições Críticas
1. **Prevenção Rigorosa de Lookahead Bias (Viés de Antecipação):**
   * A suíte possui 90 arquivos de teste, com destaque para `test_news_lookahead.py`, `test_fundamentals_lookahead.py`, `test_social_lookahead.py` e `test_tool_date_enforcement.py`.
   * Garante que ferramentas de coleta e analistas jamais recebam dados com timestamps posteriores ao momento da tomada de decisão. Esta é uma prática vital para o QUANT HERMES.
2. **Incompatibilidade com Scalping de Alta Frequência:**
   * Uma rodada completa de debate adversarial via LLM (Bull vs. Bear com réplica e tréplica) consome entre 15 e 60 segundos por consulta de rede externa aos provedores de API.
   * **Conclusão:** É estritamente inviável submeter operações de scalping (M1/M5) ao debate síncrono de LLMs. O QUANT HERMES implementará **dois modos operacionais**:
     * **Modo Rápido (Sub-segundo):** Modelos quantitativos determinísticos, HMM, XGBoost/LightGBM e regras matemáticas de microestrutura (execução direta pós-Risk Engine).
     * **Modo Aprofundado (Macro / Swing / Regime):** Acionamento assíncrono e periódico dos agentes LLM (Adversarial, Gold & Macro) para definir o regime global e parâmetros operacionais de longo prazo, sem atrasar o tick de execução.

### 6.3 Veredito para o QUANT HERMES
* **Aproveitável (Conceitual e Arquitetural):** Padrão de grafo LangGraph com checkpointing SQLite, dialética Bull/Bear estruturada, rigoroso isolamento temporal contra lookahead bias.
* **Rejeitado:** Dependência de LLM síncrono para validação de sinais de scalping.

---

## 7. Repositório 6: EA31337

* **URL Oficial:** `https://github.com/EA31337/EA31337`
* **Commit Auditado:** `9b9bd38c4e49dd6916f4fe3936e50e97fca7a692`
* **Branch:** `master`
* **Data do Commit:** Sexta-feira, 20 de Setembro de 2024 (por Rafal W.)
* **Licença:** **GNU General Public License v3 (GPL-3.0)** — **ALERTA CRÍTICO**

### 7.1 Licença e Restrições Legais
* **Restrição Inegociável:** Sob a licença GPL-3.0, qualquer código derivado ou compilado em conjunto deve ser obrigatoriamente licenciado em GPL-3.0 aberto.
* **Decisão:** **REJEIÇÃO DE QUALQUER CÓDIGO FONTE DIRETO.** Apenas princípios conceituais de modularização de sinais e interfaces MQL5 serão absorvidos de forma limpa (*clean-room*).

### 7.2 Estrutura e Fragmentação de Submódulos
* **Arquitetura Baseada em Git Submodules:**
  * O repositório central contém apenas cascas e cabeçalhos. O código real reside em múltiplos submódulos (`EA31337-strategies.git`, `EA31337-indicators.git`, `EA31337-classes.git`). Um clone superficial deixa os diretórios de estratégias vazios.
* **Complexidade Legada:**
  * Utiliza uma camada densa de macros de pré-processador (`#define`) e wrappers para manter compatibilidade simultânea entre MT4 (MQL4) e MT5 (MQL5). Isso introduz overhead desnecessário, uma vez que o QUANT HERMES é focado nativamente na arquitetura moderna de 64 bits do MT5.

### 7.3 Veredito para o QUANT HERMES
* **Aproveitável (Conceitual):** Estruturação tipada de parâmetros de indicadores e separação de sinais.
* **Rejeitado:** Código-fonte C/MQL legado, dependência de submódulos dispersos e contaminação de licença GPL-3.0.

---

## 8. Resumo Comparativo e Evidências Forenses

| Repositório | Licença | Commit Auditado | Força Principal | Vulnerabilidade / Falha Identificada | Decisão de Reuso |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Samvid Trading Core** | MIT | `0f40e76cad` | Barramento Pub/Sub, Heartbeat Veto | Integração MT5 é apenas stub em console.py L19; bloat excessivo | Conceitual apenas; código descartado |
| **Nexus Trading System MT5** | **AGPL-3.0** | `4c5e949756` | Microsserviços e pisos invioláveis de risco | AGPL-3.0 restritiva; concorrência multi-thread inválida para MT5 COM; testes ocos | **Rejeição total de código**; reaproveitar princípios em clean-room |
| **Multi-Agent Quant** | MIT | `9acd48a075` | Divisão de guardas de risco | **Confiança desacoplada do voto** (L77-88); **account_state None não bloqueia** (L28); drawdown 50% | Correção das falhas no nosso Consensus e Risk Engine |
| **MT5 Portfolio Framework** | MIT | `13c5588db1` | Rigor MQL5, cálculo real via OrderCalcProfit | Rastreamento por Magic vulnerável em contas Netting sem reconciliação virtual | Padrão matemático e MQL5 adotado |
| **TradingAgents** | Apache 2.0 | `9fa1196fff` | Grafo LangGraph, debate adversarial, sem lookahead | Latência de LLM síncrona inviabiliza scalping; requer bifurcação rápido/lento | Padrão LangGraph e isolamento temporal adotados |
| **EA31337** | **GPL-3.0** | `9b9bd38c4e` | Catálogo de estratégias | GPL-3.0 restritiva; submódulos vazios; código legado híbrido MQL4 | **Rejeição de código**; clean-room conceitual |

---
*Relatório concluído com base na inspeção real do código-fonte baixado no workspace local.*

