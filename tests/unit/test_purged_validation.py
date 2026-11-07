"""
QUANT HERMES — TESTES DE VALIDAÇÃO PURGADA E EMBARGO
Módulo: tests.unit.test_purged_validation
"""
from datetime import datetime, timedelta, timezone
from typing import List
import numpy as np
import pytest

from core.models.market import MarketBar, TimeFrame
from intelligence.learning.validation import PurgedWalkForwardValidator, ValidationReport


def _generate_realistic_market_series(n_bars: int = 250) -> List[MarketBar]:
    """Gera série de 250 barras com regime de mercado e volatilidade oscilante."""
    rng = np.random.default_rng(999)
    start_time = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    bars: List[MarketBar] = []
    price = 1.2500

    for i in range(n_bars):
        # Drift com ruído gaussiano
        drift = 0.0004 if (i % 60) < 30 else -0.0003
        ret = drift + rng.normal(0, 0.0005)
        close = round(price * (1.0 + ret), 5)
        open_p = round(price, 5)
        high = round(max(open_p, close) + abs(rng.normal(0, 0.0002)), 5)
        low = round(min(open_p, close) - abs(rng.normal(0, 0.0002)), 5)

        bars.append(
            MarketBar(
                symbol="GBPUSD",
                timeframe=TimeFrame.M15,
                time=start_time + timedelta(minutes=15 * i),
                open=open_p,
                high=high,
                low=low,
                close=close,
                tick_volume=200,
                spread=1,
            )
        )
        price = close

    return bars


class TestPurgedWalkForwardValidator:

    def test_purged_splits_generation_no_overlap(self):
        validator = PurgedWalkForwardValidator(
            n_splits=3,
            forward_horizon=5,
            embargo_pct=0.03,
        )
        n_samples = 150
        splits = validator.generate_purged_splits(n_samples)

        assert len(splits) == 3

        for train_idx, test_idx, purged_count, embargo_count in splits:
            assert len(test_idx) > 0
            assert len(train_idx) > 0

            # Garantia fundamental: Purging e Embargo
            # Nenhum índice de teste pode estar em treino
            test_set = set(test_idx)
            train_set = set(train_idx)
            assert test_set.isdisjoint(train_set)

            # Purging: As forward_horizon amostras imediatamente anteriores ao teste não devem estar em treino
            test_start = int(test_idx[0])
            for purge_offset in range(1, validator.forward_horizon + 1):
                forbidden_idx = test_start - purge_offset
                if forbidden_idx >= 0:
                    assert forbidden_idx not in train_set

    def test_insufficient_samples_raises(self):
        validator = PurgedWalkForwardValidator()
        with pytest.raises(ValueError, match="Amostras insuficientes"):
            validator.generate_purged_splits(n_samples=50)

    def test_validate_full_cycle_report(self):
        validator = PurgedWalkForwardValidator(
            n_splits=3,
            forward_horizon=5,
            embargo_pct=0.02,
            min_oos_profit_factor=1.10,
            min_oos_win_rate=0.45,
            max_oos_drawdown=0.08,
            min_oos_trades=5,
        )
        bars = _generate_realistic_market_series(n_bars=220)

        report = validator.validate(bars)
        assert isinstance(report, ValidationReport)
        assert report.total_folds > 0
        assert report.mean_profit_factor >= 0.0
        assert 0.0 <= report.mean_win_rate <= 1.0
        assert 0.0 <= report.max_drawdown_observed <= 1.0
        assert len(report.fold_results) == report.total_folds

    def test_constitutional_gate_rejection(self):
        # Validador com threshold inatingível (PF >= 5.0) para verificar bloqueio
        strict_validator = PurgedWalkForwardValidator(
            n_splits=3,
            min_oos_profit_factor=5.00,  # Propositalmente alto para testar reprovação
        )
        bars = _generate_realistic_market_series(n_bars=200)

        report = strict_validator.validate(bars)
        assert report.is_approved_for_production is False
        assert any("Profit Factor OOS" in r for r in report.rejection_reasons)
