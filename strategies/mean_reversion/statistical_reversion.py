"""
QUANT HERMES — Estratégia Estatística de Reversão à Média (Mean Reversion)
Módulo: strategies.mean_reversion.statistical_reversion
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_adx, calc_atr, calc_rsi, calc_sma, calc_zscore
from strategies.base import BaseStrategy


class StatisticalMeanReversionStrategy(BaseStrategy):
    """
    Estratégia Estatística de Reversão à Média.
    Opera estritamente em mercados laterais e não-tendenciais (ADX < 25),
    identificando desvios extremos padronizados (Z-Score >= 2.2) com exaustão de RSI.
    """

    def __init__(
        self,
        strategy_id: str = "STRAT_MEAN_REVERSION_STAT",
        target_symbols: Optional[List[str]] = None,
        target_timeframes: Optional[List[TimeFrame]] = None,
        min_rr_ratio: float = 1.8,
        z_score_threshold: float = 2.2,
        max_trend_adx: float = 25.0,
        period: int = 20,
        rsi_period: int = 14,
        atr_period: int = 14,
    ):
        symbols = target_symbols or ["EURUSD", "USDJPY"]
        timeframes = target_timeframes or [TimeFrame.M5, TimeFrame.M15]
        super().__init__(
            strategy_id=strategy_id,
            family="mean_reversion",
            target_symbols=symbols,
            target_timeframes=timeframes,
            min_rr_ratio=min_rr_ratio,
        )
        self.z_score_threshold = z_score_threshold
        self.max_trend_adx = max_trend_adx
        self.period = period
        self.rsi_period = rsi_period
        self.atr_period = atr_period

    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        min_bars = max(self.period, self.rsi_period, self.atr_period) + 10
        if len(bars) < min_bars:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        adx, _, _ = calc_adx(highs, lows, closes, 14)
        zscore = calc_zscore(closes, self.period)
        sma = calc_sma(closes, self.period)
        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        curr_adx = adx[-1]
        curr_z = zscore[-1]
        curr_sma = sma[-1]
        curr_rsi = rsi[-1]
        curr_atr = atr[-1]
        curr_close = closes[-1]

        if np.isnan(curr_atr) or curr_atr <= 0 or np.isnan(curr_sma):
            return None

        # REGRA FUNDAMENTAL: Não opera reversão à média em tendências fortes (ADX >= 25)
        if curr_adx >= self.max_trend_adx:
            return None

        # 1. SOBREVENDA EXTREMA (Z-Score <= -2.2 e RSI <= 30) -> BUY
        if curr_z <= -self.z_score_threshold and curr_rsi <= 32.0:
            entry_price = current_tick.ask if current_tick and current_tick.ask > 0 else curr_close
            target_mean = curr_sma
            reward_dist = target_mean - entry_price
            if reward_dist <= 0:
                return None

            # Stop loss definido para garantir pelo menos min_rr_ratio
            stop_dist = max(reward_dist / self.min_rr_ratio, curr_atr * 1.0)
            stop_loss = round(entry_price - stop_dist, 5)
            take_profit = round(target_mean, 5)

            # Recalcula RR
            risk_dist = abs(entry_price - stop_loss)
            if risk_dist <= 0 or (reward_dist / risk_dist) < self.min_rr_ratio:
                return None

            confidence = round(min(0.85, 0.60 + (abs(curr_z) / 5.0) * 0.3), 2)
            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.BUY,
                confidence=confidence,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(stop_loss - (curr_atr * 0.5), 5),
                rationale={
                    "z_score": round(curr_z, 2),
                    "rsi": round(curr_rsi, 2),
                    "adx": round(curr_adx, 2),
                    "target_mean": round(target_mean, 5),
                },
            )

        # 2. SOBRECOMPRA EXTREMA (Z-Score >= +2.2 e RSI >= 70) -> SELL
        if curr_z >= self.z_score_threshold and curr_rsi >= 68.0:
            entry_price_sell = current_tick.bid if current_tick and current_tick.bid > 0 else curr_close
            target_mean = curr_sma
            reward_dist = entry_price_sell - target_mean
            if reward_dist <= 0:
                return None

            stop_dist = max(reward_dist / self.min_rr_ratio, curr_atr * 1.0)
            stop_loss = round(entry_price_sell + stop_dist, 5)
            take_profit = round(target_mean, 5)

            risk_dist = abs(stop_loss - entry_price_sell)
            if risk_dist <= 0 or (reward_dist / risk_dist) < self.min_rr_ratio:
                return None

            confidence = round(min(0.85, 0.60 + (abs(curr_z) / 5.0) * 0.3), 2)
            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.SELL,
                confidence=confidence,
                entry=entry_price_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(stop_loss + (curr_atr * 0.5), 5),
                rationale={
                    "z_score": round(curr_z, 2),
                    "rsi": round(curr_rsi, 2),
                    "adx": round(curr_adx, 2),
                    "target_mean": round(target_mean, 5),
                },
            )

        return None
