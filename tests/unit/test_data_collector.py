"""
Testes Unitários do Coletor de Dados de Mercado
Arquivo: tests/unit/test_data_collector.py
"""
import pytest
from datetime import datetime, timedelta, timezone
from core.event_bus import PrioritizedEventBus
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.ingestion.collector import MarketDataCollector
from execution.adapters.paper import PaperTradingAdapter


@pytest.mark.asyncio
class TestMarketDataCollector:
    """Valida a sanitização, desduplicação e detecção de lacunas de dados de mercado."""

    async def test_valid_tick_ingestion(self):
        adapter = PaperTradingAdapter()
        bus = PrioritizedEventBus()
        collector = MarketDataCollector(adapter, bus)

        tick = MarketTick(
            symbol="EURUSD",
            time=datetime.now(timezone.utc),
            bid=1.08500,
            ask=1.08515,
            volume=5.0,
        )

        accepted = await collector.ingest_tick(tick)
        assert accepted is True

    async def test_duplicate_tick_rejection(self):
        adapter = PaperTradingAdapter()
        collector = MarketDataCollector(adapter)

        now = datetime.now(timezone.utc)
        tick1 = MarketTick(symbol="EURUSD", time=now, bid=1.08500, ask=1.08515)
        tick2 = MarketTick(symbol="EURUSD", time=now, bid=1.08500, ask=1.08515)

        assert await collector.ingest_tick(tick1) is True
        assert await collector.ingest_tick(tick2) is False  # Duplicado deve ser descartado

    async def test_gap_detection_between_bars(self):
        adapter = PaperTradingAdapter()
        collector = MarketDataCollector(adapter)

        base_time = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
        bar1 = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M5,
            time=base_time,
            open=1.08500,
            high=1.08550,
            low=1.08480,
            close=1.08520,
            tick_volume=100,
        )

        # Salto anômalo de 30 minutos em vez de 5 minutos
        jumped_time = base_time + timedelta(minutes=30)
        bar2 = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M5,
            time=jumped_time,
            open=1.08520,
            high=1.08600,
            low=1.08500,
            close=1.08580,
            tick_volume=120,
        )

        count = await collector.ingest_bars([bar1, bar2])
        assert count == 2

        gaps = collector.get_detected_gaps()
        assert len(gaps) == 1
        assert gaps[0]["symbol"] == "EURUSD"
        assert gaps[0]["missing_seconds"] == 1800.0  # 30 minutos

