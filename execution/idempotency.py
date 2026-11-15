"""
QUANT HERMES — ARMAZENAMENTO PERSISTENTE DE IDEMPOTÊNCIA E ESTADOS DE ORDEM
Módulo: execution.idempotency

Responsabilidade:
- Armazenamento transacional durável de intenções de ordens em SQLite WAL.
- Eliminação da vulnerabilidade de idempotência volátil em memória RAM.
- Garantia de identidade única e imutável para cada intenção operacional.
- Registro transacional da máquina de estados (antes, durante e após despacho ao broker).
- Suporte a recuperação pós-falha (crash recovery) e reconciliação de ordens ambíguas.
- Postura estrita Fail-Closed: se o armazenamento persistente falhar, nenhuma ordem é enviada.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple
from uuid import UUID

from core.logger import get_logger
from core.models.base import utc_now

logger = get_logger("execution.idempotency")


class OrderLifecycleState(str, Enum):
    """
    Máquina de estados explícita e persistente para o ciclo de vida de uma ordem.
    """
    RECEIVED = "RECEIVED"                         # Intenção recebida pelo subsistema de execução
    AUTHORIZED = "AUTHORIZED"                     # Autorização formal e válida do Risk Engine confirmada
    PERSISTED = "PERSISTED"                       # Intenção gravada duravelmente no banco de dados
    SUBMITTING = "SUBMITTING"                     # Ordem prestes a ser despachada para o adapter (pré-socket)
    SUBMITTED = "SUBMITTED"                       # Ordem despachada para o socket/API do broker
    ACKNOWLEDGED = "ACKNOWLEDGED"                 # Broker confirmou recebimento da ordem
    PARTIALLY_FILLED = "PARTIALLY_FILLED"         # Preenchimento parcial do volume autorizado
    FILLED = "FILLED"                             # Ordem totalmente executada no mercado
    REJECTED = "REJECTED"                         # Ordem rejeitada pelo broker ou pelo adapter
    CANCEL_PENDING = "CANCEL_PENDING"             # Solicitação de cancelamento em processamento
    CANCELLED = "CANCELLED"                       # Ordem cancelada com sucesso
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"  # Estado ambíguo (timeout, crash ou desconexão)
    FAILED = "FAILED"                             # Falha interna catastrófica não recuperável


# Transições válidas permitidas na máquina de estados
VALID_STATE_TRANSITIONS: Dict[OrderLifecycleState, Set[OrderLifecycleState]] = {
    OrderLifecycleState.RECEIVED: {
        OrderLifecycleState.AUTHORIZED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.FAILED,
    },
    OrderLifecycleState.AUTHORIZED: {
        OrderLifecycleState.PERSISTED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.FAILED,
    },
    OrderLifecycleState.PERSISTED: {
        OrderLifecycleState.SUBMITTING,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.FAILED,
    },
    OrderLifecycleState.SUBMITTING: {
        OrderLifecycleState.SUBMITTED,
        OrderLifecycleState.ACKNOWLEDGED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.RECONCILIATION_REQUIRED,
        OrderLifecycleState.FAILED,
    },
    OrderLifecycleState.SUBMITTED: {
        OrderLifecycleState.ACKNOWLEDGED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.CANCEL_PENDING,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.RECONCILIATION_REQUIRED,
        OrderLifecycleState.FAILED,
    },
    OrderLifecycleState.ACKNOWLEDGED: {
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.CANCEL_PENDING,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.RECONCILIATION_REQUIRED,
    },
    OrderLifecycleState.PARTIALLY_FILLED: {
        OrderLifecycleState.FILLED,
        OrderLifecycleState.CANCEL_PENDING,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.RECONCILIATION_REQUIRED,
    },
    OrderLifecycleState.CANCEL_PENDING: {
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.FILLED,  # Pode ser preenchida antes do cancelamento chegar
        OrderLifecycleState.RECONCILIATION_REQUIRED,
    },
    OrderLifecycleState.RECONCILIATION_REQUIRED: {
        OrderLifecycleState.ACKNOWLEDGED,
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.FAILED,
    },
    # Estados terminais:
    OrderLifecycleState.FILLED: set(),
    OrderLifecycleState.REJECTED: set(),
    OrderLifecycleState.CANCELLED: set(),
    OrderLifecycleState.FAILED: set(),
}


class InvalidStateTransitionError(Exception):
    """Exceção levantada quando ocorre uma tentativa de transição ilegal de estado."""
    pass


class IdempotencyViolationError(Exception):
    """Exceção levantada quando uma ordem duplicada tenta ser inserida ou processada."""
    pass


class StoreCorruptedError(Exception):
    """Exceção levantada quando o banco de dados apresenta corrupção física ou estrutural."""
    pass


class SqliteIdempotencyStore:
    """
    Gerenciador transacional de idempotência e auditoria de ordens baseado em SQLite WAL.
    Garante persistência atômica e recuperação após interrupções de processo (crash).
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        db_path: str | Path = "data/storage/idempotency.db",
        timeout_seconds: float = 10.0,
        retention_window_seconds: int = 86400,  # 24 horas padrão para histórico
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.retention_window_seconds = retention_window_seconds
        self._lock = threading.RLock()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Abre uma conexão isolada com configurações de segurança e WAL."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.timeout_seconds,
            isolation_level=None,  # Controle manual de transações via BEGIN/COMMIT
        )
        conn.row_factory = sqlite3.Row
        # Configurações do motor SQLite para alta durabilidade e concorrência
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=FULL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=10000;")
        return conn

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Gerenciador de contexto para transações explícitas ACID."""
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Inicializa as tabelas, índices e restrições de unicidade."""
        with self._lock:
            with self._transaction() as conn:
                # 1. Tabela de Metadados / Versão
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )

                # 2. Tabela Principal de Ordens e Idempotência
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS order_intents (
                        intent_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        decision_id TEXT NOT NULL,
                        auth_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        action TEXT NOT NULL,
                        requested_lot REAL NOT NULL,
                        authorized_lot REAL NOT NULL,
                        entry_price REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        take_profit REAL NOT NULL,
                        magic INTEGER NOT NULL,
                        state TEXT NOT NULL,
                        attempts_count INTEGER NOT NULL DEFAULT 0,
                        order_ticket INTEGER DEFAULT 0,
                        deal_ticket INTEGER DEFAULT 0,
                        volume_executed REAL DEFAULT 0.0,
                        price_executed REAL DEFAULT 0.0,
                        retcode INTEGER DEFAULT 0,
                        broker_comment TEXT DEFAULT '',
                        last_error TEXT DEFAULT '',
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL,
                        expires_at_utc TEXT NOT NULL
                    );
                    """
                )

                # 3. Índices para Otimização de Consultas de Reconciliação
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_order_intents_state 
                    ON order_intents(state);
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_order_intents_symbol 
                    ON order_intents(symbol);
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_order_intents_ticket 
                    ON order_intents(order_ticket);
                    """
                )

                # 4. Tabela de Auditoria de Transições de Estado (Audit Log)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS order_state_transitions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        intent_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        from_state TEXT NOT NULL,
                        to_state TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        transitioned_at_utc TEXT NOT NULL,
                        FOREIGN KEY (intent_id) REFERENCES order_intents(intent_id) ON DELETE CASCADE
                    );
                    """
                )

                conn.execute(
                    """
                    INSERT OR REPLACE INTO schema_meta (key, value, updated_at)
                    VALUES ('version', ?, ?)
                    """,
                    (str(self.SCHEMA_VERSION), utc_now().isoformat()),
                )

    @staticmethod
    def generate_idempotency_key(
        symbol: str,
        action: str,
        strategy_id: str,
        decision_id: UUID | str,
        auth_id: UUID | str,
    ) -> str:
        """
        Gera a identidade idempotente estável e verificável de uma operação.
        A identidade NÃO muda com reinicializações ou novos UUIDs de requisição.
        """
        payload = f"{symbol.upper()}:{action.upper()}:{strategy_id}:{str(decision_id)}:{str(auth_id)}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"IDEM_{symbol.upper()}_{digest[:16]}"

    def register_intent_pre_submission(
        self,
        intent_id: UUID | str,
        idempotency_key: str,
        decision_id: UUID | str,
        auth_id: UUID | str,
        strategy_id: str,
        symbol: str,
        action: str,
        requested_lot: float,
        authorized_lot: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        magic: int,
    ) -> bool:
        """
        Registra atomicamente a intenção antes do envio físico ao socket.
        Retorna True se registrada com sucesso.
        Retorna False se já existir (duplicação detectada).
        """
        now = utc_now()
        now_str = now.isoformat()
        expires_str = datetime.fromtimestamp(now.timestamp() + self.retention_window_seconds, tz=timezone.utc).isoformat()

        with self._lock:
            try:
                with self._transaction() as conn:
                    # Checa duplicidade antes de inserir
                    cursor = conn.execute(
                        "SELECT intent_id, state FROM order_intents WHERE idempotency_key = ?",
                        (idempotency_key,),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        logger.warning(
                            "Tentativa de inserção duplicada bloqueada por Idempotência",
                            extra={
                                "idempotency_key": idempotency_key,
                                "existing_intent_id": row["intent_id"],
                                "existing_state": row["state"],
                            },
                        )
                        return False

                    # Insere intenção em estado SUBMITTING
                    conn.execute(
                        """
                        INSERT INTO order_intents (
                            intent_id, idempotency_key, decision_id, auth_id, strategy_id,
                            symbol, action, requested_lot, authorized_lot, entry_price,
                            stop_loss, take_profit, magic, state, attempts_count,
                            created_at_utc, updated_at_utc, expires_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                        """,
                        (
                            str(intent_id),
                            idempotency_key,
                            str(decision_id),
                            str(auth_id),
                            strategy_id,
                            symbol.upper(),
                            action.upper(),
                            float(requested_lot),
                            float(authorized_lot),
                            float(entry_price),
                            float(stop_loss),
                            float(take_profit),
                            int(magic),
                            OrderLifecycleState.SUBMITTING.value,
                            now_str,
                            now_str,
                            expires_str,
                        ),
                    )

                    # Registra a transição inicial no log de auditoria
                    conn.execute(
                        """
                        INSERT INTO order_state_transitions (
                            intent_id, idempotency_key, from_state, to_state, reason, details_json, transitioned_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(intent_id),
                            idempotency_key,
                            OrderLifecycleState.AUTHORIZED.value,
                            OrderLifecycleState.SUBMITTING.value,
                            "PRE_SUBMISSION_REGISTRATION",
                            json.dumps({"authorized_lot": authorized_lot, "entry_price": entry_price}),
                            now_str,
                        ),
                    )
                    return True
            except sqlite3.IntegrityError as e:
                logger.warning(
                    "Violação de integridade ao registrar ordem (possível concorrência)",
                    extra={"idempotency_key": idempotency_key, "error": str(e)},
                )
                return False
            except Exception as e:
                logger.critical(
                    "FALHA CRÍTICA AO REGISTRAR INTENÇÃO NO BANCO (FAIL-CLOSED)",
                    extra={"idempotency_key": idempotency_key, "error": str(e)},
                )
                raise StoreCorruptedError(f"Database write failure: {e}") from e

    def transition_state(
        self,
        idempotency_key: str,
        to_state: OrderLifecycleState,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
        order_ticket: Optional[int] = None,
        deal_ticket: Optional[int] = None,
        volume_executed: Optional[float] = None,
        price_executed: Optional[float] = None,
        retcode: Optional[int] = None,
        broker_comment: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> None:
        """
        Atualiza o estado de uma ordem de forma atômica e valida a transição na máquina de estados.
        """
        now_str = utc_now().isoformat()
        details_str = json.dumps(details or {})

        with self._lock:
            with self._transaction() as conn:
                cursor = conn.execute(
                    "SELECT intent_id, state FROM order_intents WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(f"Idempotency key not found: {idempotency_key}")

                current_state = OrderLifecycleState(row["state"])
                intent_id = row["intent_id"]

                # Valida se a transição é constitucionalmente legal
                allowed_transitions = VALID_STATE_TRANSITIONS.get(current_state, set())
                if to_state not in allowed_transitions and current_state != to_state:
                    err_msg = f"Transição ilegal de estado para ordem {idempotency_key}: {current_state} -> {to_state}"
                    logger.error(err_msg, extra={"intent_id": intent_id, "allowed": [s.value for s in allowed_transitions]})
                    raise InvalidStateTransitionError(err_msg)

                # Monta query dinâmica de atualização
                updates = ["state = ?", "updated_at_utc = ?"]
                params: List[Any] = [to_state.value, now_str]

                if order_ticket is not None:
                    updates.append("order_ticket = ?")
                    params.append(int(order_ticket))
                if deal_ticket is not None:
                    updates.append("deal_ticket = ?")
                    params.append(int(deal_ticket))
                if volume_executed is not None:
                    updates.append("volume_executed = ?")
                    params.append(float(volume_executed))
                if price_executed is not None:
                    updates.append("price_executed = ?")
                    params.append(float(price_executed))
                if retcode is not None:
                    updates.append("retcode = ?")
                    params.append(int(retcode))
                if broker_comment is not None:
                    updates.append("broker_comment = ?")
                    params.append(str(broker_comment))
                if last_error is not None:
                    updates.append("last_error = ?")
                    params.append(str(last_error))

                params.append(idempotency_key)
                update_sql = f"UPDATE order_intents SET {', '.join(updates)} WHERE idempotency_key = ?"
                conn.execute(update_sql, tuple(params))

                # Registra no histórico de auditoria
                conn.execute(
                    """
                    INSERT INTO order_state_transitions (
                        intent_id, idempotency_key, from_state, to_state, reason, details_json, transitioned_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent_id,
                        idempotency_key,
                        current_state.value,
                        to_state.value,
                        reason,
                        details_str,
                        now_str,
                    ),
                )

    def get_intent_by_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Recupera os detalhes completos de uma intenção pelo seu identificador idempotente."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM order_intents WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                row = cursor.fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

    def get_unresolved_intents(self) -> List[Dict[str, Any]]:
        """
        Retorna todas as intenções que não estão em estado terminal.
        Essencial para o protocolo de recuperação de crash na inicialização.
        """
        terminal_states = (
            OrderLifecycleState.FILLED.value,
            OrderLifecycleState.REJECTED.value,
            OrderLifecycleState.CANCELLED.value,
            OrderLifecycleState.FAILED.value,
        )
        placeholders = ", ".join("?" for _ in terminal_states)

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    f"SELECT * FROM order_intents WHERE state NOT IN ({placeholders}) ORDER BY created_at_utc ASC",
                    terminal_states,
                )
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

    def check_integrity(self) -> bool:
        """Executa verificação de integridade física no arquivo SQLite (PRAGMA integrity_check)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("PRAGMA integrity_check;")
                result = cursor.fetchone()
                return result[0].lower() == "ok" if result else False
            except Exception as e:
                logger.critical("Falha ao checar integridade do banco SQLite", extra={"error": str(e)})
                return False
            finally:
                conn.close()

    def cleanup_expired_records(self) -> int:
        """Remove registros com data de expiração ultrapassada e que já estão em estado terminal."""
        now_str = utc_now().isoformat()
        terminal_states = (
            OrderLifecycleState.FILLED.value,
            OrderLifecycleState.REJECTED.value,
            OrderLifecycleState.CANCELLED.value,
            OrderLifecycleState.FAILED.value,
        )
        placeholders = ", ".join("?" for _ in terminal_states)

        with self._lock:
            with self._transaction() as conn:
                cursor = conn.execute(
                    f"""
                    DELETE FROM order_intents 
                    WHERE expires_at_utc < ? AND state IN ({placeholders})
                    """,
                    (now_str, *terminal_states),
                )
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info("Registros expirados limpos do store de idempotência", extra={"count": deleted})
                return deleted

