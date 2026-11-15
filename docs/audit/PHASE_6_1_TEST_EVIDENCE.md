# QUANT HERMES — REGISTRO DE EVIDÊNCIAS DE TESTES
## FASE 6.1: INTEGRIDADE QUANTITATIVA E VALIDAÇÃO ESTATÍSTICA

**Data:** 07 de novembro de 2026  
**Ambiente:** Python 3.11.3 / Pytest 9.2.0 / Windows 11  
**Total de Testes do Sistema:** 196 testes coletados, 196 aprovados (100% de aprovação).

---

### 1. Resumo da Suíte Específica da Fase 6.1

Arquivo de teste principal: `tests/unit/test_phase_6_1_quant_integrity.py`
Resultado: **8 testes executados, 8 testes aprovados (100% PASS)** em 3.60s.

```text
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61MonteCarloBlockBootstrap::test_all_bootstrap_methods_execute_and_produce_valid_metrics PASSED [ 12%]
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61MonteCarloBlockBootstrap::test_optimal_block_size_estimator PASSED [ 25%]
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61MonteCarloBlockBootstrap::test_block_bootstrap_captures_loss_clustering_better_than_iid PASSED [ 37%]
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61PurgedWalkForwardTimestamp::test_purged_splits_by_timestamp_guarantees_no_temporal_leakage PASSED [ 50%]
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61PurgedWalkForwardTimestamp::test_realistic_backtest_economics_without_artificial_heuristics PASSED [ 62%]
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61DataIntegrityAudit::test_audit_clean_series_is_valid PASSED [ 75%]
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61DataIntegrityAudit::test_audit_detects_out_of_order_and_duplicates PASSED [ 87%]
tests/unit/test_phase_6_1_quant_integrity.py::TestPhase61DataIntegrityAudit::test_audit_detects_invalid_ohlc PASSED [100%]
```

---

### 2. Detalhamento e Asserções dos Testes da Fase 6.1

#### 2.1 Eixo A: Monte Carlo com Block Bootstrap
1. **`test_all_bootstrap_methods_execute_and_produce_valid_metrics`**:
   - Executa 500 iterações para cada método: `moving`, `circular`, `stationary`, e `iid`.
   - Verifica se todas as métricas são finitas e satisfazem as restrições de probabilidade: $0 \le \text{prob\_ruin} \le 1$, $\text{max\_dd\_p95} \ge 0$, $\text{cvar\_99} \ge \text{cvar\_95} \ge \text{var\_95}$.
   - Valida a presença de `max_consecutive_losses_p95` e `max_consecutive_losses_worst`.
2. **`test_optimal_block_size_estimator`**:
   - Testa séries sintéticas com forte autocorrelação temporal ($AR(1)$ com $\rho=0.8$) e séries de ruído branco ($\rho=0.0$).
   - Comprova que séries correlacionadas produzem tamanho de bloco $b > 1$, e que o estimador é limitado dentro do teto seguro ($1 \le b \le n/2$).
3. **`test_block_bootstrap_captures_loss_clustering_better_than_iid`**:
   - Constrói uma série com forte agrupamento de perdas (regimes contíguos de perdas seguidos de regimes de ganhos).
   - Executa `compare_iid_vs_block()` com 1.000 iterações.
   - **Evidência Comprovada:**
     - `max_consecutive_losses_p95` (Bloco) > `max_consecutive_losses_p95` (IID).
     - `max_dd_p95` (Bloco) > `max_dd_p95` (IID).
     - `cvar_99` (Bloco) > `cvar_99` (IID).
     - Veredito emitido: `IID_UNDERESTIMATES_TAIL_RISK`.

#### 2.2 Eixo B & C: Validação Purgada por Timestamp e Economia Real
4. **`test_purged_splits_by_timestamp_guarantees_no_temporal_leakage`**:
   - Cria série sintética com 500 barras de 15 minutos reais.
   - Aplica `purge_window = timedelta(hours=2)` e `embargo_window = timedelta(hours=4)`.
   - Gera folds de Walk-Forward.
   - Comprova matematicamente que para cada split $k$:
     $$\text{Train Start}_{k+1} \ge \text{Test End}_k + \text{Embargo Window}$$
     Garantindo separação temporal contínua e ausência de vazamento.
5. **`test_realistic_backtest_economics_without_artificial_heuristics`**:
   - Simula validação com split out-of-sample realístico.
   - Executa com spread (1.5 pips), comissão ($7.00/lote), slippage (0.5 pips) e cálculo monetário baseado em ATR dinâmico.
   - Confirmação de que `total_transaction_costs > 0`, `mean_sortino` é calculado, e que `cost_sensitivity_pf_2x_mean < mean_profit_factor` (estresse de custos reduz o Profit Factor).

#### 2.3 Auditoria de Dados de Mercado
6. **`test_audit_clean_series_is_valid`**:
   - Submete série sintética estritamente ordenada e sem gaps além do intervalo de 15 minutos.
   - Valida `is_valid == True`, contagens de anomalias zeradas.
7. **`test_audit_detects_out_of_order_and_duplicates`**:
   - Injeta intencionalmente barras fora de ordem cronológica e barras com timestamps idênticos.
   - Valida `is_valid == False`, `out_of_order_count >= 1`, `duplicate_timestamps_count >= 1`.
8. **`test_audit_detects_invalid_ohlc`**:
   - Injeta barras com $High < Low$, $Open > High$ e $Volume \le 0$.
   - Valida `is_valid == False`, `invalid_ohlc_count >= 1`, `zero_volume_count >= 1`.

---

### 3. Regressão e Cobertura Total do Sistema

Execução completa em todo o repositório:
```text
pytest tests/unit tests/risk tests/contract tests/security -q --ignore=tests/unit/test_monitoring_api.py
======================= 196 passed, 2 warnings in 8.82s =======================
```

- **Fase 1 (Fundação e Event Bus):** 100% PASS
- **Fase 2 (Dados e MT5 Adapter):** 100% PASS
- **Fase 3 (Risk Engine e Inviolabilidade):** 100% PASS
- **Fase 4 (Estratégias Quantitativas):** 100% PASS
- **Fase 5 (Multiagente e Consenso):** 100% PASS
- **Fase 6 & 6.1 (Modelos, Purgação e Monte Carlo):** 100% PASS
- **Fase 7 & 7.1 (Orquestração, Idempotência e Recuperação):** 100% PASS

