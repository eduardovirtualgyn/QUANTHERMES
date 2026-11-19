"""
QUANT HERMES — TESTES DO ADAPTADOR LINUX BRIDGE E MT5 GATEWAY
Módulo: tests.unit.test_linux_bridge_adapter
"""
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient

from core.models.market import MarketBar, MarketTick, TimeFrame
from core.models.risk import OrderRequest
from execution.adapters.base import PlatformConnectionError
from execution.adapters.linux_bridge import LinuxMT5BridgeAdapter
from execution.adapters.paper import PaperTradingAdapter
from execution.gateway.mt5_gateway import create_gateway_app


@pytest.fixture
def mock_gateway_setup():
    """Cria gateway em memória acoplado a um PaperTradingAdapter."""
    paper_adapter = PaperTradingAdapter(initial_balance=25000.0)
    app = create_gateway_app(
        adapter=paper_adapter,
        secret_token="TEST_HERMES_SECRET_TOKEN_2026",
    )
    return app, paper_adapter


@pytest.fixture
def valid_bridge_adapter(mock_gateway_setup):
    """Retorna LinuxMT5BridgeAdapter configurado com cliente in-memory ASGI válido."""
    app, paper_adapter = mock_gateway_setup
    transport = ASGITransport(app=app)
    client = AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Hermes-Bridge-Token": "TEST_HERMES_SECRET_TOKEN_2026"},
    )
    adapter = LinuxMT5BridgeAdapter(
        gateway_url="http://testserver",
        bridge_token="TEST_HERMES_SECRET_TOKEN_2026",
        client=client,
    )
    return adapter, paper_adapter, client


class TestLinuxMT5BridgeAdapter:

    @pytest.mark.asyncio
    async def test_connect_and_is_connected(self, valid_bridge_adapter):
        bridge, paper, client = valid_bridge_adapter
        assert await bridge.is_connected() is False

        connected = await bridge.connect()
        assert connected is True
        assert await bridge.is_connected() is True

        await bridge.disconnect()
        assert await bridge.is_connected() is False
        await client.aclose()

    @pytest.mark.asyncio
    async def test_unauthorized_token_rejected(self, mock_gateway_setup):
        app, _ = mock_gateway_setup
        transport = ASGITransport(app=app)
        bad_client = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-Hermes-Bridge-Token": "INVALID_TOKEN"},
        )
        bad_bridge = LinuxMT5BridgeAdapter(
            gateway_url="http://testserver",
            bridge_token="INVALID_TOKEN",
            client=bad_client,
        )

        connected = await bad_bridge.connect()
        assert connected is False
        assert await bad_bridge.is_connected() is False
        await bad_client.aclose()

    @pytest.mark.asyncio
    async def test_get_account_state_deserialization(self, valid_bridge_adapter):
        bridge, paper, client = valid_bridge_adapter
        await bridge.connect()

        account = await bridge.get_account_state()
        assert account.balance == 25000.0
        assert account.equity == 25000.0
        assert account.currency == "USD"
        assert account.current_drawdown_pct == 0.0

        await bridge.disconnect()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_get_symbol_info(self, valid_bridge_adapter):
        bridge, paper, client = valid_bridge_adapter
        await bridge.connect()

        info = await bridge.get_symbol_info("EURUSD")
        assert info.symbol == "EURUSD"
        assert info.digits == 5
        assert info.point == 0.00001
        assert info.contract_size == 100000.0

        await bridge.disconnect()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_get_ticks_and_bars(self, valid_bridge_adapter):
        bridge, paper, client = valid_bridge_adapter
        await bridge.connect()

        now = datetime.now(timezone.utc)
        sample_tick = MarketTick(
            symbol="EURUSD",
            time=now,
            bid=1.1000,
            ask=1.1002,
            last=1.1001,
            volume=10,
        )
        sample_bar = MarketBar(
            symbol="EURUSD",
            timeframe=TimeFrame.M15,
            time=now,
            open=1.1000,
            high=1.1020,
            low=1.0990,
            close=1.1010,
            tick_volume=100,
        )
        paper._historical_ticks["EURUSD"] = [sample_tick]
        paper.set_historical_bars("EURUSD", [sample_bar])

        ticks = await bridge.get_ticks("EURUSD", count=5)
        assert len(ticks) == 1
        assert ticks[0].symbol == "EURUSD"

        bars = await bridge.get_bars("EURUSD", timeframe=TimeFrame.M15, count=10)
        assert len(bars) == 1
        assert bars[0].high >= bars[0].low

        await bridge.disconnect()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_order_and_position_lifecycle(self, valid_bridge_adapter):
        bridge, paper, client = valid_bridge_adapter
        await bridge.connect()

        order_req = OrderRequest(
            auth_id=uuid4(),
            idempotency_key="TEST_KEY_12345",
            symbol="EURUSD",
            action="BUY",
            volume=0.10,
            price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            magic=123456,
            comment="HERMES_TEST_ORDER",
        )

        # 1. Verifica prévia da ordem
        check_res = await bridge.check_order(order_req)
        assert check_res.get("retcode") == 0

        # 2. Despacho físico ao broker
        exec_res = await bridge.send_order(order_req)
        assert exec_res.success is True
        assert exec_res.order_ticket > 0
        assert exec_res.volume_executed == 0.10

        # 3. Consulta posições abertas
        positions = await bridge.get_open_positions(symbol="EURUSD")
        assert len(positions) == 1
        assert positions[0].ticket == exec_res.order_ticket

        # 4. Modifica níveis de Stop Loss / Take Profit
        mod_res = await bridge.modify_position(
            ticket=exec_res.order_ticket,
            stop_loss=1.0960,
            take_profit=1.1120,
        )
        assert mod_res.success is True

        # 5. Encerra a posição
        close_res = await bridge.close_position(ticket=exec_res.order_ticket)
        assert close_res.success is True

        # Confirma encerramento
        remaining = await bridge.get_open_positions(symbol="EURUSD")
        assert len(remaining) == 0

        await bridge.disconnect()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_fail_closed_on_network_down(self):
        # Aponta para uma porta morta/inexistente com timeout mínimo
        dead_bridge = LinuxMT5BridgeAdapter(
            gateway_url="http://127.0.0.1:59999",
            bridge_token="TEST_HERMES_SECRET_TOKEN_2026",
            timeout_seconds=0.2,
        )

        with pytest.raises(PlatformConnectionError):
            await dead_bridge.connect()

        with pytest.raises(PlatformConnectionError):
            await dead_bridge.get_account_state()

        order_req = OrderRequest(
            auth_id=uuid4(),
            idempotency_key="TEST_FAIL_KEY",
            symbol="EURUSD",
            action="BUY",
            volume=0.10,
            price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            magic=123456,
        )

        with pytest.raises(PlatformConnectionError):
            await dead_bridge.send_order(order_req)
