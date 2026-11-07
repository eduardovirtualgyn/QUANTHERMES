# QUANT HERMES
## Autonomous Multi-Agent Quantitative Trading System for MetaTrader 5

[![Python Version](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2011%20%7C%20Linux%20VPS-lightgrey.svg)]()
[![Execution](https://img.shields.io/badge/execution-MetaTrader%205-green.svg)]()
[![Status](https://img.shields.io/badge/status-FASE%200%20CONCLU%C3%8DDA-success.svg)]()

---

## 1. Visão Geral

O **QUANT HERMES** é uma infraestrutura quantitativa autônoma multiagente para trading no MetaTrader 5, focada nos mercados de **Forex** (EURUSD, GBPUSD, USDJPY) e **Metais** (XAUUSD). Opera com estilos híbridos (*Scalping, Day Trade e Swing Trade*) ancorados em controles de risco matemáticos invioláveis e independentes.

Não se trata de um Expert Advisor convencional. É um ecossistema modular orientado a eventos, com inteligência analítica distribuída, modelos estatísticos de regime (HMM), classificadores supervisionados (XGBoost/LightGBM), debate dialético adversarial e alocação centralizada de portfólio.

### Princípio Fundamental de Arquitetura:
> **Agentes pesquisam e recomendam; estratégias geram sinais; o Portfolio Manager aloca capital; mas SOMENTE o Risk Engine autoriza e despacha a execução.**
> Nenhum modelo de IA ou algoritmo pode alterar seus próprios limites financeiros ou contornar as travas de proteção de capital.

---

## 2. As Dez Camadas do Sistema

1. **Market Data Engine:** Ingestão de ticks, candles, book e calendário macroeconômico em tempo real com barreira estrita contra *lookahead bias*.
2. **Feature Engineering Engine:** Cálculo vetorial determinístico de médias, volatilidade, osciladores e estruturas de mercado SMC.
3. **AI Multi-Agent Engine:** 8 agentes especializados operando em duplo caminho (*Fast Quant Path* para scalping e *Deep Research Path* para análise macroeconômica).
4. **Quantitative Intelligence Engine:** Modelagem de regimes de mercado via Hidden Markov Models (HMM), classificadores ML e calibração de probabilidade.
5. **Strategy Engine:** 7 famílias de estratégias quantitativas desacopladas que emitem apenas intenções puras de negociação.
6. **Portfolio Manager:** Fusão de consenso ponderado, monitoramento de correlações de pares e alocação prudencial de capital.
7. **Risk Engine (Autoridade Soberana):** Pisos invioláveis codificados (`_HARDCODED_MIN`), controle rigoroso de margem, spread, slippage, perda diária, perda semanal e Kill Switch.
8. **Execution Engine:** Adaptador abstrato com worker single-thread dedicado para chamadas MT5 COM no Windows, garantindo estabilidade e idempotência.
9. **Learning Engine:** Trilha de auditoria completa de cada trade, testes de Walk-Forward purgado e simulações de Monte Carlo para melhoria contínua controlada.
10. **Monitoring and Dashboard:** Painel operacional FastAPI + WebSockets em tempo real com telemetria e controles de emergência.

---

## 3. Os Oito Agentes Especializados

* **AG01 — TREND INTELLIGENCE:** Análise multi-timeframe de tendências (EMAs, ADX, MACD, Regressão Linear).
* **AG02 — MARKET STRUCTURE INTELLIGENCE:** Identificação determinística de BOS, CHoCH, Sweeps de Liquidez e Order Blocks.
* **AG03 — MOMENTUM AND BREAKOUT:** Compressão de volatilidade (Bollinger Squeeze), aceleração e expansão de range.
* **AG04 — MEAN REVERSION:** Desvios estatísticos extremos (Z-Scores, RSI dinâmico) com filtro contra tendências fortes.
* **AG05 — GOLD AND MACRO INTELLIGENCE:** Especialização em XAUUSD, correlação com Dólar DXY e blackout em notícias de alto impacto (FOMC, NFP, CPI).
* **AG06 — QUANTITATIVE INTELLIGENCE:** Detecção probabilística de regimes via HMM, XGBoost/LightGBM e calibração de confiança.
* **AG07 — ADVERSARIAL RESEARCH:** Questionamento dialético Bull vs. Bear e busca ativa por armadilhas e overfitting via LLMs opcionais (assíncrono).
* **AG08 — PORTFOLIO INTELLIGENCE:** Cálculo do consenso ponderado multidimensional e proposta de alocação de risco.

---

## 4. O Motor de Consenso Ponderado

A decisão direcional composta é calculada por:

$$\text{Composite Score} = \sum_{i=1}^{M} \left( w_i(R) \times D_i \times C_i \times Q_i \right)$$

Onde o voto $D_i \in \{-1, 0, +1\}$ é ponderado simultaneamente pelo peso no regime $w_i(R)$, confiança calibrada $C_i$ e qualidade histórica $Q_i$. Apenas pontuações com alta convicção e ausência de invalidações ativam ordens.

---

## 5. Auditoria de Referências — Resumo da Fase 0

Na Fase 0, seis repositórios de ponta foram clonados e auditados em nível forense no disco local:
* **Samvid Trading Core:** Aproveitados os conceitos de barramento Pub/Sub, Heartbeat Veto e testes com SQLite em memória; descartados os módulos periféricos (*bloat*) e o stub vazio de MT5.
* **Nexus Trading System MT5:** Rejeitada a cópia de código devido à licença **AGPL-3.0** restritiva. Identificado e corrigido o risco de colisão COM multi-thread no MT5. Adotado o conceito de pisos invioláveis de risco em código original (*clean-room*).
* **Multi-Agent Quant:** Identificadas e corrigidas duas vulnerabilidades críticas: a confiança era ignorada no cálculo do voto de fusão, e ordens eram liberadas sem proteção caso o estado da conta estivesse nulo.
* **MT5 Portfolio Framework:** Adotado o padrão de cálculo preciso de volume em lotes via `OrderCalcProfit` com arredondamento para baixo no `volStep` (`MathFloor`).
* **TradingAgents:** Adotado o padrão LangGraph adversarial assíncrono e os testes estritos contra *Lookahead Bias*.
* **EA31337:** Rejeitada a cópia direta de código devido à licença **GPL-3.0** e fragmentação de submódulos.

Documentação completa em [`docs/research/`](docs/research/).

---

## 6. Estrutura de Diretórios Planejada

```
quant-hermes/
├── AGENTS.md               # Constituição e regras dos agentes
├── README.md               # Documentação principal
├── pyproject.toml          # Dependências e empacotamento
├── .env.example            # Template de variáveis de ambiente
├── .gitignore              # Proteção de credenciais e caches
├── config/                 # Arquivos de configuração YAML
├── agents/                 # Os 8 agentes especializados
├── intelligence/           # Consenso, regimes HMM, calibração
├── strategies/             # As 7 famílias de estratégias
├── portfolio/              # Gestão centralizada de portfólio
├── risk/                   # Risk Engine soberano e inviolável
├── execution/              # Adaptadores MT5, Paper e Backtest
├── data/                   # Ingestão, features e séries históricas
├── learning/               # Walk-Forward, Monte Carlo e Model Registry
├── backtesting/            # Motor de simulação tick-a-tick
├── api/                    # Endpoints FastAPI e WebSockets
├── dashboard/              # Interface operacional em tempo real
├── monitoring/             # Métricas Prometheus e alertas
├── deployment/             # Scripts Windows e contêineres Docker Linux
├── docs/                   # Documentação arquitetural, de pesquisa e decisões
├── scripts/                # Utilitários operacionais e diagnósticos
└── tests/                  # Pirâmide de testes completa (20 modos de falha)
```

---

## 7. Próximos Passos — Roadmap

* [x] **FASE 0 — Auditoria e Planejamento:** Concluída com sucesso (Auditoria dos 6 repositórios, ADRs, AGENTS.md, Matriz de Risco e Testes).
* [ ] **FASE 1 — Fundação:** Inicialização formal da estrutura de pacotes, schemas Pydantic V2, logging estruturado e barramento de eventos.
* [ ] **FASE 2 — MT5 e Data Engine:** Implementação do `WindowsMT5Adapter`, `PaperTradingAdapter` e pipeline de dados tick-a-tick.
* [ ] **FASE 3 — Risk e Portfolio:** Implementação dos pisos invioláveis de risco, dimensionamento dinâmico e circuit breakers.

