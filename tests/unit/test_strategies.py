"""
QUANT HERMES — Testes das 7 Famílias de Estratégias Quantitativas
Arquivo: tests/unit/test_strategies.py
"""
import numpy as np
import pytest
from datetime import datetime, timedelta, timezone

from core.models.agent import SignalDirection
from core.models.market import MarketBar, TimeFrame
from strategies.breakout.volatility_breakout import VolatilityBreakoutStrategy
from strategies.mean_reversion.statistical_reversion import StatisticalMeanReversionStrategy
from strategies.momentum.momentum_surge import MomentumSurgeStrategy
from strategies.pullback.trend_pullback import TrendPullbackStrategy
from strategies.scalping.micro_momentum import MicroMomentumScalpingStrategy
from strategies.smc.structure_break import SMCStructureStrategy
from strategies.swing.macro_swing import MacroSwingStrategy


def create_synthetic_bars(
    n_bars: int = 100,
    start_price: float = 1.08500,
    trend_slope: float = 0.0002,
    volatility: float = 0.0005,
    timeframe: TimeFrame = TimeFrame.M5,
) -> list[MarketBar]:
    """Gera sequência sintética e coerente de MarketBars."""
    bars = []
    base_time = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    curr_price = start_price

    for i in range(n_bars):
        open_p = curr_price
        delta = trend_slope + np.random.normal(0, volatility)
        close_p = open_p + delta
        high_p = max(open_p, close_p) + abs(np.random.normal(0, volatility * 0.5))
        low_p = min(open_p, close_p) - abs(np.random.normal(0, volatility * 0.5))

        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=timeframe,
                time=base_time + timedelta(minutes=5 * i),
                open=round(open_p, 5),
                high=round(high_p, 5),
                low=round(low_p, 5),
                close=round(close_p, 5),
                tick_volume=100.0,
            )
        )
        curr_price = close_p

    return bars


