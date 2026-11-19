"""
QUANT HERMES — TESTES DO EXECUTOR SOBERANO DE ORDENS
Módulo: tests.unit.test_order_executor
"""
from datetime import datetime, timezone
from uuid import uuid4
import pytest

from core.models.risk import RiskAuthorization, TradeProposal
from execution.adapters.paper import PaperTradingAdapter
from execution.order_executor import OrderExecutor


@pytest.fixture
async def paper_adapter():
    adapter = PaperTradingAdapter(initial_balance=10000.0)
    await adapter.connect()
    yield adapter
    await adapter.disconnect()


@pytest.fixture
def executor(paper_adapter):
    return OrderExecutor(adapter=paper_adapter, idempotency_window_seconds=60)


class TestOrderExecutor:

    @pytest.mark.asyncio
    async def test_unapproved_risk_auth_raises_permission_error(self, executor):
        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND_EURUSD",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )

        unapproved_auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=False,
            authorized_lot=0.0,
            stop_loss=1.0950,
            rejection_reason="DAILY_LOSS_LIMIT_REACHED",
        )

        # Barreira Constitucional: Deve disparar PermissionError
        with pytest.raises(PermissionError, match="Constitutional Violation"):
            await executor.execute_order(proposal, unapproved_auth)

    @pytest.mark.asyncio
    async def test_approved_risk_auth_executes_successfully(self, executor):
        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_MOMENTUM_EURUSD",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.1000,
            stop_loss=1.0960,
            take_profit=1.1080,
        )

        approved_auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.10,
            stop_loss=1.0960,
            take_profit=1.1080,
            risk_amount_money=25.0,
            risk_percentage=0.25,
        )

        result = await executor.execute_order(proposal, approved_auth)
        assert result.success is True
        assert result.order_ticket > 0
        assert result.volume_executed == 0.10
        assert len(executor.get_execution_history()) == 1
        stored = executor.store.get_intent_by_key(result.idempotency_key)
        assert stored is not None
        assert stored["requested_lot"] == approved_auth.authorized_lot
        assert stored["requested_lot"] != proposal.target_risk_pct

    @pytest.mark.asyncio
    async def test_idempotency_blocks_duplicate_order_submission(self, executor):
        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_BREAKOUT_EURUSD",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )

        approved_auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.05,
            stop_loss=1.0950,
            take_profit=1.1100,
        )

        # Primeira submissão: Sucesso
        res1 = await executor.execute_order(proposal, approved_auth)
        assert res1.success is True

        # Segunda submissão idêntica imediata: Bloqueada por Idempotência
        res2 = await executor.execute_order(proposal, approved_auth)
        assert res2.success is False
        assert "IDEMPOTENCY" in res2.comment

    @pytest.mark.asyncio
    async def test_mismatched_symbol_raises_value_error(self, executor):
        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_SCALP",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.1000,
            stop_loss=1.0950,
        )

        mismatched_auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="GBPUSD",  # Símbolo divergente
            action="BUY",
            approved=True,
            authorized_lot=0.10,
            stop_loss=1.0950,
        )

        with pytest.raises(ValueError, match="Incoerência de ativo"):
            await executor.execute_order(proposal, mismatched_auth)
