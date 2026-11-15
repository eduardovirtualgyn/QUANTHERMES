"""
QUANT HERMES — TESTES DE RESILIÊNCIA, IDEMPOTÊNCIA PERSISTENTE E RECUPERAÇÃO DE CRASH (FASE 7.1)
Módulo: tests.unit.test_phase_7_1_resilience

Valida:
1. Resiliência a crashes durante o envio ao broker (detecção de ambiguidade).
2. Prevenção estrita de reenvio cego em ordens com resultado desconhecido.
3. Tratamento e distinção de preenchimentos parciais (PARTIALLY_FILLED).
4. Registro transacional e auditável de rejeições do broker (REJECTED).
5. Recuperação pós-crash na inicialização (recover_unresolved_orders).
6. Postura Fail-Closed diante de falhas de escrita do armazenamento SQLite.
7. Concorrência e bloqueio entre múltiplas instâncias do executor compartilhando o mesmo disco.
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest

from core.models.risk import (
    OrderRequest,
    OrderResult,
    Position,
    RiskAuthorization,
    TradeProposal,
)
from execution.adapters.base import TradingPlatformAdapter
from execution.adapters.paper import PaperTradingAdapter
from execution.idempotency import (
    OrderLifecycleState,
    SqliteIdempotencyStore,
    StoreCorruptedError,
)
from execution.order_executor import OrderExecutor


class MockFaultyAdapter(PaperTradingAdapter):
    """Adaptador com capacidade de injeção de falhas para testes de resiliência."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.should_raise_on_send: bool = False
        self.should_partial_fill: bool = False
        self.should_reject: bool = False
        self.partial_lot: float = 0.05
        self.rejection_reason: str = "MT5_REQUOTE_10006"

    async def send_order(self, request: OrderRequest) -> OrderResult:
        if self.should_raise_on_send:
            raise ConnectionResetError("Broker socket dropped connection during order_send")

        if self.should_reject:
            return OrderResult(
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                success=False,
                retcode=10006,
                comment=self.rejection_reason,
            )

        if self.should_partial_fill:
            ticket = self._next_ticket
            self._next_ticket += 1
            return OrderResult(
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                success=True,
                retcode=10009,
                order_ticket=ticket,
                deal_ticket=ticket + 500,
                volume_executed=self.partial_lot,
                price_executed=request.price,
                comment="PARTIALLY_FILLED_IOC",
            )

        return await super().send_order(request)


@pytest.fixture
def test_db_path(tmp_path):
    return tmp_path / "resilience_idempotency.db"


@pytest.fixture
def store(test_db_path):
    return SqliteIdempotencyStore(db_path=test_db_path)


@pytest.fixture
def faulty_adapter():
    return MockFaultyAdapter(initial_balance=100000.0)


@pytest.fixture
def resilient_executor(faulty_adapter, store):
    return OrderExecutor(adapter=faulty_adapter, store=store, idempotency_window_seconds=60)


def create_sample_proposal_and_auth(symbol: str = "EURUSD", action: str = "BUY", lot: float = 0.10):
    decision_id = uuid4()
    proposal = TradeProposal(
        decision_id=decision_id,
        strategy_id="STRAT_TEST_RESILIENCE",
        symbol=symbol,
        action=action,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        magic=777001,
    )
    auth = RiskAuthorization(
        decision_id=decision_id,
        symbol=symbol,
        action=action,
        approved=True,
        authorized_lot=lot,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_amount_money=50.0,
        risk_percentage=0.25,
    )
    return proposal, auth