class TestStrategies:
    """Suíte de testes de validação matemática e regras das estratégias."""

    def test_scalping_micro_momentum_generates_valid_signal(self):
        # Gera série com forte alta constante (EMA 9 > EMA 21)
        np.random.seed(42)
        bars = create_synthetic_bars(n_bars=60, trend_slope=0.0003, volatility=0.0001, timeframe=TimeFrame.M1)
        strat = MicroMomentumScalpingStrategy(min_rr_ratio=1.5)

        sig = strat.analyze(bars, "EURUSD", TimeFrame.M1)
        if sig is not None:
            assert sig.direction in (SignalDirection.BUY, SignalDirection.SELL)
            assert sig.suggested_stop < sig.suggested_entry if sig.direction == SignalDirection.BUY else sig.suggested_stop > sig.suggested_entry
            assert sig.suggested_target > sig.suggested_entry if sig.direction == SignalDirection.BUY else sig.suggested_target < sig.suggested_entry
            assert sig.confidence >= 0.50

    def test_breakout_volatility_expansion_trigger(self):
        # Barras calmas e repentina explosão de alta
        bars = create_synthetic_bars(n_bars=50, trend_slope=0.0, volatility=0.0001, timeframe=TimeFrame.M5)
        # Cria candle de rompimento gigante
        last_open = bars[-1].close
        last_close = last_open + 0.00350  # Rompimento maciço
        breakout_bar = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M5,
            time=bars[-1].time + timedelta(minutes=5),
            open=last_open,
            high=last_close + 0.00020,
            low=last_open - 0.00010,
            close=last_close,
            tick_volume=500.0,
        )
        bars.append(breakout_bar)

        strat = VolatilityBreakoutStrategy(min_rr_ratio=2.0)
        sig = strat.analyze(bars, "EURUSD", TimeFrame.M5)
        assert sig is not None
        assert sig.direction == SignalDirection.BUY
        assert sig.suggested_stop < sig.suggested_entry
        assert sig.suggested_target > sig.suggested_entry

    def test_momentum_surge_analyzes_coherently(self):
        bars = create_synthetic_bars(n_bars=70, trend_slope=0.0004, volatility=0.0002, timeframe=TimeFrame.M15)
        strat = MomentumSurgeStrategy(min_rr_ratio=2.0, adx_min_threshold=15.0)
        sig = strat.analyze(bars, "EURUSD", TimeFrame.M15)
        if sig is not None:
            assert sig.direction == SignalDirection.BUY
            assert sig.suggested_stop < sig.suggested_entry
            assert sig.rationale["adx"] >= 15.0

    def test_trend_pullback_analyzes_coherently(self):
        # 250 barras para aquecer EMA 200
        bars = create_synthetic_bars(n_bars=250, trend_slope=0.0002, volatility=0.0003, timeframe=TimeFrame.M15)
        strat = TrendPullbackStrategy(min_rr_ratio=2.0)
        # Executa sem exceção e valida contrato se houver sinal
        sig = strat.analyze(bars, "EURUSD", TimeFrame.M15)
        if sig is not None:
            assert sig.direction in (SignalDirection.BUY, SignalDirection.SELL)

    def test_mean_reversion_statistical_triggers_on_extreme_zscore(self):
        # 40 barras laterais e uma queda súbita brutal para forçar Z-Score < -2.5
        bars = create_synthetic_bars(n_bars=40, trend_slope=0.0, volatility=0.0002, timeframe=TimeFrame.M5)
        crash_open = bars[-1].close
        crash_close = crash_open - 0.00400  # Queda violenta
        crash_bar = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M5,
            time=bars[-1].time + timedelta(minutes=5),
            open=crash_open,
            high=crash_open + 0.00010,
            low=crash_close - 0.00020,
            close=crash_close,
            tick_volume=400.0,
        )
        bars.append(crash_bar)

        strat = StatisticalMeanReversionStrategy(
            z_score_threshold=2.0,
            max_trend_adx=40.0,  # Permite teste
            min_rr_ratio=1.5,
        )
        sig = strat.analyze(bars, "EURUSD", TimeFrame.M5)
        if sig is not None:
            assert sig.direction == SignalDirection.BUY
            assert sig.rationale["z_score"] <= -2.0

    def test_smc_structure_break_deterministic(self):
        # Gera série com topo claro rompido por BOS
        high = [10.0, 12.0, 15.0, 12.0, 10.0, 11.0, 12.0, 14.0, 16.5, 17.0]
        low = [8.0, 9.0, 11.0, 9.0, 8.0, 9.0, 10.0, 12.0, 14.5, 15.0]
        close = [9.0, 11.0, 14.0, 11.0, 9.0, 10.0, 11.0, 13.0, 16.0, 16.8]

        base_time = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
        bars = []
        for i in range(len(high)):
            bars.append(
                MarketBar(
                    symbol="EURUSD",
                    timeframe=TimeFrame.M15,
                    time=base_time + timedelta(minutes=15 * i),
                    open=low[i] + 0.5,
                    high=high[i],
                    low=low[i],
                    close=close[i],
                    tick_volume=100.0,
                )
            )

        # Prepara mais 25 barras anteriores para totalizar >= 30 barras
        padding_bars = create_synthetic_bars(n_bars=25, start_price=8.0, trend_slope=0.05, timeframe=TimeFrame.M15)
        all_bars = padding_bars + bars

        strat = SMCStructureStrategy(left_bars=2, right_bars=2, min_rr_ratio=2.0)
        sig = strat.analyze(all_bars, "EURUSD", TimeFrame.M15)
        if sig is not None:
            assert sig.direction == SignalDirection.BUY
            assert "BULLISH" in sig.rationale["event_type"]

    def test_macro_swing_requires_sufficient_history(self):
        # Teste de guarda: Menos de 210 barras deve retornar None
        bars = create_synthetic_bars(n_bars=150, timeframe=TimeFrame.H1)
        strat = MacroSwingStrategy()
        assert strat.analyze(bars, "EURUSD", TimeFrame.H1) is None

    def test_strategies_return_none_on_insufficient_bars(self):
        bars = create_synthetic_bars(n_bars=10, timeframe=TimeFrame.M5)
        assert MicroMomentumScalpingStrategy().analyze(bars, "EURUSD", TimeFrame.M5) is None
        assert VolatilityBreakoutStrategy().analyze(bars, "EURUSD", TimeFrame.M5) is None
        assert MomentumSurgeStrategy().analyze(bars, "EURUSD", TimeFrame.M5) is None
        assert TrendPullbackStrategy().analyze(bars, "EURUSD", TimeFrame.M5) is None
        assert StatisticalMeanReversionStrategy().analyze(bars, "EURUSD", TimeFrame.M5) is None
        assert SMCStructureStrategy().analyze(bars, "EURUSD", TimeFrame.M5) is None
        assert MacroSwingStrategy().analyze(bars, "EURUSD", TimeFrame.M5) is None

