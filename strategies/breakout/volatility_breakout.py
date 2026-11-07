"""
QUANT HERMES — Estratégia de Rompimento de Volatilidade (Volatility Breakout)
Módulo: strategies.breakout.volatility_breakout
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, calc_bollinger_bands, calc_donchian
from strategies.base import BaseStrategy


class VolatilityBreakoutStrategy(BaseStrategy):
    """
    Estratégia de Rompimento de Volatilidade.
    Detecta expansão explosiva de range a partir de compressão de volatilidade
    (Bollinger Squeeze) com confirmação de rompimento de canais Donchian.
    """

    def __init__(
        self,
        strategy_id: str = "STRAT_BREAKOUT_VOLATILITY",
        target_symbols: Optional[List[str]] = None,
        target_timeframes: Optional[List[TimeFrame]] = None,
        min_rr_ratio: float = 2.0,
        bb_period: int = 20,
        donchian_period: int = 20,
        atr_period: int = 14,
        expansion_threshold: float = 1.3,
    ):
        symbols = target_symbols or ["EURUSD", "GBPUSD", "XAUUSD"]
        timeframes = target_timeframes or [TimeFrame.M5, TimeFrame.M15, TimeFrame.H1]
        super().__init__(
            strategy_id=strategy_id,
            family="breakout",
            target_symbols=symbols,
            target_timeframes=timeframes,
            min_rr_ratio=min_rr_ratio,
        )
        self.bb_period = bb_period
        self.donchian_period = donchian_period
        self.atr_period = atr_period
        self.expansion_threshold = expansion_threshold

    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        min_bars = max(self.bb_period, self.donchian_period, self.atr_period) + 10
        if len(bars) < min_bars:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        upper_bb, mid_bb, lower_bb = calc_bollinger_bands(closes, self.bb_period, 2.0)
        upper_dc, _, lower_dc = calc_donchian(highs, lows, self.donchian_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        curr_close = closes[-1]
        curr_high = highs[-1]
        curr_low = lows[-1]
        curr_bar_range = curr_high - curr_low
        curr_atr = atr[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Expansão de range na barra atual
        is_expanding = curr_bar_range > (curr_atr * self.expansion_threshold)
        if not is_expanding:
            return None

        entry_price = current_tick.ask if current_tick and current_tick.ask > 0 else curr_close

        # Rompimento de ALTA (BUY)
        # Preço fecha acima da banda de Bollinger superior e fecha na máxima recente
        prev_upper_dc = upper_dc[-2]
        if curr_close > upper_bb[-1] and curr_close >= prev_upper_dc:
            stop_loss = round(mid_bb[-1], 5)
            risk_dist = abs(entry_price - stop_loss)
            if risk_dist <= 0:
                return None
            take_profit = round(entry_price + (risk_dist * self.min_rr_ratio), 5)

            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.BUY,
                confidence=0.80,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(mid_bb[-1], 5),
                rationale={
                    "breakout_type": "BOLLINGER_DONCHIAN_BULLISH",
                    "bar_range": round(curr_bar_range, 5),
                    "atr": round(curr_atr, 5),
                },
            )

        # Rompimento de BAIXA (SELL)
        entry_price_sell = current_tick.bid if current_tick and current_tick.bid > 0 else curr_close
        prev_lower_dc = lower_dc[-2]
        if curr_close < lower_bb[-1] and curr_close <= prev_lower_dc:
            stop_loss = round(mid_bb[-1], 5)
            risk_dist = abs(stop_loss - entry_price_sell)
            if risk_dist <= 0:
                return None
            take_profit = round(entry_price_sell - (risk_dist * self.min_rr_ratio), 5)

            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.SELL,
                confidence=0.80,
                entry=entry_price_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(mid_bb[-1], 5),
                rationale={
                    "breakout_type": "BOLLINGER_DONCHIAN_BEARISH",
                    "bar_range": round(curr_bar_range, 5),
                    "atr": round(curr_atr, 5),
                },
            )

        return None

