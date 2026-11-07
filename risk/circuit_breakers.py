"""
QUANT HERMES — Circuit Breakers de Proteção de Capital
Módulo: risk.circuit_breakers
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional
from core.models.risk import AccountState
from core.models.base import utc_now


@dataclass
class BreakerTripInfo:
    """Informações de disparo de um circuit breaker."""
    tripped: bool
    breaker_name: str
    reason: str
    triggered_at: datetime
    reset_at: Optional[datetime] = None


class DailyLossGuard:
    """
    Guardião de perda diária máxima.
    Trava o sistema se as perdas do dia atingirem ou superarem o limite (padrão 1.50%).
    Permanece travado até a virada do dia às 00:00 UTC.
    """

    def __init__(self, max_daily_loss_pct: float = 1.50):
        if max_daily_loss_pct <= 0.0 or max_daily_loss_pct > 2.00:
            raise ValueError(f"max_daily_loss_pct ({max_daily_loss_pct}%) deve estar entre 0.01% e 2.00% (piso)")
        self.max_daily_loss_pct = max_daily_loss_pct
        self._tripped: bool = False
        self._trip_date: Optional[datetime.date] = None

    def check(self, account_state: AccountState, current_time: Optional[datetime] = None) -> tuple[bool, Optional[str]]:
        now = current_time or utc_now()
        today = now.date()

        # Reseta se mudou de dia UTC
        if self._tripped and self._trip_date is not None and today > self._trip_date:
            self._tripped = False
            self._trip_date = None

        # Avalia se a perda diária atingiu o limite
        # daily_pnl_pct é negativo em caso de perda (ex: -1.55%)
        if account_state.daily_pnl_pct <= -self.max_daily_loss_pct:
            self._tripped = True
            self._trip_date = today
            return False, (
                f"CIRCUIT_BREAKER_DAILY_LOSS: Perda diária ({account_state.daily_pnl_pct:.2f}%) "
                f"atingiu o limite de -{self.max_daily_loss_pct:.2f}%"
            )

        if self._tripped:
            return False, f"CIRCUIT_BREAKER_DAILY_LOSS: Bloqueio diário ativo até 00:00 UTC seguinte"

        return True, None


class WeeklyLossGuard:
    """
    Guardião de perda semanal máxima.
    Trava o sistema se as perdas acumuladas na semana atingirem o limite (padrão 3.00%).
    Permanece travado até a virada de semana (Segunda-feira 00:00 UTC).
    """

    def __init__(self, max_weekly_loss_pct: float = 3.00):
        if max_weekly_loss_pct <= 0.0 or max_weekly_loss_pct > 4.00:
            raise ValueError(f"max_weekly_loss_pct ({max_weekly_loss_pct}%) deve estar entre 0.01% e 4.00% (piso)")
        self.max_weekly_loss_pct = max_weekly_loss_pct
        self._tripped: bool = False
        self._trip_week: Optional[tuple[int, int]] = None  # (ano, semana_iso)

    def check(self, account_state: AccountState, current_time: Optional[datetime] = None) -> tuple[bool, Optional[str]]:
        now = current_time or utc_now()
        current_week = now.isocalendar()[:2]

        # Reseta se mudou de semana ISO
        if self._tripped and self._trip_week is not None and current_week > self._trip_week:
            self._tripped = False
            self._trip_week = None

        if account_state.weekly_pnl_pct <= -self.max_weekly_loss_pct:
            self._tripped = True
            self._trip_week = current_week
            return False, (
                f"CIRCUIT_BREAKER_WEEKLY_LOSS: Perda semanal ({account_state.weekly_pnl_pct:.2f}%) "
                f"atingiu o limite de -{self.max_weekly_loss_pct:.2f}%"
            )

        if self._tripped:
            return False, f"CIRCUIT_BREAKER_WEEKLY_LOSS: Bloqueio semanal ativo até segunda-feira 00:00 UTC"

        return True, None


class EmergencyDrawdownGuard:
    """
    Guardião de Drawdown de Emergência (Piso inviolável de 8.00%).
    Se o drawdown da conta em relação ao topo histórico (peak equity)
    atingir ou superar 8.00%, desarma o sistema imediatamente.
    """

    def __init__(self, max_drawdown_limit_pct: float = 8.00):
        if max_drawdown_limit_pct <= 0.0 or max_drawdown_limit_pct > 8.00:
            raise ValueError(
                f"max_drawdown_limit_pct ({max_drawdown_limit_pct}%) não pode exceder o piso absoluto de 8.00%"
            )
        self.max_drawdown_limit_pct = max_drawdown_limit_pct

    def check(self, account_state: AccountState) -> tuple[bool, Optional[str]]:
        if account_state.current_drawdown_pct >= self.max_drawdown_limit_pct:
            return False, (
                f"CIRCUIT_BREAKER_EMERGENCY_DRAWDOWN: Drawdown atual ({account_state.current_drawdown_pct:.2f}%) "
                f"ultrapassou o teto absoluto de {self.max_drawdown_limit_pct:.2f}%"
            )
        return True, None


class WeekendRiskGuard:
    """
    Guardião de risco de fim de semana.
    Impede novas operações a partir de sexta-feira às 20:00 UTC
    e durante todo o fim de semana (sábado e domingo), protegendo
    contra gaps de abertura de mercado.
    """

    def __init__(self, friday_closing_utc_hour: int = 20):
        self.friday_closing_utc_hour = friday_closing_utc_hour

    def check(self, current_time: Optional[datetime] = None) -> tuple[bool, Optional[str]]:
        now = current_time or utc_now()
        weekday = now.weekday()  # Segunda=0, Sexta=4, Sábado=5, Domingo=6

        # Sexta-feira após o horário limite
        if weekday == 4 and now.hour >= self.friday_closing_utc_hour:
            return False, (
                f"WEEKEND_RISK_GUARD: Operações bloqueadas após {self.friday_closing_utc_hour:02d}:00 UTC "
                f"de sexta-feira (horário atual: {now.strftime('%H:%M')} UTC)"
            )

        # Sábado ou Domingo
        if weekday in (5, 6):
            return False, (
                f"WEEKEND_RISK_GUARD: Operações bloqueadas no fim de semana ({now.strftime('%A')})"
            )

        return True, None


class CircuitBreakerManager:
    """
    Gerenciador unificado de circuit breakers do QUANT HERMES.
    Avalia sequencialmente todos os guardiões antes de qualquer deliberação de risco.
    """

    def __init__(
        self,
        max_daily_loss_pct: float = 1.50,
        max_weekly_loss_pct: float = 3.00,
        max_drawdown_limit_pct: float = 8.00,
        friday_closing_utc_hour: int = 20,
    ):
        self.daily_guard = DailyLossGuard(max_daily_loss_pct)
        self.weekly_guard = WeeklyLossGuard(max_weekly_loss_pct)
        self.drawdown_guard = EmergencyDrawdownGuard(max_drawdown_limit_pct)
        self.weekend_guard = WeekendRiskGuard(friday_closing_utc_hour)

    def check_all(
        self,
        account_state: AccountState,
        current_time: Optional[datetime] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Executa a verificação encadeada de todos os circuit breakers.
        Retorna (True, None) se todos os freios estiverem intactos.
        Retorna (False, motivo) ao primeiro freio disparado.
        """
        # 1. Drawdown de emergência (mais crítico)
        ok, reason = self.drawdown_guard.check(account_state)
        if not ok:
            return False, reason

        # 2. Perda diária
        ok, reason = self.daily_guard.check(account_state, current_time)
        if not ok:
            return False, reason

        # 3. Perda semanal
        ok, reason = self.weekly_guard.check(account_state, current_time)
        if not ok:
            return False, reason

        # 4. Horário de fim de semana
        ok, reason = self.weekend_guard.check(current_time)
        if not ok:
            return False, reason

        return True, None