class TestPhase71Resilience:

    @pytest.mark.asyncio
    async def test_ambiguous_result_on_socket_drop_is_marked_reconciliation_required(
        self, resilient_executor, faulty_adapter, store
    ):
        """
        Cenário Crítico: O socket do MT5 cai ou dá timeout durante send_order.
        O sistema NÃO deve tentar reenvio cego e deve marcar como RECONCILIATION_REQUIRED.
        """
        proposal, auth = create_sample_proposal_and_auth()
        faulty_adapter.should_raise_on_send = True

        result = await resilient_executor.execute_order(proposal, auth)
        assert result.success is False
        assert "AMBIGUOUS" in result.comment
        assert "RECONCILIATION_REQUIRED" in result.comment

        # Verifica estado no banco SQLite
        intent = store.get_intent_by_key(result.idempotency_key)
        assert intent is not None
        assert intent["state"] == OrderLifecycleState.RECONCILIATION_REQUIRED.value
        assert "ConnectionResetError" in intent["last_error"]

        # Tentativa de reenvio com mesma proposta é estritamente BLOQUEADA por idempotência
        retry_result = await resilient_executor.execute_order(proposal, auth)
        assert retry_result.success is False
        assert retry_result.comment == "DUPLICATE_ORDER_BLOCKED_BY_IDEMPOTENCY"

    @pytest.mark.asyncio
    async def test_partial_fill_preserves_executed_volume_and_marks_state(
        self, resilient_executor, faulty_adapter, store
    ):
        """
        Cenário: O broker preenche apenas 0.05 de um lote autorizado de 0.10.
        O sistema deve registrar o estado como PARTIALLY_FILLED e preservar os volumes.
        """
        proposal, auth = create_sample_proposal_and_auth(lot=0.10)
        faulty_adapter.should_partial_fill = True
        faulty_adapter.partial_lot = 0.05

        result = await resilient_executor.execute_order(proposal, auth)
        assert result.success is True
        assert result.volume_executed == 0.05

        intent = store.get_intent_by_key(result.idempotency_key)
        assert intent["state"] == OrderLifecycleState.PARTIALLY_FILLED.value
        assert intent["authorized_lot"] == 0.10
        assert intent["volume_executed"] == 0.05
        assert intent["order_ticket"] == result.order_ticket

    @pytest.mark.asyncio
    async def test_broker_rejection_marks_rejected_and_stores_reason(
        self, resilient_executor, faulty_adapter, store
    ):
        """
        Cenário: O broker rejeita a ordem (Requote ou preço inválido).
        O sistema deve registrar REJECTED com retcode e motivo.
        """
        proposal, auth = create_sample_proposal_and_auth()
        faulty_adapter.should_reject = True
        faulty_adapter.rejection_reason = "MT5_REQUOTE_10006"

        result = await resilient_executor.execute_order(proposal, auth)
        assert result.success is False
        assert result.retcode == 10006

        intent = store.get_intent_by_key(result.idempotency_key)
        assert intent["state"] == OrderLifecycleState.REJECTED.value
        assert intent["retcode"] == 10006
        assert "MT5_REQUOTE_10006" in intent["broker_comment"]

    @pytest.mark.asyncio
    async def test_crash_recovery_protocol_reconciles_matched_open_position(
        self, resilient_executor, faulty_adapter, store, test_db_path
    ):
        """
        Cenário de Crash e Recuperação:
        1. Intenção foi persistida em SUBMITTING.
        2. Processo sofreu crash antes de receber resposta.
        3. No broker, a ordem existe (foi aberta).
        4. O procedimento recover_unresolved_orders localiza a posição e atualiza para FILLED.
        """
        proposal, auth = create_sample_proposal_and_auth()
        key = store.generate_idempotency_key(
            proposal.symbol, proposal.action, proposal.strategy_id, proposal.decision_id, auth.auth_id
        )

        # Simula estado deixado em SUBMITTING pelo processo morto
        store.register_intent_pre_submission(
            intent_id=proposal.proposal_id,
            idempotency_key=key,
            decision_id=proposal.decision_id,
            auth_id=auth.auth_id,
            strategy_id=proposal.strategy_id,
            symbol=proposal.symbol,
            action=proposal.action,
            requested_lot=0.10,
            authorized_lot=0.10,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            magic=proposal.magic,
        )

        # Injeta uma posição existente no broker simulador com a mesma assinatura (magic + symbol)
        broker_ticket = 998811
        faulty_adapter._positions[broker_ticket] = Position(
            ticket=broker_ticket,
            symbol=proposal.symbol,
            magic=proposal.magic,
            position_type=proposal.action,
            volume=0.10,
            open_price=1.1002,
            stop_loss=1.0950,
            take_profit=1.1100,
            current_price=1.1002,
            open_time=datetime.now(timezone.utc),
        )

        # Executa recuperação
        recovered = await resilient_executor.recover_unresolved_orders()
        assert len(recovered) == 1
        assert recovered[0]["status"] == "RECONCILED_FILLED"
        assert recovered[0]["ticket"] == broker_ticket

        # Verifica estado pós-recuperação no SQLite
        intent = store.get_intent_by_key(key)
        assert intent["state"] == OrderLifecycleState.FILLED.value
        assert intent["order_ticket"] == broker_ticket

    @pytest.mark.asyncio
    async def test_crash_recovery_protocol_marks_missing_position_as_reconciliation_required(
        self, resilient_executor, store
    ):
        """
        Cenário: Ordem deixada em SUBMITTING antes do crash, mas nenhuma posição aberta foi encontrada no broker.
        O sistema deve marcar como RECONCILIATION_REQUIRED para evitar reenvio cego.
        """
        proposal, auth = create_sample_proposal_and_auth()
        key = store.generate_idempotency_key(
            proposal.symbol, proposal.action, proposal.strategy_id, proposal.decision_id, auth.auth_id
        )

        store.register_intent_pre_submission(
            intent_id=proposal.proposal_id,
            idempotency_key=key,
            decision_id=proposal.decision_id,
            auth_id=auth.auth_id,
            strategy_id=proposal.strategy_id,
            symbol=proposal.symbol,
            action=proposal.action,
            requested_lot=0.10,
            authorized_lot=0.10,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            magic=proposal.magic,
        )

        recovered = await resilient_executor.recover_unresolved_orders()
        assert len(recovered) == 1
        assert recovered[0]["status"] == "MARKED_RECONCILIATION_REQUIRED"

        intent = store.get_intent_by_key(key)
        assert intent["state"] == OrderLifecycleState.RECONCILIATION_REQUIRED.value

    @pytest.mark.asyncio
    async def test_fail_closed_aborts_order_when_persistence_fails(self, resilient_executor, store):
        """
        Cenário Fail-Closed: Falha no banco de dados SQLite impede o envio de ordem.
        Nenhuma ordem pode ser despachada sem garantia de persistência durável.
        """
        proposal, auth = create_sample_proposal_and_auth()

        with patch.object(
            store, "register_intent_pre_submission", side_effect=StoreCorruptedError("Disk I/O error")
        ):
            result = await resilient_executor.execute_order(proposal, auth)
            assert result.success is False
            assert "FAIL_CLOSED" in result.comment
            assert result.order_ticket == 0

    @pytest.mark.asyncio
    async def test_multi_instance_idempotency_across_processes(self, test_db_path, faulty_adapter):
        """
        Testa duas instâncias completamente separadas do OrderExecutor (como se fossem dois processos),
        compartilhando o mesmo arquivo SQLite no disco.
        A segunda instância deve ser estritamente bloqueada mesmo sem histórico em RAM.
        """
        store1 = SqliteIdempotencyStore(db_path=test_db_path)
        executor1 = OrderExecutor(adapter=faulty_adapter, store=store1)

        store2 = SqliteIdempotencyStore(db_path=test_db_path)
        executor2 = OrderExecutor(adapter=faulty_adapter, store=store2)

        proposal, auth = create_sample_proposal_and_auth()

        # Instância 1 executa
        res1 = await executor1.execute_order(proposal, auth)
        assert res1.success is True

        # Instância 2 tenta executar a mesma proposta com histórico em RAM zerado
        res2 = await executor2.execute_order(proposal, auth)
        assert res2.success is False
        assert "IDEMPOTENCY" in res2.comment
