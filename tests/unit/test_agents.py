"""
QUANT HERMES — Testes dos Agentes Especializados de Inteligência
Arquivo: tests/unit/test_agents.py
"""
import numpy as np
import pytest
from datetime import datetime, timedelta, timezone

from core.models.agent import SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from core.models.regime import MarketRegimeType
from intelligence.agents.ag01_trend import TrendIntelligenceAgent
from intelligence.agents.ag02_structure import MarketStructureAgent
from intelligence.agents.ag03_momentum import MomentumBreakoutAgent
from intelligence.agents.ag04_mean_reversion import MeanReversionAgent
from intelligence.agents.ag05_gold_macro import GoldMacroAgent
from intelligence.agents.ag06_quantitative import QuantitativeAgent
from intelligence.agents.ag07_adversarial import AdversarialResearchAgent


def create_bars(
    n_bars: int = 60,
    slope: float = 0.0002,
    vol: float = 0.0003,
    start: float = 1.08500,
    timeframe: TimeFrame = TimeFrame.M15,
) -> list[MarketBar]:
    bars = []
    t0 = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    curr = start
    for i in range(n_bars):
        delta = slope + np.random.normal(0, vol)
        close_p = curr + delta
        high_p = max(curr, close_p) + abs(np.random.normal(0, vol * 0.5))
        low_p = min(curr, close_p) - abs(np.random.normal(0, vol * 0.5))
        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=timeframe,
                time=t0 + timedelta(minutes=15 * i),
                open=round(curr, 5),
                high=round(high_p, 5),
                low=round(low_p, 5),
                close=round(close_p, 5),
                tick_volume=100.0,
            )
        )
        curr = close_p
    return bars


class TestSpecializedAgents:
    """Testes dos 8 agentes especialistas de inteligência."""

    def test_ag01_trend_intelligence(self):
        np.random.seed(42)
        bars = create_bars(n_bars=70, slope=0.0004, vol=0.0001)
        multi_tf = {TimeFrame.M15: bars, TimeFrame.H1: bars}

        agent = TrendIntelligenceAgent()
        sig = agent.analyze(multi_tf, "EURUSD")
        if sig is not None:
            assert sig.direction == SignalDirection.BUY
            assert sig.agent_id == "AG01_TREND"
            assert sig.suggested_stop < sig.suggested_entry

    def test_ag02_market_structure(self):
        bars = create_bars(n_bars=50, slope=0.0003, vol=0.0001)
        multi_tf = {TimeFrame.M15: bars}

        agent = MarketStructureAgent()
        sig = agent.analyze(multi_tf, "EURUSD")
        if sig is not None:
            assert sig.agent_id == "AG02_STRUCTURE"
            assert sig.direction in (SignalDirection.BUY, SignalDirection.SELL)

    def test_ag03_momentum_breakout(self):
        bars = create_bars(n_bars=50, slope=0.0, vol=0.0001)
        # Insere barra explosiva
        last = bars[-1]
        big_bar = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M15,
            time=last.time + timedelta(minutes=15),
            open=last.close,
            high=last.close + 0.00400,
            low=last.close - 0.00010,
            close=last.close + 0.00380,
            tick_volume=500.0,
        )
        bars.append(big_bar)
        multi_tf = {TimeFrame.M15: bars}

        agent = MomentumBreakoutAgent()
        sig = agent.analyze(multi_tf, "EURUSD")
        assert sig is not None
        assert sig.agent_id == "AG03_MOMENTUM"
        assert sig.direction == SignalDirection.BUY

    def test_ag04_mean_reversion_veto_in_strong_trend(self):
        # Em forte tendência (ADX alto), AG04 deve vetar qualquer sinal de reversão
        bars = create_bars(n_bars=70, slope=0.0008, vol=0.0001)
        multi_tf = {TimeFrame.M15: bars}

        agent = MeanReversionAgent(max_adx=25.0)
        sig = agent.analyze(multi_tf, "EURUSD")
        assert sig is None

    def test_ag05_gold_macro_news_blackout(self):
        bars = create_bars(n_bars=50, start=2650.0)
        multi_tf = {TimeFrame.M15: bars}

        now = datetime(2026, 11, 4, 13, 30, tzinfo=timezone.utc)
        tick = MarketTick(
            symbol="XAUUSD",
            time=now,
            bid=2650.0,
            ask=2650.3,
            last=2650.1,
            volume=10.0,
        )
        # Notícia de CPI exatamente às 13:30 (dentro do blackout de 15 min)
        macro_context = {
            "upcoming_news": [
                {
                    "title": "US CPI",
                    "impact": "HIGH",
                    "time": datetime(2026, 11, 4, 13, 30, tzinfo=timezone.utc),
                }
            ]
        }

        agent = GoldMacroAgent()
        sig = agent.analyze(multi_tf, "XAUUSD", current_tick=tick, macro_context=macro_context)
        assert sig is not None
        assert sig.direction == SignalDirection.HOLD
        assert sig.rationale.get("news_blackout_active") is True

    def test_ag06_quantitative_regime_classification(self):
        bars = create_bars(n_bars=60, slope=0.0005, vol=0.0002)
        agent = QuantitativeAgent()
        classification = agent.classify_regime(bars, "EURUSD")

        assert isinstance(classification.active_regime, MarketRegimeType)
        assert 0.0 <= classification.confidence <= 1.0
        assert 0.0 <= classification.entropy <= 1.0
        assert len(classification.probabilities) == len(MarketRegimeType)

    def test_ag07_adversarial_detects_traps(self):
        bars = create_bars(n_bars=40)
        # Cria pavio de rejeição brutal no topo (Bull Trap)
        last = bars[-1]
        trap_bar = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M15,
            time=last.time + timedelta(minutes=15),
            open=last.close,
            high=last.close + 0.00300,  # Esticada
            low=last.close - 0.00020,
            close=last.close + 0.00030,  # Fechou perto da abertura -> pavio enorme
            tick_volume=300.0,
        )
        bars.append(trap_bar)

        agent = AdversarialResearchAgent()
        debate = agent.debate(SignalDirection.BUY, bars, "EURUSD")

        assert debate.risk_penalty_factor > 0.0
        assert any("BULL_TRAP" in t for t in debate.detected_traps)
