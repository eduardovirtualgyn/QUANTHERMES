"""
QUANT HERMES — AG04: MEAN REVERSION AGENT
Módulo: intelligence.agents.ag04_mean_reversion
"""
from __future__ import annotations

import numpy as np
from typing import Any, Dict, List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_adx, calc_atr, calc_rsi, calc_sma, calc_zscore
from intelligence.agents.base import BaseIntelligenceAgent


class MeanReversionAgent(BaseIntelligenceAgent):
    """
    AG04 — MEAN REVERSION
    Responsabilidade:
    - Identificação de regimes laterais não-tendenciais.
    - Cálculo de desvios estatísticos extremos (Z-Scores).
    - Detecção de condições de sobre-extensão e exaustão com retorno à média.
    - VETO ESTRITO: Bloqueia recomendações se ADX >= 25 (mercado em forte tendência).
    """

    def __init__(
        self,
        agent_id: str = "AG04_MEAN_REVERSION",
        quality_factor: float = 0.84,
        z_score_threshold: float = 2.0,
        max_adx: float = 25.0,
    ):
        super().__init__(
            agent_id=agent_id,
            name="Mean Reversion Agent",
            quality_factor=quality_factor,
        )
        self.z_score_threshold = z_score_threshold
        self.max_adx = max_adx

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

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        adx, _, _ = calc_adx(highs, lows, closes, 14)
        zscore = calc_zscore(closes, 20)
        sma = calc_sma(closes, 20)
        rsi = calc_rsi(closes, 14)
        atr = calc_atr(highs, lows, closes, 14)

        curr_adx = adx[-1]
        curr_z = zscore[-1]
        curr_sma = sma[-1]
        curr_rsi = rsi[-1]
        curr_atr = atr[-1]
        curr_close = closes[-1]

        if np.isnan(curr_atr) or curr_atr <= 0 or np.isnan(curr_sma):
            return None

        # VETO: Proibição estrita de operar contra tendências fortes
        if curr_adx >= self.max_adx:
            return None

        # 1. SOBREVENDA (Z <= -2.0 e RSI <= 32) -> BUY visando retorno à média
        if curr_z <= -self.z_score_threshold and curr_rsi <= 32.0:
            entry = current_tick.ask if current_tick and current_tick.ask > 0 else curr_close
            target = curr_sma
            reward_dist = target - entry
            if reward_dist <= 0:
                return None

            stop_dist = max(reward_dist / 1.8, curr_atr * 1.0)
            stop_loss = round(entry - stop_dist, 5)
            take_profit = round(target, 5)

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.BUY,
                confidence=round(min(0.85, 0.60 + (abs(curr_z) / 4.0) * 0.25), 2),
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(stop_loss - (curr_atr * 0.5), 5),
                rationale={
                    "z_score": round(curr_z, 2),
                    "rsi": round(curr_rsi, 2),
                    "adx": round(curr_adx, 2),
                    "target_mean": round(target, 5),
                },
            )

        # 2. SOBRECOMPRA (Z >= +2.0 e RSI >= 68) -> SELL visando retorno à média
        if curr_z >= self.z_score_threshold and curr_rsi >= 68.0:
            entry_sell = current_tick.bid if current_tick and current_tick.bid > 0 else curr_close
            target = curr_sma
            reward_dist = entry_sell - target
            if reward_dist <= 0:
                return None

            stop_dist = max(reward_dist / 1.8, curr_atr * 1.0)
            stop_loss = round(entry_sell + stop_dist, 5)
            take_profit = round(target, 5)

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.SELL,
                confidence=round(min(0.85, 0.60 + (abs(curr_z) / 4.0) * 0.25), 2),
                entry=entry_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(stop_loss + (curr_atr * 0.5), 5),
                rationale={
                    "z_score": round(curr_z, 2),
                    "rsi": round(curr_rsi, 2),
                    "adx": round(curr_adx, 2),
                    "target_mean": round(target, 5),
                },
            )

        return None

