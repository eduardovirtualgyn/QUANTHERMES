"""
QUANT HERMES — TESTES DA API E DASHBOARD DE MONITORAMENTO
Módulo: tests.unit.test_monitoring_api
"""
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from core.models.risk import RiskAuthorization, TradeProposal
from execution.adapters.paper import PaperTradingAdapter
from execution.order_executor import OrderExecutor
from monitoring.server import create_monitoring_app
from monitoring.telemetry import TelemetryProvider
from risk.engine import RiskEngine


@pytest.fixture
async def temp_environment():
    temp_dir = tempfile.mkdtemp()
    ks_path = Path("data/storage/kill_switch_state.json")
    if ks_path.exists():
        ks_path.unlink(missing_ok=True)

    adapter = PaperTradingAdapter(initial_balance=10000.0)
    await adapter.connect()

    os.environ["HERMES_OPERATOR_TOKEN"] = "HERMES_OPERATOR_TEST_TOKEN"
    risk_engine = RiskEngine()
    provider = TelemetryProvider(adapter=adapter, risk_engine=risk_engine)
    app = create_monitoring_app(provider=provider, operator_token="HERMES_OPERATOR_TEST_TOKEN")

    client = TestClient(app)
    yield client, adapter, risk_engine, provider

    await adapter.disconnect()
    if ks_path.exists():
        ks_path.unlink(missing_ok=True)
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestMonitoringAPI:

    @pytest.mark.asyncio
    async def test_health_endpoint(self, temp_environment):
        client, _, _, _ = temp_environment
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "HEALTHY"
        assert data["adapter_connected"] is True
        assert data["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_account_endpoint(self, temp_environment):
        client, _, _, _ = temp_environment
        response = client.get("/api/v1/account")

        assert response.status_code == 200
        data = response.json()
        assert data["balance"] == 10000.0
        assert data["equity"] == 10000.0
        assert data["currency"] == "USD"
        assert "daily_pnl_pct" in data

    @pytest.mark.asyncio
    async def test_positions_endpoint_with_active_position(self, temp_environment):
        client, adapter, _, _ = temp_environment

        # Cria e executa uma ordem legítima para ter posição aberta
        executor = OrderExecutor(adapter=adapter)
        dec_id = uuid4()
        proposal = TradeProposal(
            decision_id=dec_id,
            strategy_id="STRAT_TEST",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        auth = RiskAuthorization(
            decision_id=dec_id,
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.10,
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        await executor.execute_order(proposal, auth)

        response = client.get("/api/v1/positions")
        assert response.status_code == 200
        positions = response.json()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "EURUSD"
        assert positions[0]["volume"] == 0.10

    @pytest.mark.asyncio
    async def test_risk_status_and_circuit_breakers(self, temp_environment):
        client, _, _, _ = temp_environment
        response = client.get("/api/v1/risk/status")

        assert response.status_code == 200
        data = response.json()
        assert data["kill_switch"]["is_active"] is False
        assert "circuit_breakers" in data
        assert data["circuit_breakers"]["daily_loss_guard"]["limit_pct"] == 1.50
        assert data["circuit_breakers"]["weekly_loss_guard"]["limit_pct"] == 3.00

    @pytest.mark.asyncio
    async def test_kill_switch_engage_and_disengage(self, temp_environment):
        client, _, risk_engine, _ = temp_environment

        auth = {"Authorization": "Bearer HERMES_OPERATOR_TEST_TOKEN"}

        # 1. Sem token o acionamento é recusado
        missing = client.post(
            "/api/v1/risk/kill-switch/engage",
            json={"reason": "Alerta de volatilidade extrema", "operator": "OPERATOR_ADMIN"},
        )
        assert missing.status_code == 401

        # 2. Aciona o Kill Switch com o token
        engage_resp = client.post(
            "/api/v1/risk/kill-switch/engage",
            headers=auth,
            json={"reason": "Alerta de volatilidade extrema", "operator": "OPERATOR_ADMIN"},
        )
        assert engage_resp.status_code == 200
        assert engage_resp.json()["status"] == "EMERGENCY_HALT"
        assert risk_engine.kill_switch.is_active() is True

        # 3. Sem cabeçalho, o desarme também é 401
        missing_disengage = client.post(
            "/api/v1/risk/kill-switch/disengage",
            json={"operator_token": "HERMES_OPERATOR_TEST_TOKEN"},
        )
        assert missing_disengage.status_code == 401

        # 4. Cabeçalho válido, token de corpo incorreto
        bad_token_resp = client.post(
            "/api/v1/risk/kill-switch/disengage",
            headers=auth,
            json={"operator_token": "WRONG_TOKEN_123"},
        )
        assert bad_token_resp.status_code == 403

        # 5. Desarma com o token de operador válido
        valid_token_resp = client.post(
            "/api/v1/risk/kill-switch/disengage",
            headers=auth,
            json={"operator_token": "HERMES_OPERATOR_TEST_TOKEN"},
        )
        assert valid_token_resp.status_code == 200
        assert risk_engine.kill_switch.is_active() is False

    @pytest.mark.asyncio
    async def test_dashboard_html_rendering(self, temp_environment):
        client, _, _, _ = temp_environment
        response = client.get("/dashboard")

        assert response.status_code == 200
        assert "QUANT HERMES" in response.text
        assert "KILL SWITCH" in response.text
        assert "Circuit Breakers Soberanos" in response.text

    @pytest.mark.asyncio
    async def test_websocket_telemetry_streaming(self, temp_environment):
        client, _, _, _ = temp_environment

        with client.websocket_connect("/ws/telemetry") as websocket:
            data = websocket.receive_json()
            assert "health" in data
            assert "account" in data
            assert "positions" in data
            assert "risk" in data
            assert data["account"]["balance"] == 10000.0

