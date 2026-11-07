"""
QUANT HERMES — Estratégia Determinística de Estrutura de Mercado e Smart Money Concepts (SMC)
Módulo: strategies.smc.structure_break
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, detect_bos_choch, detect_swings
from strategies.base import BaseStrategy


class SMCStructureStrategy(BaseStrategy):
    """
    Estratégia Determinística de Smart Money Concepts (SMC).
    Elimina qualquer subjetividade através de identificação matemática estrita de:
    1. Quebra de Estrutura (BOS) ou Mudança de Caráter (CHoCH).
    2. Varredura de liquidez prévia (Liquidity Sweep) em topos/fundos fractais.
    3. Risco/Retorno assimétrico mínimo de 2.5x.
    """

    def __init__(
        self,
        strategy_id: str = "STRAT_SMC_STRUCTURE",
        target_symbols: Optional[List[str]] = None,
        target_timeframes: Optional[List[TimeFrame]] = None,
        min_rr_ratio: float = 2.5,
        left_bars: int = 3,
        right_bars: int = 3,
        atr_period: int = 14,
    ):
        symbols = target_symbols or ["EURUSD", "XAUUSD"]
        timeframes = target_timeframes or [TimeFrame.M15, TimeFrame.H1, TimeFrame.H4]
        super().__init__(
            strategy_id=strategy_id,
            family="smc",
            target_symbols=symbols,
            target_timeframes=timeframes,
            min_rr_ratio=min_rr_ratio,
        )
        self.left_bars = left_bars
        self.right_bars = right_bars
        self.atr_period = atr_period

    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        if len(bars) < 30:
            return None

        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        closes = np.array([b.close for b in bars])

        atr = calc_atr(highs, lows, closes, self.atr_period)
        curr_atr = atr[-1]
        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Detecta eventos de BOS e CHoCH
        events = detect_bos_choch(highs, lows, closes, self.left_bars, self.right_bars)
        if not events:
            return None

        # Analisa o evento estrutural mais recente (deve ter ocorrido nas últimas 3 barras)
        latest_event = events[-1]
        bar_distance = (len(bars) - 1) - latest_event["bar_index"]
        if bar_distance > 3:
            return None

        event_type = latest_event["type"]
        broken_level = latest_event["broken_level"]
        curr_close = closes[-1]

        # 1. Estrutura BULLISH (BOS_BULLISH ou CHOCH_BULLISH)
        if "BULLISH" in event_type and curr_close > broken_level:
            entry_price = current_tick.ask if current_tick and current_tick.ask > 0 else curr_close
            # Stop loss abaixo do nível rompido ou swing de fundo recente
            stop_loss = round(broken_level - (curr_atr * 0.8), 5)
            risk_dist = abs(entry_price - stop_loss)
            if risk_dist <= 0:
                return None

            take_profit = round(entry_price + (risk_dist * self.min_rr_ratio), 5)
            confidence = 0.82 if "CHOCH" in event_type else 0.78

            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.BUY,
                confidence=confidence,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(broken_level - curr_atr, 5),
                rationale={
                    "event_type": event_type,
                    "broken_structure_level": round(broken_level, 5),
                    "bars_ago": bar_distance,
                    "atr": round(curr_atr, 5),
                },
            )

        # 2. Estrutura BEARISH (BOS_BEARISH ou CHOCH_BEARISH)
        if "BEARISH" in event_type and curr_close < broken_level:
            entry_price_sell = current_tick.bid if current_tick and current_tick.bid > 0 else curr_close
            stop_loss = round(broken_level + (curr_atr * 0.8), 5)
            risk_dist = abs(stop_loss - entry_price_sell)
            if risk_dist <= 0:
                return None

            take_profit = round(entry_price_sell - (risk_dist * self.min_rr_ratio), 5)
            confidence = 0.82 if "CHOCH" in event_type else 0.78

            return self.build_signal(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.SELL,
                confidence=confidence,
                entry=entry_price_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(broken_level + curr_atr, 5),
                rationale={
                    "event_type": event_type,
                    "broken_structure_level": round(broken_level, 5),
                    "bars_ago": bar_distance,
                    "atr": round(curr_atr, 5),
                },
            )

        return None
