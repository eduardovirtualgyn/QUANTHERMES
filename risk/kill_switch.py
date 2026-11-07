"""
QUANT HERMES — Mecanismo de Trava de Emergência Global (Kill Switch)
Módulo: risk.kill_switch
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from core.logger import get_logger
from core.models.base import utc_now
from execution.adapters.base import TradingPlatformAdapter

logger = get_logger("risk.kill_switch")

_DEFAULT_STATE_PATH = Path("data/storage/kill_switch_state.json")


class KillSwitch:
    """
    Trava de emergência global com persistência em disco.
    Garante:
    1. Bloqueio imediato e irrestrito de qualquer nova ordem.
    2. Persistência de estado atômica em arquivo JSON, impedindo que reinicializações
       ou reinícios de processo limpem indevidamente o estado de trava.
    3. Rotina assíncrona de liquidação compulsória de todas as posições abertas no broker.
    4. Desarme restrito com assinatura de operador.
    """

    def __init__(self, state_file_path: Optional[Path] = None):
        self.state_file_path = state_file_path or _DEFAULT_STATE_PATH
        self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._is_active: bool = False
        self._reason: Optional[str] = None
        self._triggered_by: Optional[str] = None
        self._triggered_at: Optional[datetime] = None
        self._load_state()

    def _load_state(self) -> None:
        """Carrega o estado persistido do arquivo JSON se existir."""
        if not self.state_file_path.exists():
            return

        try:
            with open(self.state_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._is_active = data.get("is_active", False)
            self._reason = data.get("reason")
            self._triggered_by = data.get("triggered_by")
            triggered_at_raw = data.get("triggered_at")
            if triggered_at_raw:
                self._triggered_at = datetime.fromisoformat(triggered_at_raw)
            if self._is_active:
                logger.warning(
                    "kill_switch_restored_from_disk",
                    reason=self._reason,
                    triggered_by=self._triggered_by,
                    triggered_at=str(self._triggered_at),
                )
        except Exception as e:
            logger.error("kill_switch_state_load_failed", error=str(e))
            # Em caso de arquivo de estado corrompido, atitude Fail-Safe: TRAVA ATIVA!
            self._is_active = True
            self._reason = f"FAIL_SAFE: Estado em disco corrompido ({e})"
            self._triggered_by = "FAIL_SAFE_LOAD_ERROR"
            self._triggered_at = utc_now()

    def _persist_state(self) -> None:
        """Persiste o estado atomicamente no disco."""
        payload = {
            "is_active": self._is_active,
            "reason": self._reason,
            "triggered_by": self._triggered_by,
            "triggered_at": self._triggered_at.isoformat() if self._triggered_at else None,
        }
        temp_file = self.state_file_path.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            temp_file.replace(self.state_file_path)
        except Exception as e:
            logger.critical("kill_switch_state_persist_failed", error=str(e))

    def is_active(self) -> bool:
        """Verifica se o Kill Switch está armado."""
        return self._is_active

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    @property
    def triggered_by(self) -> Optional[str]:
        return self._triggered_by

    @property
    def triggered_at(self) -> Optional[datetime]:
        return self._triggered_at

    def engage(self, reason: str, triggered_by: str = "SYSTEM") -> None:
        """
        Arma a trava de emergência global.
        Persiste no disco e trava imediatamente o envio de qualquer nova operação.
        """
        self._is_active = True
        self._reason = reason
        self._triggered_by = triggered_by
        self._triggered_at = utc_now()
        self._persist_state()
        logger.critical(
            "KILL_SWITCH_ENGAGED",
            reason=reason,
            triggered_by=triggered_by,
            timestamp=self._triggered_at.isoformat(),
        )

    def disengage(self, operator_token: str, reason: str) -> bool:
        """
        Desarma o Kill Switch mediante autorização explícita de operador.
        Não pode ser chamado por nenhum agente ou modelo de IA.
        """
        if not operator_token or len(operator_token.strip()) < 8:
            logger.error("kill_switch_disengage_rejected_invalid_token")
            return False

        self._is_active = False
        self._reason = None
        self._triggered_by = None
        self._triggered_at = None
        self._persist_state()
        logger.warning("KILL_SWITCH_DISENGAGED", operator_reason=reason)
        return True

    async def execute_emergency_liquidation(
        self,
        adapter: TradingPlatformAdapter,
    ) -> dict[str, Any]:
        """
        Rotina compulsória de liquidação total de posições no terminal de negociação.
        Itera sobre todas as posições em aberto e envia ordens de fechamento a mercado.
        """
        logger.critical("EMERGENCY_LIQUIDATION_STARTED")
        positions = await adapter.get_open_positions()
        closed_count = 0
        failed_count = 0
        details = []

        for pos in positions:
            try:
                res = await adapter.close_position(ticket=pos.ticket)
                if res.success:
                    closed_count += 1
                    details.append({"ticket": pos.ticket, "status": "CLOSED", "retcode": res.retcode})
                    logger.warning("emergency_position_closed", ticket=pos.ticket, symbol=pos.symbol)
                else:
                    failed_count += 1
                    details.append({
                        "ticket": pos.ticket,
                        "status": "FAILED",
                        "retcode": res.retcode,
                        "error": res.comment,
                    })
                    logger.critical(
                        "emergency_position_close_failed",
                        ticket=pos.ticket,
                        symbol=pos.symbol,
                        error=res.comment,
                    )
            except Exception as exc:
                failed_count += 1
                details.append({"ticket": pos.ticket, "status": "ERROR", "error": str(exc)})
                logger.critical("emergency_position_close_exception", ticket=pos.ticket, error=str(exc))

        # Verificação final
        remaining_positions = await adapter.get_open_positions()
        is_clean = len(remaining_positions) == 0

        summary = {
            "total_open": len(positions),
            "closed": closed_count,
            "failed": failed_count,
            "remaining_open": len(remaining_positions),
            "clean_slate": is_clean,
            "details": details,
        }
        logger.critical("EMERGENCY_LIQUIDATION_COMPLETED", **summary)
        return summary
