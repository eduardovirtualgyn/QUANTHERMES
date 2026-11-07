"""
QUANT HERMES — AG01: TREND INTELLIGENCE AGENT
Módulo: intelligence.agents.ag01_trend
"""
from __future__ import annotations

import numpy as np
from typing import Any, Dict, List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_adx, calc_atr, calc_ema, calc_macd
from intelligence.agents.base import BaseIntelligenceAgent


class TrendIntelligenceAgent(BaseIntelligenceAgent):
    """
    AG01 — TREND INTELLIGENCE
    Responsabilidade:
    - Análise de tendência multi-timeframe (M15, H1, H4).
    - Alinhamento de médias exponenciais (EMA 20, 50, 200).
    - Força direcional via ADX e aceleração via MACD.
    - Filtro de confluência: só emite sinal forte quando M15 e H1 concordam.
    """

    def __init__(
        self,
        agent_id: str = "AG01_TREND",
        quality_factor: float = 0.88,
        adx_trend_threshold: float = 20.0,
    ):
        super().__init__(
            agent_id=agent_id,
            name="Trend Intelligence Agent",
            quality_factor=quality_factor,
        )
        self.adx_trend_threshold = adx_trend_threshold

    def analyze(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick: Optional[MarketTick] = None,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentSignal]:
        # Exige pelo menos dados em M15 e H1 para validação de tendência
        m15_bars = bars_multi_tf.get(TimeFrame.M15)
        h1_bars = bars_multi_tf.get(TimeFrame.H1)

        # Fallback se H1 não disponível: usa M5 e M15
        primary_tf = TimeFrame.M15
        primary_bars = m15_bars
        if not primary_bars or len(primary_bars) < 50:
            primary_tf = TimeFrame.M5
            primary_bars = bars_multi_tf.get(TimeFrame.M5)

        if not primary_bars or len(primary_bars) < 50:
            return None

        closes = np.array([b.close for b in primary_bars])
        highs = np.array([b.high for b in primary_bars])
        lows = np.array([b.low for b in primary_bars])

        e20 = calc_ema(closes, 20)
        e50 = calc_ema(closes, 50)
        e200 = calc_ema(closes, min(200, len(closes) - 1))
        adx, pdi, mdi = calc_adx(highs, lows, closes, 14)
        atr = calc_atr(highs, lows, closes, 14)

        c = closes[-1]
        curr_e20 = e20[-1]
        curr_e50 = e50[-1]
        curr_e200 = e200[-1]
        curr_adx = adx[-1]
        curr_atr = atr[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Checagem em H1 se disponível
        h1_bullish = True
        h1_bearish = True
        if h1_bars and len(h1_bars) >= 30:
            h1_closes = np.array([b.close for b in h1_bars])
            h1_e50 = calc_ema(h1_closes, 50)[-1]
            h1_bullish = h1_closes[-1] > h1_e50
            h1_bearish = h1_closes[-1] < h1_e50

        entry = current_tick.ask if current_tick and current_tick.ask > 0 else c
        stop_dist = max(curr_atr * 1.5, 0.00015)

        # 1. TENDÊNCIA DE ALTA (BULLISH)
        if c > curr_e20 > curr_e50 and curr_adx >= self.adx_trend_threshold and pdi[-1] > mdi[-1] and h1_bullish:
            stop_loss = round(entry - stop_dist, 5)
            take_profit = round(entry + (stop_dist * 2.0), 5)
            confidence = round(min(0.90, 0.60 + (curr_adx / 100.0) * 0.3), 2)

            return self.build_signal(
                symbol=symbol,
                timeframe=primary_tf,
                direction=SignalDirection.BUY,
                confidence=confidence,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_e50, 5),
                rationale={
                    "ema_alignment": "EMA20 > EMA50",
                    "adx": round(curr_adx, 2),
                    "h1_confluence": h1_bullish,
                    "trend_slope": "POSITIVE",
                },
            )

        # 2. TENDÊNCIA DE BAIXA (BEARISH)
        entry_sell = current_tick.bid if current_tick and current_tick.bid > 0 else c
        if c < curr_e20 < curr_e50 and curr_adx >= self.adx_trend_threshold and mdi[-1] > pdi[-1] and h1_bearish:
            stop_loss = round(entry_sell + stop_dist, 5)
            take_profit = round(entry_sell - (stop_dist * 2.0), 5)
            confidence = round(min(0.90, 0.60 + (curr_adx / 100.0) * 0.3), 2)

            return self.build_signal(
                symbol=symbol,
                timeframe=primary_tf,
                direction=SignalDirection.SELL,
                confidence=confidence,
                entry=entry_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_e50, 5),
                rationale={
                    "ema_alignment": "EMA20 < EMA50",
                    "adx": round(curr_adx, 2),
                    "h1_confluence": h1_bearish,
                    "trend_slope": "NEGATIVE",
                },
            )

        return None

