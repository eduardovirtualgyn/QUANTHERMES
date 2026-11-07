"""
QUANT HERMES — Testes dos Circuit Breakers
Arquivo: tests/risk/test_circuit_breakers.py
"""
import pytest
from datetime import datetime, timezone, timedelta
from core.models.risk import AccountState
from risk.circuit_breakers import (
    DailyLossGuard,
    WeeklyLossGuard,
    EmergencyDrawdownGuard,
    WeekendRiskGuard,
    CircuitBreakerManager,
)


@pytest.fixture
def base_account_state():
    return AccountState(
        login=12345678,
        server="HermesDemo-Server",
        currency="USD",
        balance=100000.0,
        equity=100000.0,
        margin=0.0,
        free_margin=100000.0,
        peak_equity=100000.0,
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        current_drawdown_pct=0.0,
    )


class TestDailyLossGuard:
    """Testes do guardião de perda diária."""

    def test_daily_loss_within_limit_passes(self, base_account_state):
        guard = DailyLossGuard(max_daily_loss_pct=1.50)
        account = base_account_state.model_copy(update={"daily_pnl_pct": -0.80})
        ok, reason = guard.check(account)
        assert ok is True
        assert reason is None

    def test_daily_loss_at_or_exceeding_limit_trips(self, base_account_state):
        guard = DailyLossGuard(max_daily_loss_pct=1.50)
        account = base_account_state.model_copy(update={"daily_pnl_pct": -1.50})
        ok, reason = guard.check(account)
        assert ok is False
        assert "CIRCUIT_BREAKER_DAILY_LOSS" in reason

    def test_daily_loss_persists_same_day_and_resets_next_day(self, base_account_state):
        guard = DailyLossGuard(max_daily_loss_pct=1.50)
        t1 = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
        t1_later = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)
        t2_next_day = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)

        # Dispara perda no dia 4
        account_loss = base_account_state.model_copy(update={"daily_pnl_pct": -1.60})
        ok, _ = guard.check(account_loss, current_time=t1)
        assert ok is False

        # Mesmo com pnl_pct recuperado mais tarde no mesmo dia, permanece bloqueado
        account_rebound = base_account_state.model_copy(update={"daily_pnl_pct": -0.50})
        ok, _ = guard.check(account_rebound, current_time=t1_later)
        assert ok is False

        # No dia seguinte, reseta e permite operação
        account_new_day = base_account_state.model_copy(update={"daily_pnl_pct": 0.0})
        ok, reason = guard.check(account_new_day, current_time=t2_next_day)
        assert ok is True
        assert reason is None

    def test_daily_loss_guard_rejects_inviolable_floor_violation(self):
        with pytest.raises(ValueError, match="piso"):
            DailyLossGuard(max_daily_loss_pct=2.50)  # Piso máximo absoluto é 2.00%


class TestWeeklyLossGuard:
    """Testes do guardião de perda semanal."""

    def test_weekly_loss_at_limit_trips(self, base_account_state):
        guard = WeeklyLossGuard(max_weekly_loss_pct=3.00)
        account = base_account_state.model_copy(update={"weekly_pnl_pct": -3.05})
        ok, reason = guard.check(account)
        assert ok is False
        assert "CIRCUIT_BREAKER_WEEKLY_LOSS" in reason

    def test_weekly_loss_guard_rejects_floor_violation(self):
        with pytest.raises(ValueError, match="piso"):
            WeeklyLossGuard(max_weekly_loss_pct=5.00)  # Piso máximo é 4.00%


class TestEmergencyDrawdownGuard:
    """Testes do guardião de drawdown catastrófico."""

    def test_drawdown_within_safe_range_passes(self, base_account_state):
        guard = EmergencyDrawdownGuard(max_drawdown_limit_pct=8.00)
        account = base_account_state.model_copy(update={"current_drawdown_pct": 4.50})
        ok, reason = guard.check(account)
        assert ok is True
        assert reason is None

    def test_drawdown_at_or_above_limit_trips(self, base_account_state):
        guard = EmergencyDrawdownGuard(max_drawdown_limit_pct=8.00)
        account = base_account_state.model_copy(update={"current_drawdown_pct": 8.00})
        ok, reason = guard.check(account)
        assert ok is False
        assert "CIRCUIT_BREAKER_EMERGENCY_DRAWDOWN" in reason

    def test_emergency_drawdown_rejects_floor_relaxation(self):
        with pytest.raises(ValueError, match="piso absoluto"):
            EmergencyDrawdownGuard(max_drawdown_limit_pct=10.00)


class TestWeekendRiskGuard:
    """Testes de proteção contra risco de fim de semana."""

    def test_weekday_normal_hours_pass(self):
        guard = WeekendRiskGuard(friday_closing_utc_hour=20)
        wednesday = datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc)
        ok, reason = guard.check(wednesday)
        assert ok is True
        assert reason is None

    def test_friday_before_limit_passes(self):
        guard = WeekendRiskGuard(friday_closing_utc_hour=20)
        friday_afternoon = datetime(2026, 11, 6, 19, 45, tzinfo=timezone.utc)
        ok, reason = guard.check(friday_afternoon)
        assert ok is True

    def test_friday_after_closing_hour_trips(self):
        guard = WeekendRiskGuard(friday_closing_utc_hour=20)
        friday_evening = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
        ok, reason = guard.check(friday_evening)
        assert ok is False
        assert "WEEKEND_RISK_GUARD" in reason

    def test_saturday_and_sunday_trip(self):
        guard = WeekendRiskGuard(friday_closing_utc_hour=20)
        saturday = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
        sunday = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)
        assert guard.check(saturday)[0] is False
        assert guard.check(sunday)[0] is False


class TestCircuitBreakerManager:
    """Testes do orquestrador de circuit breakers."""

    def test_manager_approves_when_all_healthy(self, base_account_state):
        manager = CircuitBreakerManager()
        wednesday = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        ok, reason = manager.check_all(base_account_state, current_time=wednesday)
        assert ok is True
        assert reason is None

    def test_manager_prioritizes_drawdown_trip(self, base_account_state):
        manager = CircuitBreakerManager()
        account = base_account_state.model_copy(
            update={"current_drawdown_pct": 8.50, "daily_pnl_pct": -2.00}
        )
        ok, reason = manager.check_all(account)
        assert ok is False
        assert "CIRCUIT_BREAKER_EMERGENCY_DRAWDOWN" in reason
