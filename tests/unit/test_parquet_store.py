"""
Testes Unitários do Repositório Histórico Parquet e Garantia Anti-Lookahead
Arquivo: tests/unit/test_parquet_store.py
"""
import pytest
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from core.models.market import MarketBar, TimeFrame
from data.storage.parquet_store import HistoricalDataStore

TEST_STORAGE_DIR = Path("data/storage_test")


@pytest.fixture(autouse=True)
def clean_test_storage():
    """Garante limpeza antes e depois de cada teste."""
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)
    yield
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)


class TestHistoricalDataStore:
    """Valida persistência colunar Parquet e prevenção de viés de antecipação."""

    def test_save_and_load_bars(self):
        store = HistoricalDataStore(base_dir=TEST_STORAGE_DIR)
        base_time = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)

        bars = [
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M5,
                time=base_time + timedelta(minutes=5 * i),
                open=1.08500 + i * 0.0001,
                high=1.08550 + i * 0.0001,
                low=1.08480 + i * 0.0001,
                close=1.08520 + i * 0.0001,
                tick_volume=100 + i,
            )
            for i in range(5)
        ]

        total = store.save_bars("EURUSD", TimeFrame.M5, bars)
        assert total == 5

        loaded = store.load_bars("EURUSD", TimeFrame.M5)
        assert len(loaded) == 5
        assert loaded[0].close == 1.08520
        assert loaded[4].close == 1.08560

    def test_deduplication_on_resave(self):
        store = HistoricalDataStore(base_dir=TEST_STORAGE_DIR)
        t = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)

        bar1 = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M5,
            time=t,
            open=1.08500,
            high=1.08550,
            low=1.08480,
            close=1.08520,
            tick_volume=100,
        )

        store.save_bars("EURUSD", TimeFrame.M5, [bar1])
        # Re-salva a mesma barra
        store.save_bars("EURUSD", TimeFrame.M5, [bar1])

        loaded = store.load_bars("EURUSD", TimeFrame.M5)
        assert len(loaded) == 1

    def test_anti_lookahead_guarantee(self):
        """
        PROVA MATEMÁTICA ANTI-LOOKAHEAD:
        Se temos barras em 10:00, 10:05, 10:10 e 10:15, e a decisão é tomada às 10:05,
        o modelo NUNCA deve enxergar as barras de 10:10 ou 10:15.
        """
        store = HistoricalDataStore(base_dir=TEST_STORAGE_DIR)
        t0 = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)

        bars = [
            MarketBar(symbol="EURUSD", timeframe=TimeFrame.M5, time=t0, open=1.08, high=1.09, low=1.07, close=1.085, tick_volume=10),
            MarketBar(symbol="EURUSD", timeframe=TimeFrame.M5, time=t0 + timedelta(minutes=5), open=1.085, high=1.095, low=1.08, close=1.09, tick_volume=20),
            MarketBar(symbol="EURUSD", timeframe=TimeFrame.M5, time=t0 + timedelta(minutes=10), open=1.09, high=1.10, low=1.085, close=1.095, tick_volume=30),  # FUTURO
            MarketBar(symbol="EURUSD", timeframe=TimeFrame.M5, time=t0 + timedelta(minutes=15), open=1.095, high=1.105, low=1.09, close=1.10, tick_volume=40),   # FUTURO
        ]
        store.save_bars("EURUSD", TimeFrame.M5, bars)

        # Momento exato da decisão: 10:05
        decision_time = t0 + timedelta(minutes=5)
        as_of_bars = store.get_bars_as_of("EURUSD", TimeFrame.M5, as_of=decision_time)

        # Deve conter exatamente 2 barras (10:00 e 10:05)
        assert len(as_of_bars) == 2
        assert max(b.time for b in as_of_bars) <= decision_time
        # Prova que dados futuros de 10:10 e 10:15 foram estritamente bloqueados
        assert not any(b.time > decision_time for b in as_of_bars)
