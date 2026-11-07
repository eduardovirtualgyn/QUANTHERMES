"""
QUANT HERMES — Testes do Grafo de Fluxo Multiagente (Multi-Agent Workflow)
Arquivo: tests/unit/test_multi_agent_workflow.py
"""
import numpy as np
import pytest
from datetime import datetime, timedelta, timezone

from core.models.agent import SignalDirection
from core.models.market import MarketBar, TimeFrame
from core.models.regime import MarketRegimeType
from intelligence.langgraph.workflow import MultiAgentWorkflow


def create_bars_sequence(n_bars: int = 60, slope: float = 0.0003, timeframe: TimeFrame = TimeFrame.M15):
    bars = []
    t0 = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    curr = 1.08500
    for i in range(n_bars):
        close_p = curr + slope + np.random.normal(0, 0.0001)
        high_p = max(curr, close_p) + 0.0002
        low_p = min(curr, close_p) - 0.0002
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


class TestMultiAgentWorkflow:
    """Testes de integração do fluxo completo da inteligência multiagente."""

    def test_full_cycle_execution(self):
        np.random.seed(42)
        bars_m15 = create_bars_sequence(n_bars=70, slope=0.0004, timeframe=TimeFrame.M15)
        bars_h1 = create_bars_sequence(n_bars=50, slope=0.0008, timeframe=TimeFrame.H1)

        multi_tf = {
            TimeFrame.M15: bars_m15,
            TimeFrame.H1: bars_h1,
        }

        workflow = MultiAgentWorkflow()
        result = workflow.run_cycle(
            bars_multi_tf=multi_tf,
            symbol="EURUSD",
        )

        assert result.symbol == "EURUSD"
        assert isinstance(result.active_regime, MarketRegimeType)
        assert result.classification is not None
        assert isinstance(result.agent_signals, list)
        assert result.adversarial_debate is not None
        assert result.consensus is not None
        assert result.consensus.action in (SignalDirection.BUY, SignalDirection.SELL, SignalDirection.HOLD)
