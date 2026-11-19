"""
Nenhuma estratégia pode mostrar edge significativo em um random walk com custos.
Um resultado positivo e significativo aqui é bug de preenchimento, não alfa.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from core.models.agent import SignalDirection
from core.models.market import MarketBar, SymbolSpecification, TimeFrame
from strategies.backtest.engine import BacktestEngine
from strategies.base import BaseStrategy
from strategies.breakout.volatility_breakout import VolatilityBreakoutStrategy
from strategies.mean_reversion.statistical_reversion import StatisticalMeanReversionStrategy
from strategies.momentum.momentum_surge import MomentumSurgeStrategy
from strategies.pullback.trend_pullback import TrendPullbackStrategy
from strategies.scalping.micro_momentum import MicroMomentumScalpingStrategy
from strategies.smc.structure_break import SMCStructureStrategy
from strategies.swing.macro_swing import MacroSwingStrategy


class _ControlBuy(BaseStrategy):
    """Controle: entra com frequência fixa. Sem custo isso fabrica edge; com custo, não."""

    def __init__(self) -> None:
        super().__init__(
            strategy_id="STRAT_CONTROL_RANDOM",
            family="momentum",
            target_symbols=["EURUSD"],
            target_timeframes=[TimeFrame.M15],
            min_rr_ratio=1.5,
        )

    def analyze(self, bars, symbol, timeframe, current_tick=None):
        if len(bars) < 40 or len(bars) % 15 != 0:
            return None
        entry = bars[-1].close
        stop_dist = 0.00100
        return self.build_signal(
            symbol=symbol,
            timeframe=timeframe,
            direction=SignalDirection.BUY,
            confidence=0.7,
            entry=entry,
            stop_loss=round(entry - stop_dist, 5),
            take_profit=round(entry + stop_dist * self.min_rr_ratio, 5),
            invalidation_level=round(entry - stop_dist, 5),
            rationale={"control": True},
        )


def _weekday_random_walk(n_bars: int = 900, seed: int = 20261119) -> list[MarketBar]:
    rng = np.random.default_rng(seed)
    cursor = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)  # segunda
    bars: list[MarketBar] = []
    price = 1.10000
    while len(bars) < n_bars:
        if cursor.weekday() >= 4 or cursor.hour < 8 or cursor.hour >= 18:
            cursor += timedelta(minutes=15)
            continue
        shock = float(rng.normal(0.0, 0.00035))
        close = max(0.5, price * (1.0 + shock))
        wick = abs(float(rng.normal(0.0, 0.00025)))
        open_p = price
        high = max(open_p, close) + wick
        low = max(0.4, min(open_p, close) - wick)
        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                time=cursor,
                open=round(open_p, 5),
                high=round(high, 5),
                low=round(low, 5),
                close=round(close, 5),
                tick_volume=int(rng.integers(20, 200)),
                spread=13,
            )
        )
        price = close
        cursor += timedelta(minutes=15)
    return bars


def _significant_positive_edge(result) -> bool:
    return bool(
        result.total_trades >= 25
        and result.expectancy_r > 0.0
        and result.t_stat > 1.96
        and result.ci95_low_r > 0.0
    )


def test_strategies_have_no_significant_edge_on_random_walk():
    spec = SymbolSpecification(
        symbol="EURUSD",
        canonical_name="EURUSD",
        category="forex_major",
        base_currency="EUR",
        quote_currency="USD",
        digits=5,
        point=0.00001,
        tick_size=0.00001,
        tick_value=1.0,
        contract_size=100000.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        swap_long=-6.4,
        swap_short=-3.2,
        swap_mode="points",
    )
    bars = _weekday_random_walk()
    engine = BacktestEngine(initial_balance=100000.0)
    strategies = [
        MicroMomentumScalpingStrategy(),
        VolatilityBreakoutStrategy(),
        MomentumSurgeStrategy(),
        TrendPullbackStrategy(),
        StatisticalMeanReversionStrategy(),
        SMCStructureStrategy(),
        MacroSwingStrategy(),
        _ControlBuy(),
    ]
    for strategy in strategies:
        result = engine.run(
            strategy=strategy,
            bars=bars,
            spec=spec,
            spread_points=1.3 * 0.0001,
            slippage_price=0.2 * 0.0001,
            charge_swap=True,
        )
        assert not _significant_positive_edge(result), (
            f"{strategy.strategy_id} mostrou edge em random walk: "
            f"trades={result.total_trades} E[R]={result.expectancy_r} t={result.t_stat}"
        )

    control = engine.run(
        strategy=_ControlBuy(),
        bars=bars,
        spec=spec,
        spread_points=1.3 * 0.0001,
        slippage_price=0.2 * 0.0001,
    )
    assert control.total_trades >= 20
    # A faixa +0.02R a +0.035R era o artefato do fill otimista sem custo.
    assert control.expectancy_r < 0.01
