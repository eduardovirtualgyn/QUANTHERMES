"""
QUANT HERMES — TESTES DE INTEGRIDADE QUANTITATIVA, BLOCK BOOTSTRAP E VALIDAÇÃO TEMPORAL (FASE 6.1)
Módulo: tests.unit.test_phase_6_1_quant_integrity

Valida:
1. EIXO A: Block Bootstrap (Circular, Moving, Stationary vs. IID), estimador de Lahiri e detecção de caudas grossas.
2. EIXO A: Comprovação empírica de que IID subestima o risco de drawdown em séries com agrupamento de perdas (loss clustering).
3. EIXO B: Purga temporal contínua por timestamps reais e embargo temporal.
4. EIXO C: Validação out-of-sample com economia realista (spread, comissão, slippage e ATR).
5. Auditoria de integridade de dados (detecção de duplicatas, desordem temporal e OHLC inválido).
"""
from datetime import datetime, timedelta, timezone
from typing import List
import numpy as np
import pytest

from core.models.market import MarketBar, SymbolSpecification, TimeFrame
from intelligence.learning.monte_carlo import (
    BootstrapComparisonReport,
    MonteCarloReport,
    MonteCarloStressTester,
)
from intelligence.learning.validation import (
    DataIntegrityReport,
    PurgedWalkForwardValidator,
    ValidationReport,
    audit_market_data_integrity,
)


def _create_synthetic_bars_with_timestamps(n_bars: int = 220) -> List[MarketBar]:
    """Cria série temporal sintética com timestamps contínuos e realistas de M15."""
    start_time = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    bars: List[MarketBar] = []
    rng = np.random.default_rng(123)
    price = 1.1000

    for i in range(n_bars):
        ret = 0.0003 + rng.normal(0, 0.0006)
        close_p = round(price * (1.0 + ret), 5)
        open_p = round(price, 5)
        high_p = round(max(open_p, close_p) + abs(rng.normal(0, 0.0003)), 5)
        low_p = round(min(open_p, close_p) - abs(rng.normal(0, 0.0003)), 5)

        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                time=start_time + timedelta(minutes=15 * i),
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                tick_volume=250,
                spread=15,
            )
        )
        price = close_p

    return bars


class TestPhase61MonteCarloBlockBootstrap:

    def test_all_bootstrap_methods_execute_and_produce_valid_metrics(self):
        tester = MonteCarloStressTester(num_simulations=200, random_state=42)
        rng = np.random.default_rng(42)
        trades = list(rng.normal(25.0, 50.0, size=60))

        methods = ["circular_block", "moving_block", "stationary", "iid"]
        for m in methods:
            report = tester.run_stress_test(trades, method=m, block_size=4)
            assert isinstance(report, MonteCarloReport)
            assert report.bootstrap_method == m
            assert report.num_simulations == 200
            assert report.max_drawdown_percentile_95 >= 0.0
            assert report.cvar_95 >= report.var_95
            assert report.max_consecutive_losses_p95 >= 1

    def test_optimal_block_size_estimator(self):
        tester = MonteCarloStressTester()
        # Série com autocorrelação positiva forte
        autocorr_trades = np.array([20.0, 25.0, 30.0, 22.0, -15.0, -20.0, -25.0, -18.0] * 10)
        b_opt = tester.estimate_optimal_block_size(autocorr_trades)
        assert b_opt >= 2
        assert b_opt <= len(autocorr_trades) // 3

    def test_block_bootstrap_captures_loss_clustering_better_than_iid(self):
        """
        Teste Empírico Crítico: Cria uma série com perdas altamente agrupadas (volatility clustering).
        O Circular Block Bootstrap deve detectar maior sequência de perdas e maior drawdown que o IID.
        """
        tester = MonteCarloStressTester(num_simulations=500, random_state=42)
        
        # Série com blocos alternados de 6 perdas seguidas de 6 ganhos
        clustered_trades = []
        for _ in range(8):
            clustered_trades.extend([-40.0, -45.0, -50.0, -35.0, -60.0, -30.0])  # Bloco adverso
            clustered_trades.extend([80.0, 70.0, 60.0, 90.0, 75.0, 85.0])         # Bloco favorável

        comp = tester.compare_iid_vs_block(clustered_trades, block_size=6)
        assert isinstance(comp, BootstrapComparisonReport)
        assert comp.block_size == 6

        # O Block Bootstrap DEVE identificar sequências de perdas p95 maiores ou iguais ao IID
        assert comp.block_max_loss_streak_p95 >= comp.iid_max_loss_streak_p95
        # O drawdown no percentil 95 sob Block Bootstrap deve ser estritamente maior que IID
        assert comp.block_max_drawdown_p95 > comp.iid_max_drawdown_p95
        assert comp.verdict == "IID_UNDERESTIMATES_TAIL_RISK"


