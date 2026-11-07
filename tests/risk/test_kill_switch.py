"""
QUANT HERMES — Testes da Trava de Emergência Global (Kill Switch)
Arquivo: tests/risk/test_kill_switch.py
"""
import json
import pytest
from uuid import uuid4
from risk.kill_switch import KillSwitch
from execution.adapters.paper import PaperTradingAdapter
from core.models.risk import OrderRequest


@pytest.fixture
def temp_state_file(tmp_path):
    return tmp_path / "test_kill_switch_state.json"


@pytest.fixture
def kill_switch(temp_state_file):
    return KillSwitch(state_file_path=temp_state_file)


class TestKillSwitch:
    """Suíte de testes de integridade e segurança do Kill Switch."""

    def test_initial_state_is_inactive(self, kill_switch):
        assert kill_switch.is_active() is False
        assert kill_switch.reason is None

    def test_engage_activates_and_persists_to_disk(self, kill_switch, temp_state_file):
        kill_switch.engage(reason="DRAWDOWN_EXCEEDED_8_PCT", triggered_by="CIRCUIT_BREAKER")
        assert kill_switch.is_active() is True
        assert kill_switch.reason == "DRAWDOWN_EXCEEDED_8_PCT"
        assert kill_switch.triggered_by == "CIRCUIT_BREAKER"
        assert temp_state_file.exists()

        # Verifica conteúdo JSON no disco
        with open(temp_state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["is_active"] is True
        assert data["reason"] == "DRAWDOWN_EXCEEDED_8_PCT"

    def test_persistence_across_process_restarts(self, temp_state_file):
        # 1. Instância A ativa o kill switch
        ks_a = KillSwitch(state_file_path=temp_state_file)
        ks_a.engage(reason="EMERGENCY_HALT", triggered_by="OPERATOR")

        # 2. Instância B é inicializada simulando reinício do processo
        ks_b = KillSwitch(state_file_path=temp_state_file)
        assert ks_b.is_active() is True
        assert ks_b.reason == "EMERGENCY_HALT"
        assert ks_b.triggered_by == "OPERATOR"

    def test_disengage_rejects_invalid_token(self, kill_switch):
        kill_switch.engage(reason="MANUAL_HALT")
        assert kill_switch.disengage(operator_token="123", reason="Too short") is False
        assert kill_switch.is_active() is True

        assert kill_switch.disengage(operator_token="", reason="Empty") is False
        assert kill_switch.is_active() is True

    def test_disengage_with_valid_operator_token(self, kill_switch, temp_state_file):
        kill_switch.engage(reason="MANUAL_HALT")
        success = kill_switch.disengage(
            operator_token="SECURE_OPERATOR_SIGNATURE_2026",
            reason="Market conditions stabilized after audit",
        )
        assert success is True
        assert kill_switch.is_active() is False
        assert kill_switch.reason is None

        # Confirma que disco foi atualizado
        ks_reopened = KillSwitch(state_file_path=temp_state_file)
        assert ks_reopened.is_active() is False

    def test_fail_safe_on_corrupted_disk_file(self, temp_state_file):
        # Cria arquivo propositalmente quebrado
        with open(temp_state_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_JSON_DATA_---!!!")

        # Nova instância deve acionar postura Fail-Safe (trava ativa)
        ks = KillSwitch(state_file_path=temp_state_file)
        assert ks.is_active() is True
        assert "FAIL_SAFE" in ks.reason

    @pytest.mark.asyncio
    async def test_emergency_liquidation_closes_all_positions(self, kill_switch):
        # 1. Prepara adaptador Paper Trading com 2 posições abertas
        adapter = PaperTradingAdapter(initial_balance=100000.0)
        await adapter.connect()

        # Abre 1ª posição (EURUSD BUY)
        order1 = OrderRequest(
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.50,
            price=1.08500,
            stop_loss=1.08200,
            magic=100001,
            idempotency_key="TEST_EMERGENCY_POS_1",
        )
        res1 = await adapter.send_order(order1)
        assert res1.success is True

        # Abre 2ª posição (XAUUSD BUY)
        order2 = OrderRequest(
            auth_id=uuid4(),
            symbol="XAUUSD",
            action="BUY",
            volume=0.20,
            price=2650.00,
            stop_loss=2640.00,
            magic=100002,
            idempotency_key="TEST_EMERGENCY_POS_2",
        )
        res2 = await adapter.send_order(order2)
        assert res2.success is True

        # Verifica que existem 2 posições em aberto
        positions_before = await adapter.get_open_positions()
        assert len(positions_before) == 2

        # 2. Executa a liquidação compulsória de emergência
        summary = await kill_switch.execute_emergency_liquidation(adapter)

        # 3. Valida resultado
        assert summary["total_open"] == 2
        assert summary["closed"] == 2
        assert summary["failed"] == 0
        assert summary["remaining_open"] == 0
        assert summary["clean_slate"] is True

        positions_after = await adapter.get_open_positions()
        assert len(positions_after) == 0

        await adapter.disconnect()
