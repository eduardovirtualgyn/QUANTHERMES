"""
QUANT HERMES — Reconciliador de Posições (Position Reconciler)
Módulo: portfolio.reconciler
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from core.logger import get_logger
from core.models.base import utc_now
from core.models.risk import Position
from execution.adapters.base import TradingPlatformAdapter

logger = get_logger("portfolio.reconciler")


@dataclass
class ReconciliationReport:
    """Relatório detalhado de reconciliação entre estado interno e terminal MT5."""
    is_synced: bool
    orphaned_tickets: List[int] = field(default_factory=list)
    ghost_tickets: List[int] = field(default_factory=list)
    sl_mismatches: List[Dict[str, float]] = field(default_factory=list)
    total_broker_positions: int = 0
    total_internal_positions: int = 0
    reconciled_at: datetime = field(default_factory=utc_now)


class PositionReconciler:
    """
    Reconciliador autônomo de posições e integridade de ordens.
    Garante:
    1. Detecção de posições órfãs (abertas no broker sem registro interno do sistema).
    2. Detecção de posições fantasma (registradas no sistema mas fechadas no broker por SL/TP).
    3. Correção e alinhamento de Stop Loss e Take Profit desincronizados via adapter.modify_position.
    4. Postura Fail-Safe em caso de divergência crítica.
    """

    def __init__(self, sl_tolerance_points: float = 0.0001):
        self.sl_tolerance_points = sl_tolerance_points

    async def reconcile(
        self,
        adapter: TradingPlatformAdapter,
        internal_registry: Dict[int, Position],
        auto_correct_stops: bool = True,
    ) -> ReconciliationReport:
        """
        Executa a reconciliação completa entre o estado do broker e o registro interno.
        """
        broker_positions = await adapter.get_open_positions()
        broker_map = {pos.ticket: pos for pos in broker_positions}

        orphaned_tickets: List[int] = []
        ghost_tickets: List[int] = []
        sl_mismatches: List[Dict[str, float]] = []

        # 1. Checa posições do broker contra registro interno (Detecta Órfãs)
        for ticket, b_pos in broker_map.items():
            if ticket not in internal_registry:
                orphaned_tickets.append(ticket)
                logger.critical(
                    "ORPHANED_POSITION_DETECTED",
                    ticket=ticket,
                    symbol=b_pos.symbol,
                    volume=b_pos.volume,
                    magic=b_pos.magic,
                )
            else:
                # Compara alinhamento do Stop Loss
                i_pos = internal_registry[ticket]
                if abs(b_pos.stop_loss - i_pos.stop_loss) > self.sl_tolerance_points:
                    mismatch = {
                        "ticket": ticket,
                        "broker_sl": b_pos.stop_loss,
                        "internal_sl": i_pos.stop_loss,
                    }
                    sl_mismatches.append(mismatch)
                    logger.warning("sl_mismatch_detected", **mismatch)

                    # Auto-correção mandando modificar no broker
                    if auto_correct_stops and i_pos.stop_loss > 0:
                        logger.info("auto_correcting_broker_stop_loss", ticket=ticket, target_sl=i_pos.stop_loss)
                        await adapter.modify_position(
                            ticket=ticket,
                            stop_loss=i_pos.stop_loss,
                            take_profit=i_pos.take_profit,
                        )

        # 2. Checa posições internas contra broker (Detecta Fantasmas)
        for ticket, i_pos in internal_registry.items():
            if ticket not in broker_map:
                ghost_tickets.append(ticket)
                logger.info(
                    "ghost_position_detected_broker_closed",
                    ticket=ticket,
                    symbol=i_pos.symbol,
                )

        is_synced = len(orphaned_tickets) == 0 and len(ghost_tickets) == 0 and len(sl_mismatches) == 0

        report = ReconciliationReport(
            is_synced=is_synced,
            orphaned_tickets=orphaned_tickets,
            ghost_tickets=ghost_tickets,
            sl_mismatches=sl_mismatches,
            total_broker_positions=len(broker_positions),
            total_internal_positions=len(internal_registry),
            reconciled_at=utc_now(),
        )

        if not is_synced:
            logger.warning(
                "reconciliation_discrepancy_detected",
                orphaned=len(orphaned_tickets),
                ghosts=len(ghost_tickets),
                mismatches=len(sl_mismatches),
            )

        return report
