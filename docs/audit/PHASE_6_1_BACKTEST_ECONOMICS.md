# QUANT HERMES — ECONOMIA REALISTA DE BACKTEST E VALIDAÇÃO
## FASE 6.1: FRICÇÕES DE MERCADO, DINÂMICA DE VOLATILIDADE E SENSIBILIDADE A CUSTOS

**Projeto:** QUANT HERMES  
**Documento:** Modelagem Econômica de Backtest e Validação Out-of-Sample  
**Módulo:** `intelligence/learning/validation.py`

---

### 1. Eliminação de Heurísticas Artificiais

Anteriormente, rotinas de validação de modelos quantitativos utilizavam aproximações ingênuas, tais como payoffs fixos:
- Ganho hipotético fixo: $+20$ ticks.
- Perda hipotética fixa: $-10$ ticks.
- Ausência de spread, custos de execução ou slippage.

Essa abordagem distorcia severamente os resultados:
- Em períodos de baixa volatilidade, $+20$ ticks é um alvo inatingível, gerando perdas artificiais por timeout.
- Em períodos de alta volatilidade, alvos fixos ignoram a amplitude dos movimentos, subestimando o risco e superestimando a taxa de acerto.
- Estratégias que pareciam lucrativas em backtest tornavam-se perdedoras no ambiente real devido à fricção acumulada de taxas e spread.

---

### 2. Modelagem Econômica Rigorosa Implementada

A Fase 6.1 substituiu todas as heurísticas artificiais por um motor econômico fiel às condições institucionais do MetaTrader 5:

#### 2.1 Alvos Dinâmicos Baseados em Volatilidade (ATR)
Cada operação simulada calcula seus níveis de liquidação com base no ATR (Average True Range de 14 períodos) da barra de sinal:

$$\text{Distância do Stop Loss} = \text{ATR} \times \text{Multiplier}_{\text{SL}} \quad (\text{padrão: } 1.5 \times \text{ATR})$$
$$\text{Distância do Take Profit} = \text{ATR} \times \text{Multiplier}_{\text{TP}} \quad (\text{padrão: } 2.5 \times \text{ATR})$$

Isso assegura que o risco e o retorno projetado sejam sempre proporcionais ao regime de volatilidade vigente do ativo.

#### 2.2 Fricções de Mercado Modeladas

Para cada operação simulada no fold de validação, deduzem-se os seguintes custos:

1. **Spread Efetivo:**
   $$\text{Custo do Spread} = \text{Spread (pontos)} \times \text{Tick Value} \times \text{Volume}$$
2. **Slippage de Execução (Derrapagem):**
   $$\text{Custo de Slippage} = \text{Slippage (pontos)} \times \text{Tick Value} \times \text{Volume}$$
3. **Comissão Institucional de Corretagem:**
   $$\text{Comissão} = \$7,00 \text{ por lote standard (ida e volta)}$$

O PnL Líquido de cada trade $j$ é dado por:

$$\text{Net PnL}_j = \text{Gross PnL}_j - \text{Custo de Spread}_j - \text{Custo de Slippage}_j - \text{Comissão}_j$$

---

### 3. Métricas Financeiras e Índices Calculados

O validador sintetiza os trades out-of-sample de cada fold em:
- **Profit Factor Bruto e Líquido:**
  $$\text{Profit Factor} = \frac{\sum \text{Ganhos}}{\sum |\text{Perdas}|}$$
- **Índice de Sharpe Anualizado:**
  $$\text{Sharpe} = \frac{\bar{r}_{\text{trade}}}{\sigma_{r}} \times \sqrt{252}$$
- **Índice de Sortino (Penalização Apenas de Desvios Negativos):**
  $$\text{Sortino} = \frac{\bar{r}_{\text{trade}}}{\sqrt{\frac{1}{K} \sum_{r_k < 0} r_k^2}} \times \sqrt{252}$$
- **Total de Custos Transacionais Pagos:** Rastreia o total financeiro drenado por spread, comissões e slippage.

---

### 4. Análise de Sensibilidade a Custos ($2\times$ Spread e $2\times$ Slippage)

Todo fold de validação calcula automaticamente o parâmetro `cost_sensitivity_pf_2x`:
- O algoritmo reprocessa a série de trades aplicando **o dobro do spread** e **o dobro da derrapagem (slippage)**.
- Recalcula o Profit Factor resultante: $\text{PF}_{2\times}$.

**Interpretação e Robustez:**
- Se $\text{PF}_{2\times} > 1.10$: A estratégia demonstra robustez institucional a choques de liquidez e alargamento de spread durante eventos noticiosos.
- Se $\text{PF}_{2\times} < 1.00$ (enquanto $\text{PF}_{\text{base}} > 1.30$): A estratégia é frágil e dependente de condições ideais de execução, sendo imediatamente sinalizada para o comitê quantitativo.

