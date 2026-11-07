"""
QUANT HERMES — Testes do Motor de Consenso Ponderado (Consensus Engine)
Arquivo: tests/unit/test_consensus_engine.py
"""
import pytest
from core.models.agent import AgentSignal, SignalDirection
from core.models.market import TimeFrame
from core.models.regime import MarketRegimeType
from intelligence.agents.ag07_adversarial import AdversarialDebateResult
from intelligence.calibration.platt_scaler import PlattScaler
from intelligence.consensus.engine import ConsensusEngine


def make_sig(agent_id: str, direction: SignalDirection, confidence: float = 0.80) -> AgentSignal:
    entry = 1.08500
    stop = 1.08200 if direction == SignalDirection.BUY else 1.08800
    target = 1.09100 if direction == SignalDirection.BUY else 1.07900
    return AgentSignal(
        agent_id=agent_id,
        symbol="EURUSD",
        timeframe=TimeFrame.M15,
        direction=direction,
        confidence=confidence,
        suggested_entry=entry,
        suggested_stop=stop,
        suggested_target=target,
        invalidation_level=stop,
        model_version="1.0.0",
    )


class TestConsensusEngine:
    """Testes de integridade matemática e deliberação do Motor de Consenso."""

    def test_consensus_bull_trend_approves_buy(self):
        engine = ConsensusEngine()
        signals = [
            make_sig("AG01_TREND", SignalDirection.BUY, confidence=0.85),
            make_sig("AG02_STRUCTURE", SignalDirection.BUY, confidence=0.80),
            make_sig("AG03_MOMENTUM", SignalDirection.BUY, confidence=0.75),
        ]

        decision = engine.deliberate(
            signals=signals,
            active_regime=MarketRegimeType.TREND_BULL_STRONG,
            symbol="EURUSD",
        )

        assert decision.action == SignalDirection.BUY
        assert decision.composite_score >= 0.35
        assert decision.calibrated_probability >= 0.60
        assert decision.suggested_stop < decision.suggested_entry
        assert decision.suggested_target > decision.suggested_entry

    def test_consensus_ranging_favors_mean_reversion(self):
        engine = ConsensusEngine()
        # No regime lateral, AG04 possui maior peso (0.40)
        signals = [
            make_sig("AG04_MEAN_REVERSION", SignalDirection.SELL, confidence=0.85),
            make_sig("AG01_TREND", SignalDirection.HOLD, confidence=0.50),
        ]

        decision = engine.deliberate(
            signals=signals,
            active_regime=MarketRegimeType.RANGING_LOW_VOL,
            symbol="EURUSD",
        )

        assert decision.action == SignalDirection.SELL
        assert decision.composite_score <= -0.35

    def test_consensus_severe_contradiction_yields_hold(self):
        engine = ConsensusEngine()
        signals = [
            make_sig("AG01_TREND", SignalDirection.BUY, confidence=0.88),
            make_sig("AG04_MEAN_REVERSION", SignalDirection.SELL, confidence=0.88),
        ]

        decision = engine.deliberate(
            signals=signals,
            active_regime=MarketRegimeType.UNCERTAIN_TRANSITION,
            symbol="EURUSD",
        )

        assert decision.action == SignalDirection.HOLD
        assert "CONTRADICTORY_HIGH_CONVICTION_SIGNALS" in decision.invalidation_criteria

    def test_consensus_adversarial_veto_forces_hold(self):
        engine = ConsensusEngine()
        signals = [
            make_sig("AG01_TREND", SignalDirection.BUY, confidence=0.85),
            make_sig("AG02_STRUCTURE", SignalDirection.BUY, confidence=0.80),
        ]

        adversarial = AdversarialDebateResult(
            symbol="EURUSD",
            veto_flag=True,
            detected_traps=["CRITICAL_INSTITUTIONAL_SWEEP"],
        )

        decision = engine.deliberate(
            signals=signals,
            active_regime=MarketRegimeType.TREND_BULL_STRONG,
            symbol="EURUSD",
            adversarial_result=adversarial,
        )

        assert decision.action == SignalDirection.HOLD
        assert "ADVERSARIAL_HARD_VETO" in decision.invalidation_criteria

    def test_platt_scaler_calibration_properties(self):
        scaler = PlattScaler()
        # Monotonicidade estrita: quanto maior o score absoluto, maior a probabilidade
        p_zero = scaler.calibrate(0.0)
        p_mild = scaler.calibrate(0.35)
        p_strong = scaler.calibrate(0.70)
        p_extreme = scaler.calibrate(1.00)

        assert 0.0 < p_zero < p_mild < p_strong < p_extreme <= 1.0
        assert p_mild >= 0.60

