"""
QUANT HERMES — TESTES UNITÁRIOS DO SQLITE IDEMPOTENCY STORE
Módulo: tests.unit.test_idempotency_store
"""
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import pytest

from execution.idempotency import (
    IdempotencyViolationError,
    InvalidStateTransitionError,
    OrderLifecycleState,
    SqliteIdempotencyStore,
)


@pytest.fixture
def temp_db_path(tmp_path):
    return tmp_path / "test_idempotency.db"


@pytest.fixture
def store(temp_db_path):
    return SqliteIdempotencyStore(db_path=temp_db_path, timeout_seconds=5.0)


class TestSqliteIdempotencyStore:

    def test_store_initialization_and_integrity(self, store):
        assert store.check_integrity() is True
        assert store.db_path.exists()

    def test_generate_idempotency_key_is_deterministic(self):
        decision_id = uuid4()
        auth_id = uuid4()

        key1 = SqliteIdempotencyStore.generate_idempotency_key(
            symbol="EURUSD",
            action="BUY",
            strategy_id="STRAT_TREND",
            decision_id=decision_id,
            auth_id=auth_id,
        )
        key2 = SqliteIdempotencyStore.generate_idempotency_key(
            symbol="EURUSD",
            action="BUY",
            strategy_id="STRAT_TREND",
            decision_id=decision_id,
            auth_id=auth_id,
        )
        assert key1 == key2
        assert key1.startswith("IDEM_EURUSD_")

    def test_register_intent_pre_submission_success(self, store):
        intent_id = uuid4()
        decision_id = uuid4()
        auth_id = uuid4()
        key = SqliteIdempotencyStore.generate_idempotency_key(
            "EURUSD", "BUY", "STRAT_TREND", decision_id, auth_id
        )

        ok = store.register_intent_pre_submission(
            intent_id=intent_id,
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=auth_id,
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            requested_lot=0.10,
            authorized_lot=0.10,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            magic=10001,
        )
        assert ok is True

        intent = store.get_intent_by_key(key)
        assert intent is not None
        assert intent["intent_id"] == str(intent_id)
        assert intent["state"] == OrderLifecycleState.SUBMITTING.value
        assert intent["symbol"] == "EURUSD"
        assert intent["authorized_lot"] == 0.10

    def test_register_duplicate_key_is_blocked(self, store):
        intent_id1 = uuid4()
        intent_id2 = uuid4()
        decision_id = uuid4()
        auth_id = uuid4()
        key = SqliteIdempotencyStore.generate_idempotency_key(
            "EURUSD", "BUY", "STRAT_MOMENTUM", decision_id, auth_id
        )

        ok1 = store.register_intent_pre_submission(
            intent_id=intent_id1,
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=auth_id,
            strategy_id="STRAT_MOMENTUM",
            symbol="EURUSD",
            action="BUY",
            requested_lot=0.05,
            authorized_lot=0.05,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            magic=10001,
        )
        assert ok1 is True

        # Tentativa de registrar com a mesma chave de idempotência deve falhar (False)
        ok2 = store.register_intent_pre_submission(
            intent_id=intent_id2,
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=auth_id,
            strategy_id="STRAT_MOMENTUM",
            symbol="EURUSD",
            action="BUY",
            requested_lot=0.05,
            authorized_lot=0.05,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            magic=10001,
        )
        assert ok2 is False

    def test_valid_state_transitions(self, store):
        decision_id = uuid4()
        auth_id = uuid4()
        key = SqliteIdempotencyStore.generate_idempotency_key(
            "USDJPY", "SELL", "STRAT_MEAN_REV", decision_id, auth_id
        )

        store.register_intent_pre_submission(
            intent_id=uuid4(),
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=auth_id,
            strategy_id="STRAT_MEAN_REV",
            symbol="USDJPY",
            action="SELL",
            requested_lot=0.20,
            authorized_lot=0.20,
            entry_price=150.00,
            stop_loss=150.50,
            take_profit=149.00,
            magic=10002,
        )

        # Transição válida: SUBMITTING -> SUBMITTED
        store.transition_state(
            idempotency_key=key,
            to_state=OrderLifecycleState.SUBMITTED,
            reason="DISPATCHED_TO_BROKER_SOCKET",
        )
        intent = store.get_intent_by_key(key)
        assert intent["state"] == OrderLifecycleState.SUBMITTED.value

        # Transição válida: SUBMITTED -> FILLED
        store.transition_state(
            idempotency_key=key,
            to_state=OrderLifecycleState.FILLED,
            reason="BROKER_ORDER_EXECUTED",
            order_ticket=998877,
            volume_executed=0.20,
            price_executed=150.01,
            retcode=10009,
        )
        intent = store.get_intent_by_key(key)
        assert intent["state"] == OrderLifecycleState.FILLED.value
        assert intent["order_ticket"] == 998877
        assert intent["volume_executed"] == 0.20

    def test_invalid_state_transition_raises_error(self, store):
        decision_id = uuid4()
        auth_id = uuid4()
        key = SqliteIdempotencyStore.generate_idempotency_key(
            "GBPUSD", "BUY", "STRAT_SMC", decision_id, auth_id
        )

        store.register_intent_pre_submission(
            intent_id=uuid4(),
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=auth_id,
            strategy_id="STRAT_SMC",
            symbol="GBPUSD",
            action="BUY",
            requested_lot=0.10,
            authorized_lot=0.10,
            entry_price=1.2500,
            stop_loss=1.2450,
            take_profit=1.2600,
            magic=10003,
        )

        # Transição para FILLED
        store.transition_state(
            idempotency_key=key,
            to_state=OrderLifecycleState.FILLED,
            reason="EXECUTED",
            order_ticket=12345,
        )

        # Tentativa ilegal: FILLED é terminal, não pode voltar para SUBMITTING
        with pytest.raises(InvalidStateTransitionError):
            store.transition_state(
                idempotency_key=key,
                to_state=OrderLifecycleState.SUBMITTING,
                reason="ILLEGAL_RETRY",
            )

    def test_crash_recovery_preserves_state_across_instances(self, temp_db_path):
        decision_id = uuid4()
        auth_id = uuid4()
        key = SqliteIdempotencyStore.generate_idempotency_key(
            "XAUUSD", "BUY", "STRAT_MACRO", decision_id, auth_id
        )

        # Instância 1 registra a ordem e sofre crash enquanto estava em SUBMITTING
        store1 = SqliteIdempotencyStore(db_path=temp_db_path)
        store1.register_intent_pre_submission(
            intent_id=uuid4(),
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=auth_id,
            strategy_id="STRAT_MACRO",
            symbol="XAUUSD",
            action="BUY",
            requested_lot=0.01,
            authorized_lot=0.01,
            entry_price=2650.0,
            stop_loss=2640.0,
            take_profit=2670.0,
            magic=10004,
        )
        del store1  # Simula processo morrendo

        # Instância 2 (novo processo reiniciado)
        store2 = SqliteIdempotencyStore(db_path=temp_db_path)
        unresolved = store2.get_unresolved_intents()
        assert len(unresolved) == 1
        assert unresolved[0]["idempotency_key"] == key
        assert unresolved[0]["state"] == OrderLifecycleState.SUBMITTING.value

        # Re-submissão cega deve ser rejeitada pela restrição do banco
        ok = store2.register_intent_pre_submission(
            intent_id=uuid4(),
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=auth_id,
            strategy_id="STRAT_MACRO",
            symbol="XAUUSD",
            action="BUY",
            requested_lot=0.01,
            authorized_lot=0.01,
            entry_price=2650.0,
            stop_loss=2640.0,
            take_profit=2670.0,
            magic=10004,
        )
        assert ok is False

    def test_multi_threaded_concurrency_exact_single_winner(self, temp_db_path):
        """Testa 10 threads simultâneas tentando registrar a mesma intenção."""
        store = SqliteIdempotencyStore(db_path=temp_db_path)
        decision_id = uuid4()
        auth_id = uuid4()
        key = SqliteIdempotencyStore.generate_idempotency_key(
            "EURUSD", "BUY", "CONCURRENT_TEST", decision_id, auth_id
        )

        def attempt_insert(thread_idx: int) -> bool:
            return store.register_intent_pre_submission(
                intent_id=uuid4(),
                idempotency_key=key,
                decision_id=decision_id,
                auth_id=auth_id,
                strategy_id="CONCURRENT_TEST",
                symbol="EURUSD",
                action="BUY",
                requested_lot=0.10,
                authorized_lot=0.10,
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit=1.1100,
                magic=555,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_insert, i) for i in range(10)]
            results = [f.result() for f in futures]

        # Exatamente UMA thread deve ter vencido (True) e 9 devem ter falhado (False)
        assert results.count(True) == 1
        assert results.count(False) == 9

