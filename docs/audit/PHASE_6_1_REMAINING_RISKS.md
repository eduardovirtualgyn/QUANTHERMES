# QUANT HERMES — ANÁLISE DE RISCOS RESIDUAIS
## FASE 6.1: RISCOS QUANTITATIVOS, DEPENDÊNCIAS DE DADOS E PRÓXIMAS ETAPAS

**Projeto:** QUANT HERMES  
**Documento:** Matriz de Riscos Residuais Pós-Fase 6.1  
**Classificação:** GOVERNANÇA E CONTROLE DE RISCO

---

### 1. Riscos Mitigados com Sucesso na Fase 6.1

| Risco Anterior | Gravidade Prévia | Status Atual | Mitigação Implementada |
|---|---|---|---|
| **Otimismo Estatístico por Reamostragem IID** | Crítica (P0) | **ELIMINADO** | Implementação de Circular Block, Moving Block e Stationary Bootstrap com estimador de Lahiri e comparador empírico `compare_iid_vs_block`. |
| **Vazamento Temporal em Validação** | Alta (P1) | **ELIMINADO** | Purgação temporal estrita e embargo contínuo baseados em `timedelta` e `bar.time` reais. |
| **Distorção Econômica (+20/-10)** | Crítica (P0) | **ELIMINADO** | Dinâmica completa de ATR para SL/TP, spread real, comissões institucionais ($7/lote), slippage e teste de estresse de custos ($2\times$). |
| **Corrupção Silenciosa de Séries Históricas** | Alta (P1) | **MITIGADO** | Função de auditoria `audit_market_data_integrity()` que valida OHLC, cronologia, duplicidade e volume antes da ingestão. |

---

### 2. Riscos Residuais Identificados

Apesar dos avanços substanciais da Fase 6.1, subsistem riscos que requerem atenção operacional contínua:

#### 2.1 Dependência da Densidade Histórica de Amostras
- **Descrição:** O estimador de tamanho de bloco de Lahiri e o cálculo de CVaR no percentil 99 exigem um número mínimo representativo de trades (mínimo de 30 a 50 trades históricos). Em estratégias de baixa frequência (swing trade em H4/D1), o tamanho da amostra pode ser insuficiente para convergência assintótica.
- **Contramedida de Projeto:** Fallback automático para $b \approx \lceil n^{1/3} \rceil$ e rejeição constitucional do modelo se $N_{\text{trades}} < 30$.

#### 2.2 Dependência de Conexão com MT5 para Dados Reais em Tempo de Execução
- **Descrição:** O validador quantitativo foi testado e validado contra geradores sintéticos rigorosos e dados em memória. A ingestão massiva contínua de anos de dados de tick do MetaTrader 5 depende da estabilidade do terminal local e de cotas de histórico da corretora.
- **Contramedida de Projeto:** Utilização da camada de armazenamento em Parquet (`data/parquet_store.py`) para congelamento e cache local imutável dos datasets auditados.

#### 2.3 Fragilidade de Assimetria de Slippage em Mercados Ilíquidos
- **Descrição:** A modelagem atual assume slippage simétrico médio (0.5 pips). Em choques de liquidez extremos (como anúncios de CPI ou NFP), o slippage pode ser puramente desfavorável e atingir múltiplos do spread normal.
- **Contramedida de Projeto:** O AG05 (Gold & Macro Intelligence) aplica blackout obrigatório durante janelas de notícias de alto impacto, e o Risk Engine veta novas ordens quando a volatilidade instantânea extrapola o teto permitido.

---

### 3. Pré-requisitos para Fases Subsequentes

1. **Fase 8 / 8.1 (Monitoramento e Telemetria):**
   - Os endpoints de monitoramento FastAPI e a interface gráfica do dashboard devem expor os novos relatórios estatísticos da Fase 6.1 (`DataIntegrityReport`, `BootstrapComparisonReport` e `ValidationReport` com Sortino e sensibilidade a custos).
2. **Fase 9 (Infraestrutura de VPS e Produção):**
   - Garantir que bibliotecas nativas de Machine Learning (`lightgbm`, `xgboost`, `scipy`) estejam instaladas com binários otimizados no contêiner Linux ou VPS Windows Server.
3. **Fase 10 (Operação em Conta Demo Institucional):**
   - Execução estrita do checklist de pré-operação e validação empírica da correspondência entre o slippage real observado no MT5 e o modelo de fricção da Fase 6.1.

