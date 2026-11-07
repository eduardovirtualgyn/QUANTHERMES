"""
QUANT HERMES — TESTES DO CLASSIFICADOR SUPERVISIONADO DE ML
Módulo: tests.unit.test_ml_classifier
"""
from datetime import datetime, timedelta, timezone
from typing import List
import numpy as np
import pytest

from core.models.agent import SignalDirection
from core.models.market import MarketBar, TimeFrame
from intelligence.learning.classifier import DirectionPrediction, QuantitativeMLClassifier


def _generate_bars_with_trends(n_bars: int = 180) -> List[MarketBar]:
    """Gera série alternada de tendência de alta e baixa para garantir diversidade de rótulos."""
    rng = np.random.default_rng(123)
    start_time = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
    bars: List[MarketBar] = []
    price = 1.0800

    for i in range(n_bars):
        # Alterna ciclo de alta e baixa
        trend = 0.0006 if (i % 40) < 20 else -0.0006
        ret = trend + rng.normal(0, 0.0004)
        close = round(price * (1.0 + ret), 5)
        open_p = round(price, 5)
        high = round(max(open_p, close) + abs(rng.normal(0, 0.0002)), 5)
        low = round(min(open_p, close) - abs(rng.normal(0, 0.0002)), 5)

        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                time=start_time + timedelta(minutes=15 * i),
                open=open_p,
                high=high,
                low=low,
                close=close,
                tick_volume=150,
                spread=1,
            )
        )
        price = close

    return bars


class TestQuantitativeMLClassifier:

    def test_insufficient_bars_extract_raises(self):
        clf = QuantitativeMLClassifier()
        bars = _generate_bars_with_trends(n_bars=40)
        with pytest.raises(ValueError, match="Mínimo de 60 barras"):
            clf.extract_features(bars)

    def test_feature_names_and_matrix_consistency(self):
        clf = QuantitativeMLClassifier()
        bars = _generate_bars_with_trends(n_bars=120)
        features, valid_indices = clf.extract_features(bars)

        assert features.shape[1] == len(QuantitativeMLClassifier.FEATURE_NAMES)
        assert len(features) == len(bars) - 55  # 55 warmup
        assert not np.isnan(features).any()

    def test_create_labels_triple_barrier(self):
        clf = QuantitativeMLClassifier(forward_bars=5, atr_multiplier=0.8)
        bars = _generate_bars_with_trends(n_bars=150)
        features, valid_indices = clf.extract_features(bars)
        labels = clf.create_labels(bars, valid_indices)

        assert len(labels) == len(valid_indices)
        # Rótulos devem ser 0 (SELL), 1 (HOLD), 2 (BUY)
        unique_labels = set(np.unique(labels))
        assert unique_labels.issubset({0, 1, 2})

    def test_fit_and_predict_lightgbm_engine(self):
        clf = QuantitativeMLClassifier(engine="lightgbm", forward_bars=5, random_state=42)
        bars = _generate_bars_with_trends(n_bars=180)

        clf.fit(bars)
        assert clf.is_fitted is True

        pred = clf.predict(bars)
        assert isinstance(pred, DirectionPrediction)
        assert pred.direction in (SignalDirection.BUY, SignalDirection.SELL, SignalDirection.HOLD)
        assert 0.0 <= pred.confidence <= 1.0
        assert "BUY" in pred.probabilities
        assert "SELL" in pred.probabilities
        assert "HOLD" in pred.probabilities
        assert len(pred.features) == 10

    def test_fit_and_predict_xgboost_engine(self):
        clf = QuantitativeMLClassifier(engine="xgboost", forward_bars=5, random_state=42)
        bars = _generate_bars_with_trends(n_bars=180)

        clf.fit(bars)
        assert clf.is_fitted is True

        pred = clf.predict(bars)
        assert isinstance(pred, DirectionPrediction)
        assert pred.direction in (SignalDirection.BUY, SignalDirection.SELL, SignalDirection.HOLD)
        assert 0.0 <= pred.confidence <= 1.0

    def test_unfitted_predict_raises_runtime_error(self):
        clf = QuantitativeMLClassifier()
        bars = _generate_bars_with_trends(n_bars=100)
        with pytest.raises(RuntimeError, match="não treinado"):
            clf.predict(bars)
