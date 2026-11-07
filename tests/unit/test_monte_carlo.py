"""
QUANT HERMES — TESTES DO SIMULADOR DE ESTRESSE MONTE CARLO
Módulo: tests.unit.test_monte_carlo
"""
import numpy as np
import pytest

from intelligence.learning.monte_carlo import MonteCarloReport, MonteCarloStressTester


class TestMonteCarloStressTester:

    def test_insufficient_trades_raises(self):
        tester = MonteCarloStressTester()
        with pytest.raises(ValueError, match="Mínimo de 10 trades"):
            tester.run_stress_test(trade_pnls=[10.0, -5.0, 15.0])

    def test_stress_test_healthy_strategy(self):
        tester = MonteCarloStressTester(
            num_simulations=500,
            emergency_drawdown_limit=0.08,
            max_acceptable_ruin_probability=0.01,
            initial_capital=10000.0,
            random_state=42,
        )

        # 60% win rate, R:R 2:1 (win=30.0, loss=-15.0)
        rng = np.random.default_rng(42)
        trades = []
        for _ in range(80):
            if rng.random() < 0.60:
                trades.append(30.0)
            else:
                trades.append(-15.0)

        report = tester.run_stress_test(trades)
        assert isinstance(report, MonteCarloReport)
        assert report.num_simulations == 500
        assert report.probability_of_ruin <= 0.01
        assert report.is_robust is True
        assert report.mean_expectancy > 0.0
        assert report.max_drawdown_percentile_95 < 0.08
        assert report.cvar_95 >= report.var_95

    def test_stress_test_fragile_strategy_rejection(self):
        tester = MonteCarloStressTester(
            num_simulations=500,
            emergency_drawdown_limit=0.08,
            max_acceptable_ruin_probability=0.01,
            initial_capital=10000.0,
            random_state=42,
        )

        # Estratégia perdedora e com perdas severas (fat tails negativas)
        fragile_trades = [-150.0, -200.0, -100.0, 50.0, -300.0, -250.0, 20.0, -400.0, 10.0, -500.0, -350.0]

        report = tester.run_stress_test(fragile_trades)
        assert report.is_robust is False
        assert len(report.rejection_reasons) > 0
        assert report.probability_of_ruin > 0.01 or report.mean_expectancy <= 0.0

    def test_confidence_interval_bounds(self):
        tester = MonteCarloStressTester(num_simulations=300, random_state=42)
        trades = [25.0, -10.0, 30.0, -15.0, 20.0, 40.0, -10.0, -15.0, 35.0, 15.0, -10.0, 25.0]

        report = tester.run_stress_test(trades)
        ci = report.confidence_interval_95
        assert ci["lower"] <= report.median_terminal_equity <= ci["upper"]

