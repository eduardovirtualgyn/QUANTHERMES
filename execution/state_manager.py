"""
QUANT HERMES — GERENCIADOR DE ESTADO OPERACIONAL
Módulo: execution.state_manager

Responsabilidade:
- Persistência e recuperação atômica do estado de execução do QUANT HERMES.
- Rastreamento resiliente de posições ativas, histórico diário e integridade operacional.
- Prevenção contra corrupção de arquivos via escrita atômica com arquivo temporário e rename.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger

logger = get_logger("state_manager")


@dataclass
class ExecutionState:
    """Estrutura imutável do estado operacional em execução."""
    system_status: str
    active_symbols: List[str]
    tracked_tickets: List[int] = field(default_factory=list)
    daily_trades_count: int = 0
    daily_realized_pnl: float = 0.0
    last_reconciliation_utc: Optional[str] = None
    last_saved_utc: Optional[str] = None


class ExecutionStateManager:
    """
    Gerenciador de estado com persistência em disco.
    Assegura que o sistema retome o controle exato de suas posições após qualquer reinicialização.
    """

    def __init__(self, storage_path: str = "data/storage/execution_state.json") -> None:
        self.storage_file = Path(storage_path)
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        self.current_state = ExecutionState(
            system_status="INITIALIZING",
            active_symbols=["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
        )

    def save_state(self, state: Optional[ExecutionState] = None) -> None:
        """
        Salva o estado no disco de forma atômica utilizando escrita temporária e rename.
        """
        if state is not None:
            self.current_state = state

        self.current_state.last_saved_utc = datetime.now(timezone.utc).isoformat()
        state_dict = asdict(self.current_state)

        tmp_file = self.storage_file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, indent=2)

            # Substituição atômica no sistema de arquivos
            os.replace(tmp_file, self.storage_file)
            logger.debug(
                "Estado operacional salvo com sucesso",
                extra={"status": self.current_state.system_status, "tracked": len(self.current_state.tracked_tickets)},
            )
        except Exception as e:
            logger.critical("Falha ao salvar estado operacional em disco", extra={"error": str(e)})
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)
            raise

    def load_state(self) -> Optional[ExecutionState]:
        """
        Carrega o estado operacional persistido em disco.
        Retorna None se o arquivo não existir ou estiver corrompido.
        """
        if not self.storage_file.exists():
            return None

        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.current_state = ExecutionState(
                system_status=data.get("system_status", "STOPPED"),
                active_symbols=data.get("active_symbols", ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]),
                tracked_tickets=data.get("tracked_tickets", []),
                daily_trades_count=data.get("daily_trades_count", 0),
                daily_realized_pnl=data.get("daily_realized_pnl", 0.0),
                last_reconciliation_utc=data.get("last_reconciliation_utc"),
                last_saved_utc=data.get("last_saved_utc"),
            )
            logger.info(
                "Estado operacional restaurado do disco",
                extra={
                    "status": self.current_state.system_status,
                    "tracked_tickets": self.current_state.tracked_tickets,
                },
            )
            return self.current_state
        except Exception as e:
            logger.error("Erro ao carregar estado operacional em disco", extra={"error": str(e)})
            return None

    def add_tracked_ticket(self, ticket: int) -> None:
        """Adiciona um ticket ao rol de posições monitoradas e salva."""
        if ticket not in self.current_state.tracked_tickets:
            self.current_state.tracked_tickets.append(ticket)
            self.save_state()

    def remove_tracked_ticket(self, ticket: int) -> None:
        """Remove um ticket após fechamento e salva."""
        if ticket in self.current_state.tracked_tickets:
            self.current_state.tracked_tickets.remove(ticket)
            self.save_state()

    def update_reconciliation_timestamp(self) -> None:
        """Atualiza o timestamp da última reconciliação."""
        self.current_state.last_reconciliation_utc = datetime.now(timezone.utc).isoformat()
        self.save_state()

    def clear(self) -> None:
        """Remove o arquivo de estado em encerramentos completos."""
        if self.storage_file.exists():
            self.storage_file.unlink(missing_ok=True)

