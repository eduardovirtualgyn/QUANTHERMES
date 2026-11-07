"""
QUANT HERMES — Estratégia de Aceleração de Momentum (Momentum Surge)
Módulo: strategies.momentum.momentum_surge
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_adx, calc_atr, calc_ema, calc_macd
from strategies.base import BaseStrategy


class MomentumSurgeStrategy(BaseStrategy):
    """
    Estratégia de Aceleração de Momentum.
    Identifica tendências fortes confirmadas por ADX > 25 e expansão
    direcional do histograma MACD alinhado com inclinação de EMA.
    """

    def __init__(
        self,
        strategy_id: str = "STRAT_MOMENTUM_SURGE",
        target_symbols: Optional[List[str]] = None,
        target_timeframes: Optional[List[TimeFrame]] = None,
        min_rr_ratio: float = 2.0,
        adx_min_threshold: float = 25.0,
        adx_period: int = 14,
        atr_period: int = 14,
        ema_period: int = 20,
    ):
        symbols = target_symbols or ["EURUSD", "USDJPY", "XAUUSD"]
        timeframes = target_timeframes or [TimeFrame.M5, TimeFrame.M15]
        super().__init__(
            strategy_id=strategy_id,
            family="momentum",
            target_symbols=symbols,
            target_timeframes=timeframes,
            min_rr_ratio=min_rr_ratio,
        )
        self.adx_min_threshold = adx_min_threshold
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.ema_period = ema_period

    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        if len(bars) < max(35, self.adx_period, self.ema_period):
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        adx, plus_di, minus_di = calc_adx(highs, lows, closes, self.adx_period)
        _, _, hist = calc_macd(closes, 12, 26, 9)
        ema = calc_ema(closes, self.ema_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        curr_adx = adx[-1]
        curr_pdi = plus_di[-1]
        curr_mdi = minus_di[-1]
        curr_hist = hist[-1]
        prev_hist = hist[-2]
        curr_atr = atr[-1]
        curr_close = closes[-1]
        curr_ema = ema[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Filtro de força direcional (ADX > 25)
        if curr_adx < self.adx_min_threshold:
            return None

        stop_dist = max(curr_atr * 1.5, 0.00015)

        # Configuração de ALTA: +DI > -DI, MACD Hist positivo e crescendo, Preço > EMA
        if curr_pdi > curr_mdi and curr_hist > 0 and curr_hist > prev_hist and curr_close > curr_ema:
            entry_price = current_tick.ask if current_tick and current_tick.ask > 0 else curr_close
            stop_loss = round(entry_price - stop_dist, 5)
            take_profit = round(entry_price + (stop_dist * self.min_rr_ratio), 5)
            confidence = round(min(0.85, 0.60 + (curr_adx / 100.0) * 0.3), 2)

            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.BUY,
                confidence=confidence,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_ema, 5),
                rationale={
                    "adx": round(curr_adx, 2),
                    "plus_di": round(curr_pdi, 2),
                    "minus_di": round(curr_mdi, 2),
                    "macd_hist": round(curr_hist, 6),
                },
            )

        # Configuração de BAIXA: -DI > +DI, MACD Hist negativo e caindo, Preço < EMA
        if curr_mdi > curr_pdi and curr_hist < 0 and curr_hist < prev_hist and curr_close < curr_ema:
            entry_price_sell = current_tick.bid if current_tick and current_tick.bid > 0 else curr_close
            stop_loss = round(entry_price_sell + stop_dist, 5)
            take_profit = round(entry_price_sell - (stop_dist * self.min_rr_ratio), 5)
            confidence = round(min(0.85, 0.60 + (curr_adx / 100.0) * 0.3), 2)

            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.SELL,
                confidence=confidence,
                entry=entry_price_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_ema, 5),
                rationale={
                    "adx": round(curr_adx, 2),
                    "plus_di": round(curr_pdi, 2),
                    "minus_di": round(curr_mdi, 2),
                    "macd_hist": round(curr_hist, 6),
                },
            )

        return None
