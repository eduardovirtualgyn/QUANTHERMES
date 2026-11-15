# QUANT HERMES — METODOLOGIA DE MONTE CARLO E BLOCK BOOTSTRAP
## FASE 6.1: PRESERVAÇÃO DE DEPENDÊNCIA TEMPORAL E RISCO DE CAUDA

**Projeto:** QUANT HERMES  
**Documento:** Metodologia Matemática e Estatística de Monte Carlo  
**Módulo:** `intelligence/learning/monte_carlo.py`  
**Referência:** Politis & Romano (1994), Lahiri (2003), Politis & White (2004)

---

### 1. Limitações Críticas do Bootstrap IID Tradicional

O bootstrap tradicional assume que a série de retornos $\{r_t\}_{t=1}^N$ é Independent and Identically Distributed (IID). Sob essa premissa, os retornos são reamostrados individualmente de maneira uniforme com reposição:

$$P(r_t^* = r_k) = \frac{1}{N}, \quad \forall k \in \{1, \dots, N\}$$

Em finanças quantitativas e séries temporais de ativos como XAUUSD e pares de moedas, a premissa IID é profundamente incorreta devido aos seguintes fenômenos empíricos:
1. **Agrupamento de Volatilidade (Volatility Clustering):** Dias de alta volatilidade tendem a ser sucedidos por dias de alta volatilidade ($\text{Cov}(r_t^2, r_{t-k}^2) > 0$).
2. **Sequências de Perdas (Loss Streaks):** Mudanças abruptas de regime de mercado geram períodos prolongados de drawdown sequencial. O IID dispersa essas perdas ao longo do tempo, diluindo artificialmente a profundidade dos drawdowns.
3. **Assimetria e Caudas Pesadas (Fat Tails):** A reamostragem IID subestima o Conditional Value-at-Risk (CVaR) nos percentis extremos (95% e 99%).

---

### 2. Métodos de Block Bootstrap Implementados

Para preservar a estrutura de dependência temporal e os agrupamentos de volatilidade, o QUANT HERMES implementou três algoritmos fundamentais:

#### 2.1 Moving Block Bootstrap (Künsch, 1989)
A série temporal de retornos $\{r_1, \dots, r_N\}$ é particionada em $N - b + 1$ blocos sobrepostos de comprimento fixo $b$:

$$B_i = (r_i, r_{i+1}, \dots, r_{i+b-1}), \quad i \in \{1, \dots, N - b + 1\}$$

Em cada iteração de Monte Carlo, blocos $B_i$ são sorteados uniformemente e concatenados até que a série sintética atinja o comprimento $N$.

#### 2.2 Circular Block Bootstrap (Politis & Romano, 1992)
Para evitar que os dados do final da série tenham menor probabilidade de amostragem (efeito de borda), a série é estendida periodicamente de forma circular:

$$r_{N+k} = r_k$$

Isso gera exatamente $N$ blocos de tamanho $b$, garantindo que cada observação histórica possua rigorosamente a mesma probabilidade de ser amostrada:

$$B_i = (r_i, r_{i+1}, \dots, r_{i+b-1}), \quad i \in \{1, \dots, N\}$$

#### 2.3 Stationary Bootstrap (Politis & Romano, 1994)
No Stationary Bootstrap, o tamanho do bloco não é constante. Em cada passo, a probabilidade de iniciar um novo bloco é governada por uma variável aleatória com distribuição geométrica de parâmetro $p = \frac{1}{b}$.

- Se $U \sim \text{Uniform}(0, 1) < p$, inicia-se um novo bloco aleatório em qualquer posição da série.
- Se $U \ge p$, continua-se para o próximo elemento $r_{t+1}$ da série de forma contínua e circular.

Esse método assegura matematicamente que a série sintética gerada preserva a **estacionariedade estrita** da série original.

---

### 3. Estimador Ótimo de Tamanho de Bloco (Lahiri / Politis & White)

A escolha arbitrária do tamanho do bloco $b$ introduz um trade-off clássico:
- Bloco muito pequeno ($b \to 1$): recai no viés IID, quebrando a dependência serial.
- Bloco muito grande ($b \to N$): gera variância excessiva e repetição quase determinística do histórico.

O algoritmo implementado em `estimate_optimal_block_size()` calcula a função de autocorrelação empírica (ACF) até o lag $K = \min(20, \lfloor N/4 \rfloor)$:

$$\hat{\rho}_k = \frac{\sum_{t=1}^{N-k} (r_t - \bar{r})(r_{t+k} - \bar{r})}{\sum_{t=1}^N (r_t - \bar{r})^2}$$

A partir do decaimento das autocorrelações significativas ($|\hat{\rho}_k| > \frac{1.96}{\sqrt{N}}$), estima-se a dependência persistente $G$:

$$G = \sum_{k=1}^K k \cdot |\hat{\rho}_k|$$

O tamanho ótimo do bloco é calculado analiticamente por:

$$b^* = \max\left(2, \min\left(\left\lceil \left( \frac{2 G^2}{1 + 2 \sum |\hat{\rho}_k|} \right)^{1/3} \cdot N^{1/3} \right\rceil, \left\lfloor \frac{N}{2} \right\rfloor \right)\right)$$

Com fallback automático para o teto assintótico de Künsch $b \approx \lceil N^{1/3} \rceil$ na ausência de autocorrelação relevante.

---

### 4. Métricas de Estresse e Cauda Calculadas

Cada simulação de Monte Carlo com $M$ caminhos (padrão $M = 2.000$) extrai:
1. **Curva de Drawdown Histórico e Sintético:**
   $$DD_t = \frac{\max_{0 \le s \le t}(W_s) - W_t}{\max_{0 \le s \le t}(W_s)}$$
2. **Value-at-Risk de Drawdown (VaR 95% e 99%):** Percentis 95 e 99 dos piores drawdowns observados em cada caminho.
3. **Conditional Value-at-Risk (CVaR / Expected Shortfall 95% e 99%):**
   $$\text{CVaR}_\alpha = E[DD \mid DD \ge \text{VaR}_\alpha]$$
4. **Agrupamento de Sequência de Perdas:**
   - `max_consecutive_losses_p95`: Quantidade de perdas ininterruptas observada no percentil 95.
   - `max_consecutive_losses_worst`: A pior sequência ininterrupta de perdas simulada em todos os $M$ cenários.
5. **Probabilidade de Ruína:** Proporção de simulações onde $DD_t \ge DD_{\text{limite}}$ (definido constitucionalmente em 8%).

---

### 5. Comparador Empírico IID vs. Bloco (`compare_iid_vs_block`)

O QUANT HERMES inclui um mecanismo auditável de comparação entre o IID e o Block Bootstrap.
Quando submetido a uma estratégia real com dependência de regime, o comparador emite:
- $\Delta \text{Max DD}_{p95} = \text{Max DD}_{p95}^{\text{Bloco}} - \text{Max DD}_{p95}^{\text{IID}}$
- $\Delta \text{Streak}_{p95} = \text{Streak}_{p95}^{\text{Bloco}} - \text{Streak}_{p95}^{\text{IID}}$

Se $\Delta \text{Max DD}_{p95} > 0.01$ ou $\Delta \text{Streak}_{p95} \ge 1$, o sistema emite formalmente o veredito:
$$\text{Verdict} = \text{"IID\_UNDERESTIMATES\_TAIL\_RISK"}$$

Impedindo que o quantitativo tome decisões de alocação baseadas na fragilidade do IID.

