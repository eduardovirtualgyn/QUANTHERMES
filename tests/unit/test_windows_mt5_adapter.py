"""
Testes Unitários do Adaptador Windows MT5 (Mocked COM Worker)
Arquivo: tests/unit/test_windows_mt5_adapter.py
"""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from core.models.risk import OrderRequest
from execution.adapters.windows_mt5 import WindowsMT5Adapter


@pytest.mark.asyncio
class TestWindowsMT5Adapter:
    """Valida a camada de execução MT5 no Windows garantindo os padrões de segurança."""

    async def test_symbol_alias_resolution(self):
        adapter = WindowsMT5Adapter(
            symbol_aliases={"EURUSD": "EURUSD_i", "XAUUSD": "GOLD.m"}
        )
        assert adapter._resolve_symbol("EURUSD") == "EURUSD_i"
        assert adapter._resolve_symbol("XAUUSD") == "GOLD.m"
        assert adapter._resolve_symbol("GBPUSD") == "GBPUSD"  # Sem alias

    @patch("execution.adapters.windows_mt5.mt5")
    async def test_successful_connect(self, mock_mt5):
        pytest.importorskip(
            "MetaTrader5",
            reason="Pacote MetaTrader5 é exclusivo do Windows e não está instalado neste ambiente",
        )
        mock_mt5.initialize.return_value = True
        mock_terminal_info = MagicMock()
        mock_terminal_info.trade_allowed = True
        mock_terminal_info.connected = True
        mock_mt5.terminal_info.return_value = mock_terminal_info

        adapter = WindowsMT5Adapter(login=12345, server="Demo-Server")
        connected = await adapter.connect()

        assert connected is True
        assert adapter._connected is True
        mock_mt5.initialize.assert_called_once()

    @patch("execution.adapters.windows_mt5.mt5")
    async def test_send_order_success(self, mock_mt5):
        adapter = WindowsMT5Adapter()
        adapter._connected = True

        mock_sym_info = MagicMock()
        mock_sym_info.filling_mode = 2  # IOC
        mock_mt5.symbol_info.return_value = mock_sym_info

        mock_order_result = MagicMock()
        mock_order_result.retcode = 10009  # TRADE_RETCODE_DONE
        mock_order_result.order = 888123
        mock_order_result.deal = 999123
        mock_order_result.volume = 0.50
        mock_order_result.price = 1.08500
        mock_order_result.comment = "Done"
        mock_mt5.order_send.return_value = mock_order_result
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.ORDER_TYPE_BUY = 0
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.ORDER_FILLING_IOC = 1

        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.50,
            price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09000,
            magic=777,
            idempotency_key="mt5_exec_001",
        )

        res = await adapter.send_order(req)
        assert res.success is True
        assert res.retcode == 10009
        assert res.order_ticket == 888123
        assert res.deal_ticket == 999123

    @patch("execution.adapters.windows_mt5.mt5")
    async def test_idempotency_prevents_duplicate_mt5_call(self, mock_mt5):
        adapter = WindowsMT5Adapter()
        adapter._connected = True

        mock_sym_info = MagicMock()
        mock_sym_info.filling_mode = 2
        mock_mt5.symbol_info.return_value = mock_sym_info

        mock_res = MagicMock()
        mock_res.retcode = 10009
        mock_res.order = 111222
        mock_res.deal = 333444
        mock_res.volume = 0.10
        mock_res.price = 1.08500
        mock_res.comment = "OK"
        mock_mt5.order_send.return_value = mock_res
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.ORDER_TYPE_BUY = 0
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.ORDER_FILLING_IOC = 1

        req = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.10,
            price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09000,
            magic=777,
            idempotency_key="idempotent_mt5_key",
        )

        res1 = await adapter.send_order(req)
        res2 = await adapter.send_order(req)

        # O mt5.order_send deve ter sido chamado exatamente UMA vez
        assert mock_mt5.order_send.call_count == 1
        assert res1.order_ticket == res2.order_ticket

