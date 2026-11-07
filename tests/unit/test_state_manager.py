"""
QUANT HERMES — TESTES DO GERENCIADOR DE ESTADO
Módulo: tests.unit.test_state_manager
"""
import shutil
import tempfile
from pathlib import Path
import pytest

from execution.state_manager import ExecutionState, ExecutionStateManager


@pytest.fixture
def temp_state_file():
    temp_dir = tempfile.mkdtemp()
    state_file = Path(temp_dir) / "test_execution_state.json"
    yield str(state_file)
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestExecutionStateManager:

    def test_save_and_load_state_atomic(self, temp_state_file):
        mgr = ExecutionStateManager(storage_path=temp_state_file)
        state = ExecutionState(
            system_status="RUNNING",
            active_symbols=["EURUSD", "XAUUSD"],
            tracked_tickets=[101, 102, 103],
            daily_trades_count=3,
            daily_realized_pnl=150.0,
        )

        mgr.save_state(state)
        assert Path(temp_state_file).exists()

        # Cria nova instância e carrega do disco
        new_mgr = ExecutionStateManager(storage_path=temp_state_file)
        loaded = new_mgr.load_state()

        assert loaded is not None
        assert loaded.system_status == "RUNNING"
        assert loaded.tracked_tickets == [101, 102, 103]
        assert loaded.daily_trades_count == 3
        assert loaded.daily_realized_pnl == 150.0

    def test_add_and_remove_tracked_ticket(self, temp_state_file):
        mgr = ExecutionStateManager(storage_path=temp_state_file)
        mgr.add_tracked_ticket(555)
        mgr.add_tracked_ticket(777)

        assert 555 in mgr.current_state.tracked_tickets
        assert 777 in mgr.current_state.tracked_tickets

        # Remove
        mgr.remove_tracked_ticket(555)
        assert 555 not in mgr.current_state.tracked_tickets
        assert 777 in mgr.current_state.tracked_tickets

        # Valida que persistiu no disco
        reloaded = ExecutionStateManager(storage_path=temp_state_file).load_state()
        assert reloaded.tracked_tickets == [777]

    def test_load_non_existent_returns_none(self, temp_state_file):
        mgr = ExecutionStateManager(storage_path=temp_state_file)
        assert mgr.load_state() is None

    def test_corrupted_file_handles_gracefully(self, temp_state_file):
        # Escreve lixo no arquivo
        with open(temp_state_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_JSON_DATA{{{{")

        mgr = ExecutionStateManager(storage_path=temp_state_file)
        loaded = mgr.load_state()
        assert loaded is None

