"""
QUANT HERMES — Testes do Reconciliador de Posições
Arquivo: tests/unit/test_reconciler.py
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from core.models.risk import OrderRequest, Position
from execution.adapters.paper import PaperTradingAdapter
from portfolio.reconciler import PositionReconciler


@pytest.fixture
def reconciler():
    return PositionReconciler(sl_tolerance_points=0.0001)


@pytest.mark.asyncio
class TestPositionReconciler:
    """Testes de reconciliação de integridade entre estado local e broker."""

    async def test_clean_synchronization(self, reconciler):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()

        # Abre uma posição no adapter
        order = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.1,
            price=1.08500,
            stop_loss=1.08200,
            magic=1001,
            idempotency_key="RECON_TEST_1",
        )
        res = await adapter.send_order(order)
        assert res.success is True

        positions = await adapter.get_open_positions()
        ticket = positions[0].ticket

        # Registro interno perfeitamente alinhado
        internal_registry = {ticket: positions[0]}

        report = await reconciler.reconcile(adapter, internal_registry)
        assert report.is_synced is True
        assert len(report.orphaned_tickets) == 0
        assert len(report.ghost_tickets) == 0
        assert len(report.sl_mismatches) == 0

        await adapter.disconnect()

    async def test_detects_orphaned_position(self, reconciler):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()

        # Abre uma ordem no broker sem registrar no sistema
        order = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.2,
            price=1.08500,
            stop_loss=1.08200,
            magic=9999,
            idempotency_key="RECON_ORPHAN",
        )
        res = await adapter.send_order(order)
        assert res.success is True

        positions = await adapter.get_open_positions()
        ticket = positions[0].ticket

        # Registro interno vazio (não conhece essa posição)
        internal_registry = {}

        report = await reconciler.reconcile(adapter, internal_registry)
        assert report.is_synced is False
        assert report.orphaned_tickets == [ticket]

        await adapter.disconnect()

    async def test_detects_ghost_position(self, reconciler):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()

        # Broker não tem nenhuma posição aberta
        # Sistema interno acha que tem uma posição com ticket 777
        ghost_pos = Position(
            ticket=777,
            symbol="EURUSD",
            magic=1001,
            position_type="BUY",
            volume=0.1,
            open_price=1.08500,
            stop_loss=1.08200,
            current_price=1.08500,
            open_time=datetime.now(timezone.utc),
        )
        internal_registry = {777: ghost_pos}

        report = await reconciler.reconcile(adapter, internal_registry)
        assert report.is_synced is False
        assert report.ghost_tickets == [777]

        await adapter.disconnect()

    async def test_detects_and_corrects_sl_mismatch(self, reconciler):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()

        # Abre posição no broker com SL = 1.08000
        order = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.1,
            price=1.08500,
            stop_loss=1.08000,
            magic=1001,
            idempotency_key="RECON_SL_MISMATCH",
        )
        res = await adapter.send_order(order)
        ticket = res.order_ticket

        # O registro de risco interno exige SL mais apertado: 1.08250
        broker_pos = (await adapter.get_open_positions())[0]
        internal_pos = broker_pos.model_copy(update={"stop_loss": 1.08250})
        internal_registry = {ticket: internal_pos}

        # Executa reconciliação com auto_correct_stops=True
        report = await reconciler.reconcile(adapter, internal_registry, auto_correct_stops=True)
        assert len(report.sl_mismatches) == 1
        assert report.sl_mismatches[0]["ticket"] == ticket

        # Verifica se o Stop Loss foi corrigido no broker
        updated_broker_pos = (await adapter.get_open_positions())[0]
        assert updated_broker_pos.stop_loss == 1.08250

        await adapter.disconnect()
