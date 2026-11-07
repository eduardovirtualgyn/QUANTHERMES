# Registros de Decisões Arquiteturais (ADRs)
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/decisions/architecture_decisions.md`  

---

## ADR-001: Implementação Clean-Room e Rejeição de Códigos AGPL/GPL
* **Status:** Aprovado
* **Contexto:** A auditoria forense identificou que os repositórios *Nexus Trading System MT5* e *EA31337* utilizam licenças fortemente copyleft (AGPL-3.0 e GPL-3.0, respectivamente). A incorporação direta de código desses repositórios contaminaria legalmente todo o projeto QUANT HERMES, forçando a abertura do código de toda a infraestrutura e modelos proprietários.
* **Decisão:** Rejeitar completamente qualquer cópia de código-fonte de projetos sob licenças copyleft estritas. Todo o código do QUANT HERMES será desenvolvido em engenharia reversa conceitual limpa (*clean-room*), mantendo total originalidade autoral e conformidade de propriedade intelectual.

---

## ADR-002: Arquitetura de Duplo Caminho (Fast Quant vs. Deep Research)
* **Status:** Aprovado
* **Contexto:** Agentes baseados em LLMs (como os analistas do *TradingAgents* e *Multi-Agent Quant*) introduzem latência de 15 a 60 segundos por ciclo de consulta, o que é fatal para operações de Scalping e Day Trade em timeframes M1/M5.
* **Decisão:** Separar a inteligência do sistema em dois caminhos desacoplados:
  1. **Fast Quant Path:** Execução sub-segundo baseada em lógica matemática determinística, árvores de decisão (XGBoost/LightGBM) e regras de microestrutura puras.
  2. **Deep Research Path:** Execução assíncrona e periódica de agentes LLM (Adversarial, Gold/Macro) para revisão de contexto macroeconômico e regimes de mercado de médio/longo prazo, sem interferir no tick crítico de execução.

---

## ADR-003: Executor Single-Thread Dedicado para MT5 COM no Windows
* **Status:** Aprovado
* **Contexto:** A auditoria do *Nexus* revelou o uso de `ThreadPoolExecutor(max_workers=4)` para despachar chamadas MT5 no Windows, o que causa corrupção de memória e falhas de IPC (Single-Threaded Apartment do COM).
* **Decisão:** Todas as interações com o terminal MetaTrader 5 no Windows 11 serão canalizadas por uma fila assíncrona serializada e executadas por um único worker de thread dedicada (`max_workers=1`), garantindo estabilidade absoluta e ausência de concorrência na DLL.

---

## ADR-004: Pisos Invioláveis de Risco no Motor de Risco
* **Status:** Aprovado
* **Contexto:** Em sistemas autônomos de trading, modelos de aprendizado ou operadores podem, inadvertidamente, relaxar limites de segurança através de arquivos YAML ou parâmetros otimizados, expondo o capital à ruína.
* **Decisão:** O Risk Engine implementará pisos invioláveis codificados no próprio código Python (`_HARDCODED_MIN`). Arquivos de configuração externos podem apenas endurecer as regras de segurança, jamais relaxá-las abaixo do piso seguro.

---

## ADR-005: Fail-Safe Compulsório por Ausência ou Falha de Dados
* **Status:** Aprovado
* **Contexto:** No repositório auditado *Multi-Agent Quant*, a função `apply_account_limits` retornava ordens desprotegidas caso o estado da conta fosse nulo (`account_state is None`).
* **Decisão:** O QUANT HERMES adota a postura de Falha Segura (*Fail-Safe*): qualquer omissão de dados de conta, perda de comunicação com o terminal, spread anômalo ou divergência de posições resultará no cancelamento imediato da proposta de ordem e suspensão de novas entradas.

---

## ADR-006: Motor de Consenso Ponderado com Calibração Probabilística
* **Status:** Aprovado
* **Contexto:** A votação por maioria simples (50%+1) ignora o grau de convicção e o histórico de acerto de cada agente. Além disso, a auditoria do *Multi-Agent Quant* demonstrou que calcular a confiança de forma separada da direção do voto gera distorções perigosas.
* **Decisão:** O consenso utilizará uma formulação matemática composta onde o voto de cada agente é modulado simultaneamente por seu peso no regime ativo, sua confiança calibrada e seu desempenho histórico fora da amostra, exigindo um limiar composto mínimo para acionar BUY ou SELL.

---

## ADR-007: Escolha do Stack Tecnológico Central (Python 3.11, Pydantic V2)
* **Status:** Aprovado
* **Contexto:** É necessária uma infraestrutura robusta, de alta performance, tipada e com suporte consolidado a bibliotecas de Machine Learning e conexão nativa ao MetaTrader 5.
* **Decisão:** Padronizar a base de código em **Python 3.11**, com **Pydantic V2** para todos os esquemas e mensagens, **FastAPI** para monitoramento/API, **NumPy / Polars** para engenharia vetorial de features, e **MetaTrader5** para a execução no Windows.

---

## ADR-008: Interface Abstrata TradingPlatformAdapter para Migração Futura Linux
* **Status:** Aprovado
* **Contexto:** A biblioteca oficial MetaTrader5 é nativa para Windows. O sistema será desenvolvido inicialmente no Windows 11, mas o objetivo de médio prazo é rodar a inteligência quantitativa em VPS Linux.
* **Decisão:** Isolar todas as chamadas à corretora atrás da interface abstrata `TradingPlatformAdapter`. Nenhum módulo de estratégia, risco ou IA terá dependência direta do pacote `MetaTrader5` ou do sistema operacional Windows, viabilizando arquitetura em contêineres e comunicação distribuída.

