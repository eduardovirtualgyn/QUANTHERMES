"""
Testes Unitários do Adaptador de Paper Trading
Arquivo: tests/unit/test_paper_adapter.py
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4
from core.models.risk import OrderRequest
from core.models.market import MarketTick
from execution.adapters.paper import PaperTradingAdapter


@pytest.mark.asyncio
class TestPaperTradingAdapter:
    """Valida a precisão da simulação em memória do PaperTradingAdapter."""

    async def test_initial_account_state(self):
        adapter = PaperTradingAdapter(initial_balance=100000.0, currency="USD", leverage=100)
        await adapter.connect()
        assert await adapter.is_connected() is True

        acc = await adapter.get_account_state()
        assert acc.balance == 100000.0
        assert acc.equity == 100000.0
        assert acc.margin == 0.0
        assert acc.free_margin == 100000.0
        assert acc.current_drawdown_pct == 0.0

    async def test_send_buy_order_and_position_creation(self):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()
        adapter.set_price("EURUSD", bid=1.08500, ask=1.08520)

        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=1.0,
            price=1.08520,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=111,
            idempotency_key="order_buy_001",
        )

        res = await adapter.send_order(req)
        assert res.success is True
        assert res.retcode == 10009
        assert res.order_ticket > 0

        positions = await adapter.get_open_positions("EURUSD")
        assert len(positions) == 1
        pos = positions[0]
        assert pos.symbol == "EURUSD"
        assert pos.position_type == "BUY"
        assert pos.volume == 1.0
        assert pos.open_price == 1.08520
        assert pos.stop_loss == 1.08000

    async def test_tick_update_and_pnl_calculation(self):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()
        adapter.set_price("EURUSD", bid=1.08500, ask=1.08520)

        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=1.0,
            price=1.08520,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=111,
            idempotency_key="order_buy_002",
        )
        await adapter.send_order(req)

        # O preço sobe 50 pips (de 1.08500 para 1.08550 bid)
        adapter.set_price("EURUSD", bid=1.08570, ask=1.08590)

        positions = await adapter.get_open_positions("EURUSD")
        pos = positions[0]
        # PnL esperado: (1.08570 - 1.08520) * 100,000 * 1.0 = +50.0 USD
        assert pos.profit == 50.0

        acc = await adapter.get_account_state()
        assert acc.equity == 100050.0
        assert acc.balance == 100000.0  # Balance permanece intacto até fechar

    async def test_stop_loss_hit_trigger(self):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()
        adapter.set_price("EURUSD", bid=1.08500, ask=1.08520)

        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=1.0,
            price=1.08520,
            stop_loss=1.08200,  # SL a 32 pips de distância
            take_profit=1.09500,
            magic=111,
            idempotency_key="order_buy_sl",
        )
        await adapter.send_order(req)

        # Preço cai e fura o Stop Loss (bid bate 1.08190 <= 1.08200)
        adapter.set_price("EURUSD", bid=1.08190, ask=1.08210)

        # A posição DEVE ter sido liquidada automaticamente pelo SL
        positions = await adapter.get_open_positions("EURUSD")
        assert len(positions) == 0

        acc = await adapter.get_account_state()
        # Perda realizada do SL: (1.08200 - 1.08520) * 100,000 * 1.0 = -320.0 USD
        assert acc.balance == 99680.0
        assert acc.equity == 99680.0
        assert acc.current_drawdown_pct > 0.0

    async def test_manual_close_position(self):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()
        adapter.set_price("EURUSD", bid=1.08500, ask=1.08520)

        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=1.0,
            price=1.08520,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=111,
            idempotency_key="order_buy_manual_close",
        )
        res = await adapter.send_order(req)
        ticket = res.order_ticket

        # Mercado sobe 100 pips (+100 USD)
        adapter.set_price("EURUSD", bid=1.08620, ask=1.08640)

        close_res = await adapter.close_position(ticket)
        assert close_res.success is True

        positions = await adapter.get_open_positions("EURUSD")
        assert len(positions) == 0

        acc = await adapter.get_account_state()
        assert acc.balance == 100100.0
        assert acc.equity == 100100.0

    async def test_order_idempotency_protection(self):
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()
        adapter.set_price("EURUSD", bid=1.08500, ask=1.08520)

        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=1.0,
            price=1.08520,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=111,
            idempotency_key="unique_idempotency_key_123",
        )

        res1 = await adapter.send_order(req)
        res2 = await adapter.send_order(req)

        # Ambas as chamadas retornam o mesmo ticket sem duplicar posição no mercado
        assert res1.order_ticket == res2.order_ticket
        positions = await adapter.get_open_positions("EURUSD")
        assert len(positions) == 1

    async def test_reject_order_with_insufficient_margin(self):
        # Cria conta com saldo pequeno ($100)
        adapter = PaperTradingAdapter(initial_balance=100.0, leverage=10)
        await adapter.connect()
        adapter.set_price("EURUSD", bid=1.08500, ask=1.08520)

        # Tenta comprar 10 lotes (exige mais de $100,000 de margem)
        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=10.0,
            price=1.08520,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=111,
            idempotency_key="insufficient_margin_order",
        )

        res = await adapter.send_order(req)
        assert res.success is False
        assert res.retcode == 10019  # Sem margem
        positions = await adapter.get_open_positions("EURUSD")
        assert len(positions) == 0

