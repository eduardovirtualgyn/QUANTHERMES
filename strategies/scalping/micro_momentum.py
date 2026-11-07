"""
QUANT HERMES — Estratégia de Micro-Momentum Scalping (M1/M5)
Módulo: strategies.scalping.micro_momentum
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, calc_ema, calc_rsi
from strategies.base import BaseStrategy


class MicroMomentumScalpingStrategy(BaseStrategy):
    """
    Estratégia de scalping rápido de alta precisão.
    Opera alinhamento de micro-tendência (EMA 9 > EMA 21) e aceleração de RSI
    com stop dinâmico por ATR e alvo proporcional de 1.5x RR.
    """

    def __init__(
        self,
        strategy_id: str = "STRAT_SCALPING_MICRO",
        target_symbols: Optional[List[str]] = None,
        target_timeframes: Optional[List[TimeFrame]] = None,
        min_rr_ratio: float = 1.5,
        ema_fast_period: int = 9,
        ema_slow_period: int = 21,
        rsi_period: int = 14,
        atr_period: int = 14,
        atr_stop_multiplier: float = 1.0,
    ):
        symbols = target_symbols or ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
        timeframes = target_timeframes or [TimeFrame.M1, TimeFrame.M5]
        super().__init__(
            strategy_id=strategy_id,
            family="scalping",
            target_symbols=symbols,
            target_timeframes=timeframes,
            min_rr_ratio=min_rr_ratio,
        )
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier

    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        if len(bars) < max(self.ema_slow_period, self.atr_period) + 5:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        ema_fast = calc_ema(closes, self.ema_fast_period)
        ema_slow = calc_ema(closes, self.ema_slow_period)
        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        curr_close = closes[-1]
        curr_ema_f = ema_fast[-1]
        curr_ema_s = ema_slow[-1]
        curr_rsi = rsi[-1]
        curr_atr = atr[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        entry_price = current_tick.ask if current_tick and current_tick.ask > 0 else curr_close
        stop_dist = max(curr_atr * self.atr_stop_multiplier, 0.00010)

        # Configuração de BUY
        if curr_close > curr_ema_f > curr_ema_s and 52.0 <= curr_rsi <= 68.0:
            stop_loss = round(entry_price - stop_dist, 5)
            take_profit = round(entry_price + (stop_dist * self.min_rr_ratio), 5)
            confidence = round(min(0.85, 0.50 + ((curr_rsi - 50.0) / 100.0) * 1.5), 2)
            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.BUY,
                confidence=confidence,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_ema_s, 5),
                rationale={
                    "ema_fast": round(curr_ema_f, 5),
                    "ema_slow": round(curr_ema_s, 5),
                    "rsi": round(curr_rsi, 2),
                    "atr": round(curr_atr, 5),
                },
            )

        # Configuração de SELL
        entry_price_sell = current_tick.bid if current_tick and current_tick.bid > 0 else curr_close
        if curr_close < curr_ema_f < curr_ema_s and 32.0 <= curr_rsi <= 48.0:
            stop_loss = round(entry_price_sell + stop_dist, 5)
            take_profit = round(entry_price_sell - (stop_dist * self.min_rr_ratio), 5)
            confidence = round(min(0.85, 0.50 + ((50.0 - curr_rsi) / 100.0) * 1.5), 2)
            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.SELL,
                confidence=confidence,
                entry=entry_price_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_ema_s, 5),
                rationale={
                    "ema_fast": round(curr_ema_f, 5),
                    "ema_slow": round(curr_ema_s, 5),
                    "rsi": round(curr_rsi, 2),
                    "atr": round(curr_atr, 5),
                },
            )

        return None
