"""
QUANT HERMES — AG03: MOMENTUM AND BREAKOUT AGENT
Módulo: intelligence.agents.ag03_momentum
"""
from __future__ import annotations

import numpy as np
from typing import Any, Dict, List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, calc_bollinger_bands, calc_donchian
from intelligence.agents.base import BaseIntelligenceAgent


class MomentumBreakoutAgent(BaseIntelligenceAgent):
    """
    AG03 — MOMENTUM AND BREAKOUT
    Responsabilidade:
    - Identificação de compressão de volatilidade (Bollinger Squeeze).
    - Detecção de aceleração e expansão de range.
    - Validação de rompimentos direcionais com canais Donchian.
    - Rejeição de rompimentos falsos através de expansão de ATR.
    """

    def __init__(
        self,
        agent_id: str = "AG03_MOMENTUM",
        quality_factor: float = 0.82,
        expansion_factor: float = 1.3,
    ):
        super().__init__(
            agent_id=agent_id,
            name="Momentum and Breakout Agent",
            quality_factor=quality_factor,
        )
        self.expansion_factor = expansion_factor

    def analyze(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick: Optional[MarketTick] = None,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentSignal]:
        tf = TimeFrame.M5 if TimeFrame.M5 in bars_multi_tf else TimeFrame.M15
        bars = bars_multi_tf.get(tf)
        if not bars or len(bars) < 30:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        upper_bb, mid_bb, lower_bb = calc_bollinger_bands(closes, 20, 2.0)
        upper_dc, _, lower_dc = calc_donchian(highs, lows, 20)
        atr = calc_atr(highs, lows, closes, 14)

        c = closes[-1]
        h = highs[-1]
        l = lows[-1]
        curr_atr = atr[-1]
        bar_range = h - l

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Exige expansão significativa de range na barra atual
        if bar_range < (curr_atr * self.expansion_factor):
            return None

        # 1. Rompimento de ALTA
        if c > upper_bb[-1] and c >= upper_dc[-2]:
            entry = current_tick.ask if current_tick and current_tick.ask > 0 else c
            stop_loss = round(mid_bb[-1], 5)
            risk_dist = abs(entry - stop_loss)
            if risk_dist <= 0:
                return None
            take_profit = round(entry + (risk_dist * 2.0), 5)

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.BUY,
                confidence=0.80,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(mid_bb[-1], 5),
                rationale={
                    "breakout": "BOLLINGER_EXPANSION_BULLISH",
                    "bar_range": round(bar_range, 5),
                    "atr": round(curr_atr, 5),
                },
            )

        # 2. Rompimento de BAIXA
        if c < lower_bb[-1] and c <= lower_dc[-2]:
            entry_sell = current_tick.bid if current_tick and current_tick.bid > 0 else c
            stop_loss = round(mid_bb[-1], 5)
            risk_dist = abs(stop_loss - entry_sell)
            if risk_dist <= 0:
                return None
            take_profit = round(entry_sell - (risk_dist * 2.0), 5)

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.SELL,
                confidence=0.80,
                entry=entry_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(mid_bb[-1], 5),
                rationale={
                    "breakout": "BOLLINGER_EXPANSION_BEARISH",
                    "bar_range": round(bar_range, 5),
                    "atr": round(curr_atr, 5),
                },
            )

        return None

