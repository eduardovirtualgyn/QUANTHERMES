"""
QUANT HERMES — TESTES DO DETECTOR DE REGIMES VIA HMM
Módulo: tests.unit.test_hmm_detector
"""
from datetime import datetime, timedelta, timezone
from typing import List
import numpy as np
import pytest

from core.models.market import MarketBar, TimeFrame
from core.models.regime import MarketRegimeType
from intelligence.agents.ag06_quantitative import QuantitativeAgent
from intelligence.regime.hmm_detector import HMMRegimeDetector


def _generate_synthetic_bars(n_bars: int = 150, trend: float = 0.0005, vol: float = 0.001) -> List[MarketBar]:
    """Gera série sintética de barras OHLCV para teste determinístico."""
    rng = np.random.default_rng(42)
    start_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    bars: List[MarketBar] = []
    price = 1.1000

    for i in range(n_bars):
        ret = trend + rng.normal(0, vol)
        close = round(price * (1.0 + ret), 5)
        open_p = round(price, 5)
        high = round(max(open_p, close) + abs(rng.normal(0, vol * 0.5)), 5)
        low = round(min(open_p, close) - abs(rng.normal(0, vol * 0.5)), 5)

        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                time=start_time + timedelta(minutes=15 * i),
                open=open_p,
                high=high,
                low=low,
                close=close,
                tick_volume=100,
                spread=1,
            )
        )
        price = close

    return bars


class TestHMMRegimeDetector:

    def test_insufficient_bars_fit_raises(self):
        detector = HMMRegimeDetector()
        short_bars = _generate_synthetic_bars(n_bars=30)
        with pytest.raises(ValueError, match="Mínimo de 50 barras"):
            detector.fit(short_bars)

    def test_feature_extraction_shape_and_warmup(self):
        detector = HMMRegimeDetector()
        bars = _generate_synthetic_bars(n_bars=80)
        features, indices = detector.extract_features(bars)

        assert features.shape[1] == 4  # log_ret, realized_vol, atr_ratio, adx
        assert len(features) == len(bars) - 25  # 25 barras de warmup
        assert len(indices) == len(features)
        assert not np.isnan(features).any()

    def test_fit_and_predict_regime_convergence(self):
        detector = HMMRegimeDetector(n_components=4, n_iter=100, random_state=42)
        bars = _generate_synthetic_bars(n_bars=150, trend=0.0008, vol=0.001)

        detector.fit(bars)
        assert detector.is_fitted is True
        assert len(detector.state_to_regime) > 0

        classification = detector.predict_regime(bars, symbol="EURUSD", timeframe="M15")
        assert classification.symbol == "EURUSD"
        assert classification.timeframe == "M15"
        assert classification.active_regime in MarketRegimeType
        assert 0.0 <= classification.confidence <= 1.0
        assert 0.0 <= classification.entropy <= 1.0
        assert sum(classification.probabilities.values()) == pytest.approx(1.0, rel=1e-2)

    def test_fallback_heuristic_when_not_fitted(self):
        detector = HMMRegimeDetector()
        bars = _generate_synthetic_bars(n_bars=40)

        # Sem chamar fit(): deve acionar o fallback heurístico fail-safe
        classification = detector.predict_regime(bars, symbol="GBPUSD", timeframe="M15")
        assert classification.symbol == "GBPUSD"
        assert classification.active_regime in MarketRegimeType
        assert classification.confidence > 0.0

    def test_integration_with_ag06_quantitative_agent(self):
        detector = HMMRegimeDetector()
        bars = _generate_synthetic_bars(n_bars=120, trend=0.001)
        detector.fit(bars)

        agent = QuantitativeAgent(hmm_detector=detector)
        classification = agent.classify_regime(bars, symbol="EURUSD")

        assert classification.symbol == "EURUSD"
        assert classification.active_regime in MarketRegimeType
        assert len(classification.probabilities) > 0
