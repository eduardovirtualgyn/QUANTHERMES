"""
QUANT HERMES — AG06: QUANTITATIVE INTELLIGENCE AGENT
Módulo: intelligence.agents.ag06_quantitative
"""
from __future__ import annotations

import numpy as np
from typing import Any, Dict, List, Optional

from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from core.models.regime import MarketRegimeType, RegimeClassification
from data.features.indicators import calc_adx, calc_atr, calc_ema, calc_zscore
from intelligence.agents.base import BaseIntelligenceAgent


class QuantitativeAgent(BaseIntelligenceAgent):
    """
    AG06 — QUANTITATIVE INTELLIGENCE
    Responsabilidade:
    - Detecção estocástica e paramétrica de regimes de mercado via HMM / métricas quantitativas.
    - Cálculo da distribuição de probabilidades a posteriori dos estados de mercado.
    - Mensuração da incerteza via Entropia de Shannon.
    - Emissão de sinais probabilísticos baseados no regime prevalecente.
    """

    def __init__(
        self,
        agent_id: str = "AG06_QUANT",
        quality_factor: float = 0.90,
        entropy_uncertainty_threshold: float = 0.80,
    ):
        super().__init__(
            agent_id=agent_id,
            name="Quantitative Intelligence Agent",
            quality_factor=quality_factor,
        )
        self.entropy_uncertainty_threshold = entropy_uncertainty_threshold

    def classify_regime(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: str = "M15",
    ) -> RegimeClassification:
        """
        Classifica o regime de mercado atual com base em retornos, volatilidade realizada e ADX.
        Retorna RegimeClassification completo com distribuição de probabilidades e entropia.
        """
        if len(bars) < 30:
            return RegimeClassification(
                symbol=symbol,
                timeframe=timeframe,
                active_regime=MarketRegimeType.UNCERTAIN_TRANSITION,
                probabilities={r.value: 0.20 for r in MarketRegimeType},
                confidence=0.20,
                entropy=1.0,
                is_uncertain=True,
            )

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])

        returns = np.diff(closes) / closes[:-1]
        realized_vol = np.std(returns[-20:]) if len(returns) >= 20 else 0.001
        mean_return = np.mean(returns[-20:]) if len(returns) >= 20 else 0.0

        adx, pdi, mdi = calc_adx(highs, lows, closes, 14)
        curr_adx = adx[-1] if not np.isnan(adx[-1]) else 15.0

        atr = calc_atr(highs, lows, closes, 14)
        atr_ratio = (atr[-1] / np.mean(atr[-20:])) if len(atr) >= 20 and np.mean(atr[-20:]) > 0 else 1.0

        # Pontuações dos regimes baseadas nas features quantitativas
        scores: Dict[MarketRegimeType, float] = {
            MarketRegimeType.TREND_BULL_STRONG: 0.1,
            MarketRegimeType.TREND_BEAR_STRONG: 0.1,
            MarketRegimeType.RANGING_LOW_VOL: 0.1,
            MarketRegimeType.EXPANSION_HIGH_VOL: 0.1,
            MarketRegimeType.UNCERTAIN_TRANSITION: 0.1,
        }

        # Lógica de pesos dos regimes
        if curr_adx >= 25.0 and pdi[-1] > mdi[-1] and mean_return > 0:
            scores[MarketRegimeType.TREND_BULL_STRONG] += 0.6 + min(0.3, curr_adx / 100.0)
        elif curr_adx >= 25.0 and mdi[-1] > pdi[-1] and mean_return < 0:
            scores[MarketRegimeType.TREND_BEAR_STRONG] += 0.6 + min(0.3, curr_adx / 100.0)
        elif curr_adx < 20.0 and atr_ratio <= 1.1:
            scores[MarketRegimeType.RANGING_LOW_VOL] += 0.7
        elif atr_ratio >= 1.5 or realized_vol >= 0.002:
            scores[MarketRegimeType.EXPANSION_HIGH_VOL] += 0.7
        else:
            scores[MarketRegimeType.UNCERTAIN_TRANSITION] += 0.5

        # Normaliza pontuações via Softmax para obter probabilidades
        exp_scores = np.exp(list(scores.values()))
        probs = exp_scores / np.sum(exp_scores)
        prob_dict = {regime.value: round(float(p), 4) for regime, p in zip(scores.keys(), probs)}

        # Calcula Entropia de Shannon normalizada: H = -sum(p * log(p)) / log(N)
        non_zero_p = probs[probs > 1e-9]
        raw_entropy = -np.sum(non_zero_p * np.log(non_zero_p))
        normalized_entropy = round(float(raw_entropy / np.log(len(scores))), 4)

        # Seleciona regime de maior probabilidade
        max_idx = np.argmax(probs)
        active_regime = list(scores.keys())[max_idx]
        confidence = round(float(probs[max_idx]), 4)
        is_uncertain = normalized_entropy >= self.entropy_uncertainty_threshold

        return RegimeClassification(
            symbol=symbol,
            timeframe=timeframe,
            active_regime=active_regime,
            probabilities=prob_dict,
            confidence=confidence,
            entropy=normalized_entropy,
            is_uncertain=is_uncertain,
        )

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

        classification = self.classify_regime(bars, symbol, tf.value)

        # Se houver alta incerteza estocástica, recomenda neutralidade (HOLD)
        if classification.is_uncertain:
            return None

        closes = np.array([b.close for b in bars])
        atr = calc_atr(np.array([b.high for b in bars]), np.array([b.low for b in bars]), closes, 14)
        curr_atr = atr[-1]
        c = closes[-1]

        entry = current_tick.ask if current_tick and current_tick.ask > 0 else c
        stop_dist = max(curr_atr * 1.5, 0.00015)

        if classification.active_regime == MarketRegimeType.TREND_BULL_STRONG:
            stop_loss = round(entry - stop_dist, 5)
            take_profit = round(entry + (stop_dist * 2.0), 5)
            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.BUY,
                confidence=classification.confidence,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(entry - (stop_dist * 1.2), 5),
                rationale={
                    "regime": classification.active_regime.value,
                    "entropy": classification.entropy,
                    "probabilities": classification.probabilities,
                },
            )

        if classification.active_regime == MarketRegimeType.TREND_BEAR_STRONG:
            entry_sell = current_tick.bid if current_tick and current_tick.bid > 0 else c
            stop_loss = round(entry_sell + stop_dist, 5)
            take_profit = round(entry_sell - (stop_dist * 2.0), 5)
            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.SELL,
                confidence=classification.confidence,
                entry=entry_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(entry_sell + (stop_dist * 1.2), 5),
                rationale={
                    "regime": classification.active_regime.value,
                    "entropy": classification.entropy,
                    "probabilities": classification.probabilities,
                },
            )

        return None
