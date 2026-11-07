"""
QUANT HERMES — TESTES DO ORQUESTRADOR CENTRAL AUTÔNOMO
Módulo: tests.unit.test_orchestrator
"""
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
import numpy as np
import pytest

from core.models.market import MarketBar, TimeFrame
from execution.adapters.paper import PaperTradingAdapter
from execution.orchestrator import AutonomousTradingOrchestrator, SessionSummary


def _generate_synthetic_bars(
    symbol: str = "EURUSD",
    n_bars: int = 80,
    trend: float = 0.0006,
    vol: float = 0.0008,
) -> List[MarketBar]:
    """Gera série de barras com tendência persistente para acionamento de estratégias."""
    rng = np.random.default_rng(42)
    start_time = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
    bars: List[MarketBar] = []
    price = 1.1000

    for i in range(n_bars):
        ret = trend + rng.normal(0, vol * 0.5)
        close = round(price * (1.0 + ret), 5)
        open_p = round(price, 5)
        high = round(max(open_p, close) + abs(rng.normal(0, 0.0002)), 5)
        low = round(min(open_p, close) - abs(rng.normal(0, 0.0002)), 5)

        bars.append(
            MarketBar(
                symbol=symbol,
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


@pytest.fixture
async def temp_orchestrator():
    temp_dir = tempfile.mkdtemp()
    state_file = Path(temp_dir) / "test_exec_state.json"
    adapter = PaperTradingAdapter(initial_balance=10000.0)

    orchestrator = AutonomousTradingOrchestrator(
        adapter=adapter,
        symbols=["EURUSD", "GBPUSD"],
        storage_path=str(state_file),
    )
    yield orchestrator
    await orchestrator.shutdown()
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestAutonomousTradingOrchestrator:

    @pytest.mark.asyncio
    async def test_initialization_and_shutdown(self, temp_orchestrator):
        assert temp_orchestrator.is_initialized is False
        await temp_orchestrator.initialize()

        assert temp_orchestrator.is_initialized is True
        assert temp_orchestrator.is_running is True
        assert await temp_orchestrator.adapter.is_connected() is True
        assert temp_orchestrator.state_manager.current_state.system_status == "RUNNING"

        await temp_orchestrator.shutdown()
        assert temp_orchestrator.is_running is False
        assert await temp_orchestrator.adapter.is_connected() is False
        assert temp_orchestrator.state_manager.current_state.system_status == "STOPPED"

    @pytest.mark.asyncio
    async def test_reconciliation_cycle(self, temp_orchestrator):
        await temp_orchestrator.initialize()
        report = await temp_orchestrator.run_reconciliation_cycle()

        assert report is not None
        assert report.is_synced is True
        assert temp_orchestrator.state_manager.current_state.last_reconciliation_utc is not None

    @pytest.mark.asyncio
    async def test_bar_processing_full_pipeline(self, temp_orchestrator):
        await temp_orchestrator.initialize()
        bars = _generate_synthetic_bars(symbol="EURUSD", n_bars=60, trend=0.001)

        # Processa as barras sequencialmente
        executed_orders = []
        for bar in bars:
            result = await temp_orchestrator.process_bar(bar)
            if result is not None and result.success:
                executed_orders.append(result)

        # O pipeline deve ter executado as avaliações mantendo integridade
        assert temp_orchestrator._session_metrics["bars"] == len(bars)
        if executed_orders:
            first_order = executed_orders[0]
            assert first_order.order_ticket > 0
            assert first_order.order_ticket in temp_orchestrator.state_manager.current_state.tracked_tickets

    @pytest.mark.asyncio
    async def test_run_simulation_session(self, temp_orchestrator):
        bars_eur = _generate_synthetic_bars(symbol="EURUSD", n_bars=45, trend=0.0008)
        bars_gbp = _generate_synthetic_bars(symbol="GBPUSD", n_bars=45, trend=-0.0008)

        session_summary = await temp_orchestrator.run_simulation_session({
            "EURUSD": bars_eur,
            "GBPUSD": bars_gbp,
        })

        assert isinstance(session_summary, SessionSummary)
        assert session_summary.total_bars_processed >= 45
        assert session_summary.reconciliation_reports_count >= 1
        assert session_summary.final_account_equity > 0.0
