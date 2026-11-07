"""
QUANT HERMES — Motor Central de Consenso Ponderado (Consensus Engine / AG08)
Módulo: intelligence.consensus.engine
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4
import numpy as np

from core.logger import get_logger
from core.models.agent import AgentSignal, ConsensusDecision, SignalDirection
from core.models.base import utc_now
from core.models.regime import MarketRegimeType
from intelligence.agents.ag07_adversarial import AdversarialDebateResult
from intelligence.calibration.platt_scaler import PlattScaler
from intelligence.consensus.weights import DEFAULT_QUALITY_FACTORS, REGIME_AGENT_WEIGHTS

logger = get_logger("intelligence.consensus.engine")


class ConsensusEngine:
    """
    AG08 — PORTFOLIO INTELLIGENCE / MOTOR DE CONSENSO PONDERADO
    Princípio:
        Não adota votação majoritária simples. A decisão é governada pela
        equação de pontuação composta:
            Composite Score = Σ ( w_i(R) × D_i × C_i × Q_i )
        Onde:
            w_i(R) : peso do agente i calibrado para o regime R
            D_i    : direção do sinal (+1 para BUY, -1 para SELL, 0 para HOLD)
            C_i    : confiança calibrada do agente (0.0 a 1.0)
            Q_i    : qualidade histórica fora da amostra do agente (0.5 a 1.0)
    """

    def __init__(
        self,
        platt_scaler: Optional[PlattScaler] = None,
        buy_threshold: float = 0.35,
        sell_threshold: float = -0.35,
        min_calibrated_probability: float = 0.60,
        regime_weights: Optional[Dict[MarketRegimeType, Dict[str, float]]] = None,
        quality_factors: Optional[Dict[str, float]] = None,
    ):
        self.platt_scaler = platt_scaler or PlattScaler()
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.min_calibrated_probability = min_calibrated_probability
        self.regime_weights = regime_weights or REGIME_AGENT_WEIGHTS
        self.quality_factors = quality_factors or DEFAULT_QUALITY_FACTORS

    def deliberate(
        self,
        signals: List[AgentSignal],
        active_regime: MarketRegimeType,
        symbol: str,
        adversarial_result: Optional[AdversarialDebateResult] = None,
    ) -> ConsensusDecision:
        """
        Executa a deliberação analítica e ponderada de todos os sinais dos agentes especialistas.
        """
        weights_map = self.regime_weights.get(active_regime, {})

        composite_score = 0.0
        total_weight_applied = 0.0

        participating_agents: List[str] = []
        dissenting_agents: List[str] = []
        invalidation_criteria: List[str] = []

        # Valores de referência para Stop Loss e Take Profit ponderados
        buy_entries = []
        buy_stops = []
        buy_targets = []
        sell_entries = []
        sell_stops = []
        sell_targets = []

        has_strong_buy = False
        has_strong_sell = False

        for sig in signals:
            agent_id = sig.agent_id
            w = weights_map.get(agent_id, 0.05)
            # Aumenta peso de AG05 se for Ouro
            if "XAU" in symbol.upper() and agent_id == "AG05_GOLD_MACRO":
                w += 0.15

            q = self.quality_factors.get(agent_id, 0.85)
            c = sig.confidence

            # Determina direção D_i
            d = 0.0
            if sig.direction == SignalDirection.BUY:
                d = 1.0
                buy_entries.append(sig.suggested_entry)
                buy_stops.append(sig.suggested_stop)
                buy_targets.append(sig.suggested_target)
                if c >= 0.80:
                    has_strong_buy = True
            elif sig.direction == SignalDirection.SELL:
                d = -1.0
                sell_entries.append(sig.suggested_entry)
                sell_stops.append(sig.suggested_stop)
                sell_targets.append(sig.suggested_target)
                if c >= 0.80:
                    has_strong_sell = True

            # Termo: w_i(R) * D_i * C_i * Q_i
            term = w * d * c * q
            composite_score += term
            total_weight_applied += w

            if d != 0:
                participating_agents.append(f"{agent_id}:{sig.direction.value}")

        # Normaliza pontuação pela soma dos pesos aplicados
        if total_weight_applied > 0:
            normalized_score = composite_score / total_weight_applied
        else:
            normalized_score = 0.0

        # Aplica penalidade do AG07 Adversarial Research se disponível
        if adversarial_result is not None:
            if adversarial_result.veto_flag:
                invalidation_criteria.append("ADVERSARIAL_HARD_VETO")
                normalized_score = 0.0

            elif adversarial_result.risk_penalty_factor > 0:
                discount = 1.0 - adversarial_result.risk_penalty_factor
                normalized_score *= discount
                invalidation_criteria.append(
                    f"ADVERSARIAL_DISCOUNT_{int(adversarial_result.risk_penalty_factor * 100)}PCT"
                )

        normalized_score = round(max(-1.0, min(1.0, normalized_score)), 4)

        # Checa conflito severo insolúvel (ex: AG01 BUY forte vs AG04 SELL forte)
        if has_strong_buy and has_strong_sell:
            invalidation_criteria.append("CONTRADICTORY_HIGH_CONVICTION_SIGNALS")
            normalized_score = 0.0  # Anula a pontuação por conflito interno irreconciliável

        # Calibra probabilidade via Platt Scaling
        calibrated_prob = self.platt_scaler.calibrate(normalized_score)

        # Determina a ação resultante
        if normalized_score >= self.buy_threshold and calibrated_prob >= self.min_calibrated_probability:
            action = SignalDirection.BUY
            suggested_entry = float(np.median(buy_entries)) if buy_entries else 1.0
            # Stop loss conservador (máximo entre os stops para manter proximidade, ou mediana)
            suggested_stop = float(np.median(buy_stops)) if buy_stops else suggested_entry * 0.99
            suggested_target = float(np.median(buy_targets)) if buy_targets else suggested_entry * 1.02
        elif normalized_score <= self.sell_threshold and calibrated_prob >= self.min_calibrated_probability:
            action = SignalDirection.SELL
            suggested_entry = float(np.median(sell_entries)) if sell_entries else 1.0
            suggested_stop = float(np.median(sell_stops)) if sell_stops else suggested_entry * 1.01
            suggested_target = float(np.median(sell_targets)) if sell_targets else suggested_entry * 0.98
        else:
            action = SignalDirection.HOLD
            suggested_entry = 1.0
            suggested_stop = 0.99
            suggested_target = 1.01

        # Identifica dissidentes
        for sig in signals:
            if action == SignalDirection.BUY and sig.direction == SignalDirection.SELL:
                dissenting_agents.append(sig.agent_id)
            elif action == SignalDirection.SELL and sig.direction == SignalDirection.BUY:
                dissenting_agents.append(sig.agent_id)

        # Garante coerência estrita de stop para validação do schema
        if action == SignalDirection.BUY and suggested_stop >= suggested_entry:
            suggested_stop = round(suggested_entry * 0.995, 5)
        if action == SignalDirection.SELL and suggested_stop <= suggested_entry:
            suggested_stop = round(suggested_entry * 1.005, 5)

        decision = ConsensusDecision(
            symbol=symbol.upper(),
            action=action,
            composite_score=normalized_score,
            calibrated_probability=calibrated_prob,
            active_regime=active_regime.value,
            participating_agents=participating_agents,
            dissenting_agents=dissenting_agents,
            invalidation_criteria=invalidation_criteria,
            suggested_entry=round(suggested_entry, 5),
            suggested_stop=round(suggested_stop, 5),
            suggested_target=round(suggested_target, 5),
        )

        logger.info(
            "consensus_deliberation_completed",
            symbol=symbol,
            action=action.value,
            composite_score=normalized_score,
            calibrated_prob=calibrated_prob,
            regime=active_regime.value,
        )

        return decision
