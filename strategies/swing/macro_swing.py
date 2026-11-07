"""
QUANT HERMES — Estratégia Macro Swing Multi-Timeframe (H1/H4)
Módulo: strategies.swing.macro_swing
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_adx, calc_atr, calc_ema, calc_rsi
from strategies.base import BaseStrategy


class MacroSwingStrategy(BaseStrategy):
    """
    Estratégia Macro Swing para operações de maior amplitude em H1 e H4.
    Exige confluência tripla de médias móveis de longo prazo (EMA 50, 100, 200),
    filtro de tendência ADX e relação Risco/Retorno assimétrica de 3.0x.
    """

    def __init__(
        self,
        strategy_id: str = "STRAT_SWING_MACRO",
        target_symbols: Optional[List[str]] = None,
        target_timeframes: Optional[List[TimeFrame]] = None,
        min_rr_ratio: float = 3.0,
        ema_fast: int = 50,
        ema_mid: int = 100,
        ema_slow: int = 200,
        atr_period: int = 14,
        adx_min: float = 20.0,
    ):
        symbols = target_symbols or ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
        timeframes = target_timeframes or [TimeFrame.H1, TimeFrame.H4]
        super().__init__(
            strategy_id=strategy_id,
            family="swing",
            target_symbols=symbols,
            target_timeframes=timeframes,
            min_rr_ratio=min_rr_ratio,
        )
        self.ema_fast = ema_fast
        self.ema_mid = ema_mid
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.adx_min = adx_min

    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        min_bars = self.ema_slow + 10
        if len(bars) < min_bars:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        e50 = calc_ema(closes, self.ema_fast)
        e100 = calc_ema(closes, self.ema_mid)
        e200 = calc_ema(closes, self.ema_slow)
        rsi = calc_rsi(closes, 14)
        adx, _, _ = calc_adx(highs, lows, closes, 14)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        c = closes[-1]
        val_e50 = e50[-1]
        val_e100 = e100[-1]
        val_e200 = e200[-1]
        curr_rsi = rsi[-1]
        curr_adx = adx[-1]
        curr_atr = atr[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        if curr_adx < self.adx_min:
            return None

        # 1. SWING DE ALTA: Preço > EMA 50 > EMA 100 > EMA 200
        if c > val_e50 > val_e100 > val_e200 and 52.0 <= curr_rsi <= 68.0:
            entry_price = current_tick.ask if current_tick and current_tick.ask > 0 else c
            stop_loss = round(val_e100, 5)
            risk_dist = abs(entry_price - stop_loss)
            if risk_dist <= 0:
                return None

            take_profit = round(entry_price + (risk_dist * self.min_rr_ratio), 5)
            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.BUY,
                confidence=0.85,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(val_e200, 5),
                rationale={
                    "trend_alignment": "EMA50_100_200_BULLISH",
                    "adx": round(curr_adx, 2),
                    "rsi": round(curr_rsi, 2),
                    "rr_ratio": self.min_rr_ratio,
                },
            )

        # 2. SWING DE BAIXA: Preço < EMA 50 < EMA 100 < EMA 200
        if c < val_e50 < val_e100 < val_e200 and 32.0 <= curr_rsi <= 48.0:
            entry_price_sell = current_tick.bid if current_tick and current_tick.bid > 0 else c
            stop_loss = round(val_e100, 5)
            risk_dist = abs(stop_loss - entry_price_sell)
            if risk_dist <= 0:
                return None

            take_profit = round(entry_price_sell - (risk_dist * self.min_rr_ratio), 5)
            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.SELL,
                confidence=0.85,
                entry=entry_price_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(val_e200, 5),
                rationale={
                    "trend_alignment": "EMA50_100_200_BEARISH",
                    "adx": round(curr_adx, 2),
                    "rsi": round(curr_rsi, 2),
                    "rr_ratio": self.min_rr_ratio,
                },
            )

        return None
