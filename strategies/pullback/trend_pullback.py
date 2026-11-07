"""
QUANT HERMES — Estratégia de Pullback e Continuação de Tendência
Módulo: strategies.pullback.trend_pullback
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, calc_ema
from strategies.base import BaseStrategy


class TrendPullbackStrategy(BaseStrategy):
    """
    Estratégia de Pullback em Tendência Estabelecida.
    Exige alinhamento de médias maiores (EMA 50 e EMA 200) e identifica
    retrações corretivas na EMA 21 com rejeição de pavio a favor da tendência.
    """

    def __init__(
        self,
        strategy_id: str = "STRAT_PULLBACK_TREND",
        target_symbols: Optional[List[str]] = None,
        target_timeframes: Optional[List[TimeFrame]] = None,
        min_rr_ratio: float = 2.0,
        ema_pullback_period: int = 21,
        ema_trend_fast: int = 50,
        ema_trend_slow: int = 200,
        atr_period: int = 14,
    ):
        symbols = target_symbols or ["EURUSD", "GBPUSD"]
        timeframes = target_timeframes or [TimeFrame.M15, TimeFrame.H1]
        super().__init__(
            strategy_id=strategy_id,
            family="pullback",
            target_symbols=symbols,
            target_timeframes=timeframes,
            min_rr_ratio=min_rr_ratio,
        )
        self.ema_pullback_period = ema_pullback_period
        self.ema_trend_fast = ema_trend_fast
        self.ema_trend_slow = ema_trend_slow
        self.atr_period = atr_period

    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        min_bars = self.ema_trend_slow + 10
        if len(bars) < min_bars:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        opens = np.array([b.open for b in bars])

        ema21 = calc_ema(closes, self.ema_pullback_period)
        ema50 = calc_ema(closes, self.ema_trend_fast)
        ema200 = calc_ema(closes, self.ema_trend_slow)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        c = closes[-1]
        h = highs[-1]
        l = lows[-1]
        o = opens[-1]
        e21 = ema21[-1]
        e50 = ema50[-1]
        e200 = ema200[-1]
        curr_atr = atr[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # 1. PULLBACK DE COMPRA (Tendência de Alta: EMA 50 > EMA 200)
        if e50 > e200:
            # Barra testou EMA 21 por baixo e fechou acima
            if l <= e21 and c > e21:
                # Rejeição com pavio inferior significativo: (min(o, c) - l) > 0.4 * (h - l)
                bar_range = max(h - l, 0.0001)
                lower_wick = min(o, c) - l
                if lower_wick / bar_range >= 0.35:
                    entry_price = current_tick.ask if current_tick and current_tick.ask > 0 else c
                    stop_loss = round(l - (curr_atr * 0.5), 5)
                    risk_dist = abs(entry_price - stop_loss)
                    if risk_dist <= 0:
                        return None
                    take_profit = round(entry_price + (risk_dist * self.min_rr_ratio), 5)

                    return self.build_signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        direction=SignalDirection.BUY,
                        confidence=0.75,
                        entry=entry_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        invalidation_level=round(e50, 5),
                        rationale={
                            "trend": "BULLISH_EMA50_ABOVE_EMA200",
                            "pullback_level": round(e21, 5),
                            "lower_wick_ratio": round(lower_wick / bar_range, 2),
                        },
                    )

        # 2. PULLBACK DE VENDA (Tendência de Baixa: EMA 50 < EMA 200)
        if e50 < e200:
            # Barra testou EMA 21 por cima e fechou abaixo
            if h >= e21 and c < e21:
                bar_range = max(h - l, 0.0001)
                upper_wick = h - max(o, c)
                if upper_wick / bar_range >= 0.35:
                    entry_price_sell = current_tick.bid if current_tick and current_tick.bid > 0 else c
                    stop_loss = round(h + (curr_atr * 0.5), 5)
                    risk_dist = abs(stop_loss - entry_price_sell)
                    if risk_dist <= 0:
                        return None
                    take_profit = round(entry_price_sell - (risk_dist * self.min_rr_ratio), 5)

                    return self.build_signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        direction=SignalDirection.SELL,
                        confidence=0.75,
                        entry=entry_price_sell,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        invalidation_level=round(e50, 5),
                        rationale={
                            "trend": "BEARISH_EMA50_BELOW_EMA200",
                            "pullback_level": round(e21, 5),
                            "upper_wick_ratio": round(upper_wick / bar_range, 2),
                        },
                    )

        return None
