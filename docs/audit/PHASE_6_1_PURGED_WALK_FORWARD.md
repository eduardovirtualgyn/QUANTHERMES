# QUANT HERMES — PURGED WALK-FORWARD VALIDATION
## FASE 6.1: VALIDAÇÃO TEMPORAL CONTÍNUA, PURGAÇÃO E EMBARGO

**Projeto:** QUANT HERMES  
**Documento:** Validação Temporal Contínua e Prevenção de Vazamento  
**Módulo:** `intelligence/learning/validation.py`  
**Referência Teórica:** Marcos López de Prado, *Advances in Financial Machine Learning* (2018)

---

### 1. O Problema do Vazamento de Informação (Data Leakage) em Séries Financeiras

Em aprendizado de máquina padrão (como K-Fold Cross Validation), amostras são particionadas aleatoriamente. Em finanças, isso acarreta **Look-Ahead Bias** severo:
- O conjunto de treino aprende padrões do futuro e prevê o passado.
- Indicadores técnicos (médias móveis, volatilidade, RSI) possuem janelas de lookback que agregam dados históricos. Se uma barra de treino estiver próxima a uma barra de teste, haverá vazamento de features por sobreposição.
- Horizontes de rotulação de trade (ex: predição de retorno nas próximas $H$ barras): os rótulos de $t$ dependem dos preços até $t+H$. Se o teste iniciar antes de $t+H$, o treino terá acessado o mesmo horizonte de preços do teste.

Partições ordinais baseadas em meros índices inteiros (ex: $k$ barras) ignoram:
1. Gaps de fim de semana (onde 1 barra de intervalo pode representar 48 horas reais).
2. Feriados e quebras de liquidez intradiária.
3. Diferenças no horizonte temporal efetivo de posições abertas.

---

### 2. Mecanismo de Purgação por Timestamp Real (`generate_purged_splits_by_timestamp`)

Para sanar definitivamente a fragilidade de indexação puramente ordinal, o QUANT HERMES opera com `datetime` contínuo baseado em `bar.time`.

Dada uma série temporal ordenada com timestamps $T = \{t_1, t_2, \dots, t_N\}$:

#### 2.1 Janelas Temporais de Validação
O validador define:
- `train_window`: Duração temporal mínima para treino (ex: 90 a 180 dias).
- `test_window`: Duração temporal out-of-sample (ex: 30 dias).
- `purge_window`: Duração do horizonte máximo de trade para eliminação de sobreposição de rótulos (ex: 2 horas a 1 dia).
- `embargo_window`: Quarentena temporal após o término do teste (ex: 4 horas a 2 dias).

#### 2.2 Purgação Pré-Split (Purging)
Se o treino termina em $t_{\text{train\_end}}$ e o teste inicia em $t_{\text{test\_start}}$:
Todas as barras cuja janela de rotulação alcance $t_{\text{test\_start}}$ são purgadas do conjunto de treino:

$$\text{Treino Efetivo} = \{ (X_i, y_i) \mid t_i + \text{Purge Window} < t_{\text{test\_start}} \}$$

Isso assegura que nenhuma informação de preços contida na janela de teste foi utilizada na geração dos rótulos de treino.

#### 2.3 Embargo Pós-Split (Embargoing)
Devido à persistência de autocorrelação serial nos retornos e nos resíduos do modelo, a amostragem de dados imediatamente posterior à janela de teste não pode ser reutilizada sem quarentena:

$$t_{\text{próximo\_treino}} \ge t_{\text{test\_end}} + \text{Embargo Window}$$

O algoritmo garante matematicamente que nenhum ponto temporal é compartilhado, violado ou vazado entre os folds consecutivos.

---

### 3. Diagrama de Fluxo Temporal da Validação

```
Fold k:
[------------- TREINO (Duração: T_train) -------------] [PURGE] [--- TESTE OOS (Duração: T_test) ---] [EMBARGO]
                                                                                                         |
Fold k+1 (Walk-Forward expansivo ou deslizante):                                                         v
[---------------------- NOVO TREINO -------------------------------------------------------------] [PURGE] ...
```

---

### 4. Vantagens Computacionais e Robustez na Fase 6.1

1. **Timestamps Reais:** A sincronização utiliza `timedelta` nativo do Python, lidando corretamente com quebras de mercado entre sexta-feira e domingo à noite no Forex/XAUUSD.
2. **Label Encoding Resiliente:** A transição entre regimes pode fazer com que um fold OOS específico apresente apenas um subconjunto de classes (ex: apenas `HOLD` e `BUY`, ausência de `SELL`). O `PurgedWalkForwardValidator` utiliza `LabelEncoder` automático antes do treinamento e remapeia as probabilidades out-of-sample de volta para as classes canônicas, evitando exceções estruturais do XGBoost/LightGBM.
3. **Compatibilidade Total:** A interface `generate_purged_splits(n_samples)` foi mantida para compatibilidade direta com chamadas baseadas em contagem ordinal de barras.

