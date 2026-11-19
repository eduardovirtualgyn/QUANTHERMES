"""
Pipeline paper: sinal → risco → lote → ordem → fill → estado.
O teste usa o orquestrador real, o Risk Engine real e o adapter de paper.
Não há conexão com corretora.
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, TimeFrame
from core.models.regime import MarketRegimeType, RegimeClassification
from execution.adapters.paper import PaperTradingAdapter
from execution.idempotency import SqliteIdempotencyStore
from execution.orchestrator import AutonomousTradingOrchestrator
from execution.order_executor import OrderExecutor
from strategies.base import BaseStrategy


class _AlwaysBuy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__(
            strategy_id="STRAT_E2E_BUY",
            family="momentum",
            target_symbols=["EURUSD"],
            target_timeframes=[TimeFrame.M15],
            min_rr_ratio=1.5,
        )

    def analyze(self, bars, symbol, timeframe, current_tick=None):
        if len(bars) < 3:
            return None
        entry = bars[-1].close
        return self.build_signal(
            symbol=symbol,
            timeframe=timeframe,
            direction=SignalDirection.BUY,
            confidence=0.8,
            entry=entry,
            stop_loss=round(entry - 0.00500, 5),
            take_profit=round(entry + 0.00750, 5),
            invalidation_level=round(entry - 0.00600, 5),
            rationale={"e2e": True},
        )


class _AlignedAgent:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.name = agent_id
        self.quality_factor = 0.9

    def analyze(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick=None,
        macro_context: Optional[dict] = None,
    ) -> Optional[AgentSignal]:
        bars = next(iter(bars_multi_tf.values()))
        bar = bars[-1]
        entry = bar.close
        return AgentSignal(
            agent_id=self.agent_id,
            symbol=symbol,
            timeframe=bar.timeframe,
            direction=SignalDirection.BUY,
            confidence=0.86,
            suggested_entry=entry,
            suggested_stop=round(entry - 0.00500, 5),
            suggested_target=round(entry + 0.00750, 5),
            invalidation_level=round(entry - 0.00600, 5),
            model_version="e2e",
        )


def _bars() -> List[MarketBar]:
    start = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)  # quarta-feira
    bars = []
    price = 1.10000
    for i in range(12):
        close = round(price + 0.00010, 5)
        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                time=start + timedelta(minutes=15 * i),
                open=price,
                high=round(close + 0.00020, 5),
                low=round(price - 0.00010, 5),
                close=close,
                tick_volume=50,
                spread=2,
            )
        )
        price = close
    return bars


@pytest.mark.asyncio
async def test_paper_pipeline_produces_a_filled_order(tmp_path: Path):
    adapter = PaperTradingAdapter(initial_balance=10000.0, leverage=100)
    orchestrator = AutonomousTradingOrchestrator(
        adapter=adapter,
        symbols=["EURUSD"],
        storage_path=str(tmp_path / "state.json"),
    )
    orchestrator.order_executor = OrderExecutor(
        adapter=adapter,
        store=SqliteIdempotencyStore(db_path=tmp_path / "idem.db"),
        symbol_mapper=orchestrator.symbol_mapper,
    )
    orchestrator.strategies = [_AlwaysBuy()]
    orchestrator.agents = {
        "AG01": _AlignedAgent("AG01_TREND"),
        "AG02": _AlignedAgent("AG02_STRUCTURE"),
        "AG03": _AlignedAgent("AG03_MOMENTUM"),
        "AG06": _AlignedAgent("AG06_QUANT"),
    }

    def _regime(symbol: str, bars: List[MarketBar]) -> RegimeClassification:
        return RegimeClassification(
            symbol=symbol,
            timeframe="M15",
            active_regime=MarketRegimeType.TREND_BULL_STRONG,
            probabilities={"TREND_BULL_STRONG": 0.9},
            confidence=0.9,
            entropy=0.2,
        )

    orchestrator._classify_regime_for_symbol = _regime  # type: ignore[method-assign]

    try:
        await orchestrator.initialize()
        fills = []
        for bar in _bars():
            result = await orchestrator.process_bar(bar)
            if result is not None and result.success:
                fills.append(result)

        assert fills, "o pipeline paper precisa produzir ao menos uma ordem"
        fill = fills[0]
        assert fill.order_ticket > 0
        assert fill.volume_executed > 0
        assert fill.retcode == 10009

        positions = await adapter.get_open_positions()
        assert len(positions) == 1
        assert positions[0].ticket == fill.order_ticket
        assert positions[0].volume == fill.volume_executed
        assert positions[0].stop_loss > 0

        assert fill.order_ticket in orchestrator.state_manager.current_state.tracked_tickets
        stored = orchestrator.order_executor.store.get_intent_by_key(fill.idempotency_key)
        assert stored is not None
        assert stored["requested_lot"] == stored["authorized_lot"]
        assert stored["requested_lot"] > 0
        assert stored["state"] in {"FILLED", "PARTIALLY_FILLED"}
    finally:
        await orchestrator.shutdown()
        shutil.rmtree(tmp_path, ignore_errors=True)