class TestPhase61PurgedWalkForwardTimestamp:

    def test_purged_splits_by_timestamp_guarantees_no_temporal_leakage(self):
        validator = PurgedWalkForwardValidator(
            n_splits=3,
            forward_horizon=4,
            embargo_pct=0.04,
        )
        bars = _create_synthetic_bars_with_timestamps(n_bars=150)
        splits = validator.generate_purged_splits_by_timestamp(bars)

        assert len(splits) == 3

        for train_idx, test_idx, purged_count, embargo_count in splits:
            assert len(train_idx) > 0
            assert len(test_idx) > 0
            assert purged_count > 0

            test_start_time = bars[test_idx[0]].time
            test_end_time = bars[test_idx[-1]].time

            # 1. Verifica purga temporal: nenhuma barra de treino pré-teste pode ter t_outcome >= test_start_time
            early_train = [i for i in train_idx if i < test_idx[0]]
            for i in early_train:
                outcome_idx = min(len(bars) - 1, i + validator.forward_horizon)
                assert bars[outcome_idx].time < test_start_time

            # 2. Verifica embargo temporal: nenhuma barra pós-teste pode ter tempo <= test_end_time + embargo
            late_train = [i for i in train_idx if i > test_idx[-1]]
            if late_train:
                total_span = bars[-1].time - bars[0].time
                embargo_delta = total_span * validator.embargo_pct
                for i in late_train:
                    assert bars[i].time > (test_end_time + embargo_delta)

    def test_realistic_backtest_economics_without_artificial_heuristics(self):
        """
        Valida que a avaliação econômica nos folds do Walk-Forward calcula
        custos reais de spread, comissão e slippage, sem usar +20/-10.
        """
        validator = PurgedWalkForwardValidator(
            n_splits=3,
            forward_horizon=4,
            spread_points=0.00015,
            commission_per_lot=7.00,
            slippage_points=0.00005,
            default_lot_size=0.10,
        )
        bars = _create_synthetic_bars_with_timestamps(n_bars=180)
        spec = SymbolSpecification(
            symbol="EURUSD",
            canonical_name="EURUSD",
            category="forex_major",
            base_currency="EUR",
            quote_currency="USD",
            digits=5,
            point=0.00001,
            tick_size=0.00001,
            tick_value=1.0,
            contract_size=100000.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
        )

        report = validator.validate(bars, spec=spec)
        assert isinstance(report, ValidationReport)
        assert report.total_folds > 0

        # Verifica se os custos de transação foram efetivamente computados
        if report.total_oos_trades > 0:
            assert report.total_transaction_costs > 0.0
            assert report.cost_sensitivity_pf_2x_mean >= 0.0
            for fold in report.fold_results:
                if fold.total_trades > 0:
                    assert fold.total_costs_paid > 0.0
                    assert fold.sharpe_ratio != 0.0 or fold.total_trades < 2


class TestPhase61DataIntegrityAudit:

    def test_audit_clean_series_is_valid(self):
        bars = _create_synthetic_bars_with_timestamps(n_bars=60)
        report = audit_market_data_integrity(bars, symbol="EURUSD")
        assert report.is_valid is True
        assert report.total_bars == 60
        assert report.duplicate_timestamps_count == 0
        assert report.out_of_order_count == 0
        assert report.invalid_ohlc_count == 0

    def test_audit_detects_out_of_order_and_duplicates(self):
        bars = _create_synthetic_bars_with_timestamps(n_bars=30)
        # Injeta timestamp duplicado e desordem
        bars[10] = MarketBar(
            symbol=bars[9].symbol,
            timeframe=bars[9].timeframe,
            time=bars[9].time,  # Duplicado!
            open=bars[9].open,
            high=bars[9].high,
            low=bars[9].low,
            close=bars[9].close,
            tick_volume=100,
            spread=1,
        )

        report = audit_market_data_integrity(bars, symbol="EURUSD")
        assert report.is_valid is False
        assert report.duplicate_timestamps_count >= 1
        assert report.out_of_order_count >= 1

    def test_audit_detects_invalid_ohlc(self):
        bars = _create_synthetic_bars_with_timestamps(n_bars=20)
        # Injeta High < Low via model_construct para simular dado bruto corrompido
        bars[5] = MarketBar.model_construct(
            symbol=bars[5].symbol,
            timeframe=bars[5].timeframe,
            time=bars[5].time,
            open=1.1000,
            high=1.0900,  # High menor que low!
            low=1.0950,
            close=1.0920,
            tick_volume=100,
            spread=1,
        )

        report = audit_market_data_integrity(bars, symbol="EURUSD")
        assert report.is_valid is False
        assert report.invalid_ohlc_count >= 1
