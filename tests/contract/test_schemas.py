"""
Testes de Contratos e Schemas Pydantic V2
Arquivo: tests/contract/test_schemas.py
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import ValidationError

from core.models.market import MarketTick, MarketBar, TimeFrame
from core.models.agent import AgentSignal, SignalDirection, ConsensusDecision
from core.models.risk import RiskAuthorization, AccountState, Position, OrderRequest, TradeProposal


class TestMarketSchemas:
    """Testes de integridade para schemas de dados de mercado."""

    def test_market_tick_valid(self):
        tick = MarketTick(
            symbol="EURUSD",
            time=datetime.now(timezone.utc),
            bid=1.08500,
            ask=1.08515,
            last=1.08505,
            volume=10.0,
        )
        assert tick.spread == 0.00015
        assert tick.bid == 1.08500
        assert tick.ask == 1.08515

    def test_market_tick_rejects_ask_lower_than_bid(self):
        with pytest.raises(ValidationError, match="não pode ser menor que Bid"):
            MarketTick(
                symbol="EURUSD",
                time=datetime.now(timezone.utc),
                bid=1.08550,
                ask=1.08500,  # Inválido: Ask menor que Bid
            )

    def test_market_bar_high_low_coherence(self):
        bar = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M5,
            time=datetime.now(timezone.utc),
            open=1.08500,
            high=1.08600,
            low=1.08450,
            close=1.08550,
            tick_volume=350,
        )
        assert bar.high >= bar.low
        assert bar.high >= bar.open

    def test_market_bar_rejects_high_lower_than_low(self):
        with pytest.raises(ValidationError, match="não pode ser menor que Low"):
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M5,
                time=datetime.now(timezone.utc),
                open=1.08500,
                high=1.08400,  # Inválido: High menor que Low
                low=1.08450,
                close=1.08420,
                tick_volume=100,
            )


class TestAgentSchemas:
    """Testes de integridade para sinais analíticos e consenso."""

    def test_agent_signal_buy_coherence(self):
        signal = AgentSignal(
            agent_id="AG01_TREND",
            symbol="EURUSD",
            timeframe=TimeFrame.M15,
            direction=SignalDirection.BUY,
            confidence=0.85,
            suggested_entry=1.08500,
            suggested_stop=1.08200,  # Válido: SL menor que Entrada
            suggested_target=1.09100,
            invalidation_level=1.08150,
            rationale={"ema_aligned": True, "adx": 32.5},
            model_version="1.0.0",
        )
        assert signal.direction == SignalDirection.BUY
        assert signal.confidence == 0.85

    def test_agent_signal_rejects_incoherent_buy_stop(self):
        with pytest.raises(ValidationError, match="deve ser estritamente menor que a entrada"):
            AgentSignal(
                agent_id="AG01_TREND",
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                direction=SignalDirection.BUY,
                confidence=0.85,
                suggested_entry=1.08500,
                suggested_stop=1.08600,  # Inválido: SL maior que Entrada para BUY
                suggested_target=1.09000,
                invalidation_level=1.08700,
                model_version="1.0.0",
            )

    def test_agent_signal_rejects_incoherent_sell_stop(self):
        with pytest.raises(ValidationError, match="deve ser estritamente maior que a entrada"):
            AgentSignal(
                agent_id="AG01_TREND",
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                direction=SignalDirection.SELL,
                confidence=0.75,
                suggested_entry=1.08500,
                suggested_stop=1.08400,  # Inválido: SL menor que Entrada para SELL
                suggested_target=1.08000,
                invalidation_level=1.08450,
                model_version="1.0.0",
            )

    def test_agent_signal_confidence_bounds(self):
        with pytest.raises(ValidationError):
            AgentSignal(
                agent_id="AG01_TREND",
                symbol="EURUSD",
                timeframe=TimeFrame.M15,
                direction=SignalDirection.BUY,
                confidence=1.25,  # Inválido: confiança acima de 1.0
                suggested_entry=1.08500,
                suggested_stop=1.08200,
                suggested_target=1.09100,
                invalidation_level=1.08150,
                model_version="1.0.0",
            )


class TestRiskSchemas:
    """Testes de integridade para autorização do Risk Engine e ordens."""

    def test_risk_authorization_approved_valid(self):
        auth = RiskAuthorization(
            decision_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.50,
            stop_loss=1.08200,
            take_profit=1.09100,
            risk_amount_money=250.0,
            risk_percentage=0.25,
            max_slippage_points=25,
        )
        assert auth.approved is True
        assert auth.authorized_lot == 0.50
        assert auth.stop_loss == 1.08200

    def test_risk_authorization_rejects_approved_with_zero_lot(self):
        with pytest.raises(ValidationError, match="lote estritamente positivo"):
            RiskAuthorization(
                decision_id=uuid4(),
                symbol="EURUSD",
                action="BUY",
                approved=True,
                authorized_lot=0.0,  # Inválido: Aprovado com lote zero
                stop_loss=1.08200,
                risk_amount_money=0.0,
                risk_percentage=0.25,
            )

    def test_risk_authorization_rejects_approved_with_rejection_reason(self):
        with pytest.raises(ValidationError, match="não pode conter rejection_reason"):
            RiskAuthorization(
                decision_id=uuid4(),
                symbol="EURUSD",
                action="BUY",
                approved=True,
                authorized_lot=0.10,
                stop_loss=1.08200,
                risk_amount_money=100.0,
                risk_percentage=0.25,
                rejection_reason="REJECTED_DUE_TO_DRAWDOWN",  # Inválido se approved=True
            )

    def test_risk_authorization_caps_risk_at_50_pct(self):
        with pytest.raises(ValidationError):
            RiskAuthorization(
                decision_id=uuid4(),
                symbol="EURUSD",
                action="BUY",
                approved=True,
                authorized_lot=0.10,
                stop_loss=1.08200,
                risk_amount_money=100.0,
                risk_percentage=0.60,  # Inválido: teto absoluto é 0.50%
            )

    def test_trade_proposal_valid(self):
        prop = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_MOMENTUM_EURUSD",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )
        assert prop.action == "BUY"
        assert prop.entry_price == 1.08500
        assert prop.stop_loss == 1.08200
        assert prop.target_risk_pct == 0.25

    def test_trade_proposal_rejects_incoherent_buy_stop(self):
        with pytest.raises(ValidationError, match="Stop Loss .* deve ser estritamente menor que entrada"):
            TradeProposal(
                decision_id=uuid4(),
                strategy_id="STRAT_MOMENTUM_EURUSD",
                symbol="EURUSD",
                action="BUY",
                entry_price=1.08500,
                stop_loss=1.08600,
            )

    def test_trade_proposal_rejects_incoherent_sell_stop(self):
        with pytest.raises(ValidationError, match="Stop Loss .* deve ser estritamente maior que entrada"):
            TradeProposal(
                decision_id=uuid4(),
                strategy_id="STRAT_MOMENTUM_EURUSD",
                symbol="EURUSD",
                action="SELL",
                entry_price=1.08500,
                stop_loss=1.08400,
            )


