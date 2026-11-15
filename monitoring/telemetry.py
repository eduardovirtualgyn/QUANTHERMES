"""
QUANT HERMES — PROVEDOR CONSOLIDADO DE TELEMETRIA
Módulo: monitoring.telemetry

Responsabilidade:
- Consolidar métricas operacionais, financeiras e estocásticas para consumo do Dashboard e API.
- Isolar a leitura de dados para não interferir na thread crítica de execução.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.logger import get_logger
from core.models.risk import AccountState, Position
from execution.adapters.base import TradingPlatformAdapter
from execution.orchestrator import AutonomousTradingOrchestrator
from intelligence.learning.registry import ModelRegistry
from risk.engine import RiskEngine

logger = get_logger("monitoring.telemetry")


@dataclass
class SystemTelemetrySnapshot:
    """Snapshot completo de telemetria do sistema em um instante no tempo."""
    timestamp_utc: str
    system_status: str
    account: Dict[str, Any]
    active_positions: List[Dict[str, Any]]
    circuit_breakers: Dict[str, Any]
    kill_switch_active: bool
    active_regimes: Dict[str, str]
    tracked_tickets_count: int
    session_metrics: Dict[str, int]


class TelemetryProvider:
    """
    Provedor assíncrono de telemetria para a API REST e WebSockets do Dashboard.
    """

    def __init__(
        self,
        orchestrator: Optional[AutonomousTradingOrchestrator] = None,
        adapter: Optional[TradingPlatformAdapter] = None,
        risk_engine: Optional[RiskEngine] = None,
        model_registry: Optional[ModelRegistry] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.adapter = adapter or (orchestrator.adapter if orchestrator else None)
        self.risk_engine = risk_engine or (orchestrator.risk_engine if orchestrator else None)
        self.model_registry = model_registry or ModelRegistry()

    async def get_system_health(self) -> Dict[str, Any]:
        """Retorna o status geral de saúde dos serviços do QUANT HERMES."""
        adapter_connected = False
        if self.adapter:
            try:
                res = self.adapter.is_connected()
                adapter_connected = await res if hasattr(res, "__await__") else res
            except Exception:
                adapter_connected = False

        status = "HEALTHY" if adapter_connected else "DEGRADED"
        if self.risk_engine:
            ks = self.risk_engine.kill_switch
            if ks.is_active() if callable(ks.is_active) else bool(ks.is_active):
                status = "EMERGENCY_HALT"

        return {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "adapter_connected": adapter_connected,
            "orchestrator_running": self.orchestrator.is_running if self.orchestrator else False,
            "version": "1.0.0",
        }

    async def get_account_state(self) -> Dict[str, Any]:
        """Retorna o estado financeiro consolidado da conta de trading."""
        if not self.adapter:
            return {
                "balance": 0.0,
                "equity": 0.0,
                "free_margin": 0.0,
                "daily_pnl_pct": 0.0,
                "current_drawdown_pct": 0.0,
            }

        res = self.adapter.get_account_state()
        account: AccountState = await res if hasattr(res, "__await__") else res

        return {
            "login": account.login,
            "server": account.server,
            "currency": account.currency,
            "balance": round(account.balance, 2),
            "equity": round(account.equity, 2),
            "margin": round(account.margin, 2),
            "free_margin": round(account.free_margin, 2),
            "margin_level": round(account.margin_level, 2),
            "leverage": account.leverage,
            "daily_pnl_pct": round(account.daily_pnl_pct, 4),
            "weekly_pnl_pct": round(account.weekly_pnl_pct, 4),
            "current_drawdown_pct": round(account.current_drawdown_pct, 4),
            "peak_equity": round(account.peak_equity, 2),
            "timestamp": account.timestamp.isoformat(),
        }

    async def get_open_positions(self) -> List[Dict[str, Any]]:
        """Retorna a lista de posições abertas no terminal/simulador."""
        if not self.adapter:
            return []

        res = self.adapter.get_open_positions()
        positions: List[Position] = await res if hasattr(res, "__await__") else res

        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "magic": p.magic,
                "position_type": p.position_type,
                "volume": p.volume,
                "open_price": p.open_price,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "current_price": p.current_price,
                "profit": round(p.profit, 2),
                "open_time": p.open_time.isoformat(),
            }
            for p in positions
        ]

    def get_risk_status(self) -> Dict[str, Any]:
        """Retorna o status de proteção dos Circuit Breakers e Kill Switch."""
        if not self.risk_engine:
            return {"status": "UNKNOWN", "kill_switch_active": False}

        ks = self.risk_engine.kill_switch
        cb = self.risk_engine.circuit_breakers
        ks_active = ks.is_active() if callable(ks.is_active) else bool(ks.is_active)

        daily_guard = getattr(cb, "daily_guard", getattr(cb, "daily_loss_guard", None))
        weekly_guard = getattr(cb, "weekly_guard", getattr(cb, "weekly_loss_guard", None))
        drawdown_guard = getattr(cb, "drawdown_guard", getattr(cb, "emergency_drawdown_guard", None))
        weekend_guard = getattr(cb, "weekend_guard", getattr(cb, "weekend_risk_guard", None))

        return {
            "kill_switch": {
                "is_active": ks_active,
                "reason": ks.reason,
                "triggered_at": ks.triggered_at.isoformat() if ks.triggered_at else None,
                "triggered_by": ks.triggered_by,
            },
            "circuit_breakers": {
                "daily_loss_guard": {
                    "limit_pct": getattr(daily_guard, "max_daily_loss_pct", getattr(daily_guard, "max_loss_pct", 1.50)),
                    "is_tripped": getattr(daily_guard, "is_tripped", getattr(daily_guard, "_tripped", False)),
                },
                "weekly_loss_guard": {
                    "limit_pct": getattr(weekly_guard, "max_weekly_loss_pct", getattr(weekly_guard, "max_loss_pct", 3.00)),
                    "is_tripped": getattr(weekly_guard, "is_tripped", getattr(weekly_guard, "_tripped", False)),
                },
                "emergency_drawdown_guard": {
                    "limit_pct": getattr(drawdown_guard, "max_drawdown_limit_pct", getattr(drawdown_guard, "max_drawdown_pct", 8.00)),
                    "is_tripped": getattr(drawdown_guard, "is_tripped", getattr(drawdown_guard, "_tripped", False)),
                },
                "weekend_risk_guard": {
                    "is_tripped": getattr(weekend_guard, "is_tripped", getattr(weekend_guard, "_tripped", False)),
                },
            },
        }

    async def get_telemetry_snapshot(self) -> Dict[str, Any]:
        """Gera um snapshot consolidado de telemetria para WebSockets."""
        health = await self.get_system_health()
        account = await self.get_account_state()
        positions = await self.get_open_positions()
        risk = self.get_risk_status()

        active_regimes = {}
        session_metrics = {}
        tracked_count = 0

        if self.orchestrator:
            active_regimes = {
                sym: reg.active_regime.value
                for sym, reg in self.orchestrator._current_regimes.items()
            }
            session_metrics = dict(self.orchestrator._session_metrics)
            tracked_count = len(self.orchestrator.state_manager.current_state.tracked_tickets)

        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "health": health,
            "account": account,
            "positions": positions,
            "risk": risk,
            "active_regimes": active_regimes,
            "tracked_tickets_count": tracked_count,
            "session_metrics": session_metrics,
        }

