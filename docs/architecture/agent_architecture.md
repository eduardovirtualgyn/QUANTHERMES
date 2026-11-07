# Arquitetura dos Agentes Especializados
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/architecture/agent_architecture.md`  

---

## 1. Topologia dos 8 Agentes

O sistema opera com 8 agentes especializados, divididos entre execução analítica rápida (Fast Quant Path) e pesquisa aprofundada (Deep Research Path):

```
+─────────────────────────────────────────────────────────────────────────────+
|                         REDE DE AGENTES QUANT HERMES                        |
+─────────────────────────────────────────────────────────────────────────────+
|  FAST QUANT PATH (Sub-segundo / Determinístico / ML Leve)                   |
|  ├─► AG01: Trend Intelligence         (EMAs, ADX, MACD, Alinhamento Multi-TF)|
|  ├─► AG02: Market Structure           (BOS, CHoCH, Sweeps de Liquidez)       |
|  ├─► AG03: Momentum & Breakout        (ATR, Bollinger Bands, Aceleração)     |
|  ├─► AG04: Mean Reversion             (Z-Score, RSI, Sobre-extensão)         |
|  └─► AG06: Quantitative Intelligence  (HMM Regimes, XGBoost, Calibração)     |
|                                                                             |
|  DEEP RESEARCH PATH (Assíncrono / Periódico / Macro e Dialético)            |
|  ├─► AG05: Gold & Macro Intelligence  (XAUUSD, Dólar DXY, Calendário Macro)  |
|  └─► AG07: Adversarial Research       (Debate Dialético Bull/Bear via LLM)   |
|                                                                             |
|  ORQUESTRAÇÃO E CONSENSO                                                    |
|  └─► AG08: Portfolio Intelligence     (Consenso Ponderado, Risco e Alocação) |
+─────────────────────────────────────────────────────────────────────────────+
```

---

## 2. Especificação Detalhada de Cada Agente

### AG01 — Trend Intelligence
* **Missão:** Detectar a direção predominante, persistência e aceleração de tendências em múltiplos timeframes.
* **Entradas:** Candles e ticks M5, M15, H1 e H4.
* **Ferramentas Matemáticas:**
  * Médias Móveis Exponenciais (EMAs 9, 21, 50, 200).
  * Índice Direcional Médio (ADX com limiar de corte para regime direcional).
  * MACD (convergência e divergência de momentum).
  * Regressão Linear deslizante para cálculo de inclinação (*slope*).
* **Critérios de Invalidação:** Quebra de médias-chave no H1 com fechamento confirmado ou ADX caindo abaixo de 20 (perda de força direcional).

### AG02 — Market Structure Intelligence
* **Missão:** Mapeamento determinístico da microestrutura de mercado e conceitos institucionais (SMC) sem ambiguidades visuais.
* **Entradas:** Séries de máximas e mínimas locais (Swings High / Low).
* **Ferramentas Matemáticas:**
  * Break of Structure (BOS): Rompimento confirmado por fechamento além do swing anterior.
  * Change of Character (CHoCH): Primeira quebra de estrutura contra a tendência prévia.
  * Liquidity Sweeps: Violação da máxima/mínima seguida de rejeição imediata (fechamento de volta para o range).
  * Fair Value Gaps (FVG) e Order Blocks matematicamente quantificados.
* **Regra Anti-Subjetividade:** Não utiliza noções subjetivas; cada ponto estrutural exige regras numéricas booleanas verificáveis.

### AG03 — Momentum and Breakout
* **Missão:** Identificar compressões de volatilidade seguidas de expansão violenta e rompimento sustentável.
* **Entradas:** ATR (Average True Range), Bandas de Bollinger, Keltner Channels, Volume de Ticks.
* **Ferramentas Matemáticas:**
  * Bollinger Squeeze: Largura de banda no menor percentil histórico (percentil 10).
  * Breakout Momentum Score: Relação entre a variação de preço atual e o ATR(14).
  * Filtro de Falso Rompimento: Exigência de fechamento fora das bandas com volume superior à média móvel de volume.

### AG04 — Mean Reversion
* **Missão:** Identificar exaustão de movimentos laterais e condições estatísticas extremas para retorno à média.
* **Entradas:** Z-Scores de preço em relação a médias móveis, RSI, distanciamento de VWAP.
* **Ferramentas Matemáticas:**
  * Z-Score do Preço: $Z = \frac{P - \mu_{n}}{\sigma_{n}}$, com gatilhos em $|Z| \ge 2.2$.
  * RSI com bandas dinâmicas baseadas em volatilidade.
* **Regra de Segurança Inviolável:** Nunca opera contra tendência forte. Se o AG01 acusar tendência forte (ADX > 30), o AG04 é automaticamente silenciado ou obrigado a emitir HOLD.

### AG05 — Gold and Macro Intelligence
* **Missão:** Especialização analítica em XAUUSD, correlações macroeconômicas (Dólar DXY, rendimento dos Treasuries de 10 anos) e monitoramento de notícias de alto impacto.
* **Eventos Monitorados:** FOMC, Decisões de Juros do Fed/BCE, CPI (Inflação), PCE, Non-Farm Payroll (NFP).
* **Comportamento em Notícias:**
  * Modo Blackout: Emissão compulsória de recomendação de HOLD e suspensão de novas entradas nos 15 minutos anteriores e 15 minutos posteriores a eventos de alto impacto.
  * Sem Alucinação: Se a fonte de notícias/macro estiver offline ou inacessível, o agente opera exclusivamente com indicadores de volatilidade do ouro ou emite HOLD.

### AG06 — Quantitative Intelligence
* **Missão:** Identificação probabilística de regimes e estimativa de expectativa matemática.
* **Modelos:**
  * Hidden Markov Models (HMM de 4 estados: Tendência de Alta, Tendência de Baixa, Consolidação Baixa Volatilidade, Expansão Alta Volatilidade).
  * Classificadores XGBoost e LightGBM treinados com validação cruzada purgada (*Purged Walk-Forward*).
  * Calibração de Probabilidades via Regressão Isotônica e Platt Scaling.
* **Incerteza:** Se a entropia de Shannon da distribuição de probabilidade dos regimes for superior a 0.8, o agente sinaliza Regime Incerto e recomenda redução de exposição.

### AG07 — Adversarial Research
* **Missão:** Questionar ativamente as hipóteses dos demais agentes, caçando armadilhas de liquidez, viés de confirmação e evidências de sobreajuste (*overfitting*).
* **Mecanismo Dialético:**
  * Pesquisador Bull vs. Pesquisador Bear com troca de argumentos estruturados.
  * Debator de Risco Conservador.
* **Flexibilidade e Desacoplamento:**
  * Suporta múltiplos provedores de LLM opcionais (OpenAI, Anthropic, Google Gemini, DeepSeek).
  * O sistema funciona perfeitamente mesmo sem qualquer LLM conectado (fallback para regras quantitativas).
  * **Não é chamado no loop síncrono de scalping** para não introduzir latência de rede.

### AG08 — Portfolio Intelligence
* **Missão:** Agregar todos os sinais, calcular o consenso ponderado, validar o regime ativo, checar correlações entre os ativos (EURUSD, GBPUSD, USDJPY, XAUUSD) e propor a alocação ótima de capital ao Risk Engine.
* **Limitação Rígida:** Não tem acesso a rotinas de envio de ordens. Emite apenas `TradeProposal` para avaliação do Risk Engine.

---

## 3. Mecanismo de Consenso Ponderado

O consenso não utiliza votação majoritária ingênua (50% + 1). Ele aplica a seguinte formulação matemática:

$$\text{Composite Score} = \sum_{i=1}^{M} \left( w_i(R) \times D_i \times C_i \times Q_i \right)$$

Onde:
* $w_i(R)$: Peso do agente $i$ no regime de mercado atual $R$ (ex: em regime de tendência, o AG01 tem peso elevado e o AG04 tem peso nulo ou reduzido).
* $D_i \in \{-1.0, 0.0, +1.0\}$: Direção do voto (SELL, HOLD, BUY).
* $C_i \in [0.0, 1.0]$: Confiança calibrada do agente.
* $Q_i \in [0.0, 1.0]$: Histórico recente de qualidade e estabilidade fora da amostra do agente.

### Critérios de Decisão:
* Se $\text{Composite Score} \ge +0.65$ e Invalidações vazias $\longrightarrow$ **BUY**
* Se $\text{Composite Score} \le -0.65$ e Invalidações vazias $\longrightarrow$ **SELL**
* Em qualquer outro cenário, divergência severa ou incerteza $\longrightarrow$ **HOLD**

