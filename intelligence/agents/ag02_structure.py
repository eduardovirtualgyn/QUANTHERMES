"""
QUANT HERMES — AG02: MARKET STRUCTURE INTELLIGENCE AGENT
Módulo: intelligence.agents.ag02_structure
"""
from __future__ import annotations

import numpy as np
from typing import Any, Dict, List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, detect_bos_choch, detect_swings
from intelligence.agents.base import BaseIntelligenceAgent


class MarketStructureAgent(BaseIntelligenceAgent):
    """
    AG02 — MARKET STRUCTURE INTELLIGENCE
    Responsabilidade:
    - Mapeamento determinístico de estrutura de mercado.
    - Identificação objetiva de Quebra de Estrutura (BOS) e Mudança de Caráter (CHoCH).
    - Detecção de varreduras de liquidez (Liquidity Sweeps).
    - Definição de zonas de oferta e demanda fractais.
    """

    def __init__(
        self,
        agent_id: str = "AG02_STRUCTURE",
        quality_factor: float = 0.85,
        left_bars: int = 3,
        right_bars: int = 3,
    ):
        super().__init__(
            agent_id=agent_id,
            name="Market Structure Intelligence Agent",
            quality_factor=quality_factor,
        )
        self.left_bars = left_bars
        self.right_bars = right_bars

    def analyze(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick: Optional[MarketTick] = None,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentSignal]:
        tf = TimeFrame.M15 if TimeFrame.M15 in bars_multi_tf else TimeFrame.M5
        bars = bars_multi_tf.get(tf)
        if not bars or len(bars) < 30:
            return None

        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        closes = np.array([b.close for b in bars])

        atr = calc_atr(highs, lows, closes, 14)
        curr_atr = atr[-1]
        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        events = detect_bos_choch(highs, lows, closes, self.left_bars, self.right_bars)
        if not events:
            return None

        latest_event = events[-1]
        distance = (len(bars) - 1) - latest_event["bar_index"]
        if distance > 3:  # Evento muito distante no passado
            return None

        event_type = latest_event["type"]
        broken_level = latest_event["broken_level"]
        curr_close = closes[-1]

        # 1. Estrutura Bullish confirmada
        if "BULLISH" in event_type and curr_close > broken_level:
            entry = current_tick.ask if current_tick and current_tick.ask > 0 else curr_close
            stop_loss = round(broken_level - (curr_atr * 0.8), 5)
            risk_dist = abs(entry - stop_loss)
            if risk_dist <= 0:
                return None
            take_profit = round(entry + (risk_dist * 2.5), 5)
            confidence = 0.85 if "CHOCH" in event_type else 0.78

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.BUY,
                confidence=confidence,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(broken_level - curr_atr, 5),
                rationale={
                    "structure_event": event_type,
                    "broken_level": round(broken_level, 5),
                    "bars_ago": distance,
                    "market_structure": "BULLISH_EXPANSION",
                },
            )

        # 2. Estrutura Bearish confirmada
        if "BEARISH" in event_type and curr_close < broken_level:
            entry_sell = current_tick.bid if current_tick and current_tick.bid > 0 else curr_close
            stop_loss = round(broken_level + (curr_atr * 0.8), 5)
            risk_dist = abs(stop_loss - entry_sell)
            if risk_dist <= 0:
                return None
            take_profit = round(entry_sell - (risk_dist * 2.5), 5)
            confidence = 0.85 if "CHOCH" in event_type else 0.78

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.SELL,
                confidence=confidence,
                entry=entry_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(broken_level + curr_atr, 5),
                rationale={
                    "structure_event": event_type,
                    "broken_level": round(broken_level, 5),
                    "bars_ago": distance,
                    "market_structure": "BEARISH_EXPANSION",
                },
            )

        return None

