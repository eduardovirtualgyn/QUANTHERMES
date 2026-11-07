"""
QUANT HERMES — AG05: GOLD AND MACRO INTELLIGENCE AGENT
Módulo: intelligence.agents.ag05_gold_macro
"""
from __future__ import annotations

import numpy as np
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, calc_ema, calc_rsi
from intelligence.agents.base import BaseIntelligenceAgent


class GoldMacroAgent(BaseIntelligenceAgent):
    """
    AG05 — GOLD AND MACRO INTELLIGENCE
    Responsabilidade:
    - Especialização quantitativa profunda no comportamento do Ouro (XAUUSD).
    - Análise de correlação com Dólar DXY e taxas de juros americanas.
    - Filtro e bloqueio estrito em janelas de notícias macroeconômicas de alto impacto
      (CPI, NFP, FOMC — blackout window de 15 minutos antes e depois).
    - Sensibilidade a movimentos assimétricos de fuga para refúgio seguro (*Safe Haven*).
    """

    def __init__(
        self,
        agent_id: str = "AG05_GOLD_MACRO",
        quality_factor: float = 0.86,
        news_blackout_minutes: int = 15,
    ):
        super().__init__(
            agent_id=agent_id,
            name="Gold and Macro Intelligence Agent",
            quality_factor=quality_factor,
        )
        self.news_blackout_minutes = news_blackout_minutes

    def is_news_blackout_active(self, current_time: datetime, macro_context: Optional[Dict[str, Any]]) -> bool:
        """
        Verifica se há evento macroeconômico de alto impacto dentro da janela de blackout.
        """
        if not macro_context or "upcoming_news" not in macro_context:
            return False

        for event in macro_context.get("upcoming_news", []):
            impact = event.get("impact", "").upper()
            event_time = event.get("time")
            if impact in ("HIGH", "CRITICAL") and event_time:
                diff_minutes = abs((current_time - event_time).total_seconds()) / 60.0
                if diff_minutes <= self.news_blackout_minutes:
                    return True
        return False

    def analyze(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick: Optional[MarketTick] = None,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentSignal]:
        if current_tick:
            now = current_tick.time
        elif bars_multi_tf:
            any_bars = next(iter(bars_multi_tf.values()), [])
            now = any_bars[-1].time if any_bars else datetime.now(timezone.utc)
        else:
            now = datetime.now(timezone.utc)

        # 1. Filtro Soberano de Blackout de Notícias
        if self.is_news_blackout_active(now, macro_context):
            # Retorna sinal explícito de HOLD durante divulgação de alto impacto
            return self.build_signal(
                symbol=symbol,
                timeframe=TimeFrame.M15,
                direction=SignalDirection.HOLD,
                confidence=1.0,
                entry=1.0,
                stop_loss=0.9,
                take_profit=1.1,
                invalidation_level=1.0,
                rationale={"news_blackout_active": True, "reason": "HIGH_IMPACT_NEWS_WINDOW"},
            )

        # Análise especializada para XAUUSD (ou pares dolarizados)
        is_gold = "XAU" in symbol.upper() or "GOLD" in symbol.upper()

        tf = TimeFrame.M15 if TimeFrame.M15 in bars_multi_tf else TimeFrame.H1
        bars = bars_multi_tf.get(tf)
        if not bars or len(bars) < 30:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        e21 = calc_ema(closes, 21)
        e55 = calc_ema(closes, 55)
        rsi = calc_rsi(closes, 14)
        atr = calc_atr(highs, lows, closes, 14)

        c = closes[-1]
        curr_e21 = e21[-1]
        curr_e55 = e55[-1]
        curr_rsi = rsi[-1]
        curr_atr = atr[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Contexto Macro: sentimento DXY (Dólar forte prejudica Ouro; Dólar fraco favorece Ouro)
        dxy_bias = macro_context.get("dxy_trend", "NEUTRAL") if macro_context else "NEUTRAL"

        stop_dist = max(curr_atr * (1.8 if is_gold else 1.5), 0.00020)

        # Ouro em alta: EMA21 > EMA55 e Dólar fraco ou neutro
        if c > curr_e21 > curr_e55 and 52.0 <= curr_rsi <= 70.0 and dxy_bias in ("BEARISH", "NEUTRAL"):
            entry = current_tick.ask if current_tick and current_tick.ask > 0 else c
            stop_loss = round(entry - stop_dist, 2 if is_gold else 5)
            take_profit = round(entry + (stop_dist * 2.2), 2 if is_gold else 5)
            confidence = 0.85 if is_gold else 0.75

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.BUY,
                confidence=confidence,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_e55, 2 if is_gold else 5),
                rationale={
                    "asset": "GOLD" if is_gold else symbol,
                    "dxy_bias": dxy_bias,
                    "gold_momentum": "BULLISH",
                    "atr": round(curr_atr, 2 if is_gold else 5),
                },
            )

        # Ouro em baixa: EMA21 < EMA55 e Dólar forte ou neutro
        if c < curr_e21 < curr_e55 and 30.0 <= curr_rsi <= 48.0 and dxy_bias in ("BULLISH", "NEUTRAL"):
            entry_sell = current_tick.bid if current_tick and current_tick.bid > 0 else c
            stop_loss = round(entry_sell + stop_dist, 2 if is_gold else 5)
            take_profit = round(entry_sell - (stop_dist * 2.2), 2 if is_gold else 5)
            confidence = 0.85 if is_gold else 0.75

            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.SELL,
                confidence=confidence,
                entry=entry_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(curr_e55, 2 if is_gold else 5),
                rationale={
                    "asset": "GOLD" if is_gold else symbol,
                    "dxy_bias": dxy_bias,
                    "gold_momentum": "BEARISH",
                    "atr": round(curr_atr, 2 if is_gold else 5),
                },
            )

        return None
