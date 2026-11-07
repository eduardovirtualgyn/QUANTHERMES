"""
QUANT HERMES — Testes do Gerenciador de Portfólio (Portfolio Manager)
Arquivo: tests/unit/test_portfolio_manager.py
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from core.models.agent import ConsensusDecision, SignalDirection
from core.models.market import MarketTick, SymbolSpecification
from core.models.risk import AccountState, Position
from portfolio.allocator import CapitalAllocator
from portfolio.correlation import CorrelationMonitor
from portfolio.manager import PortfolioManager
from risk.circuit_breakers import CircuitBreakerManager
from risk.engine import RiskEngine
from risk.kill_switch import KillSwitch


@pytest.fixture
def eurusd_spec():
    return SymbolSpecification(
        symbol="EURUSD",
        canonical_name="EURUSD",
        category="forex_major",
        base_currency="EUR",
        quote_currency="USD",
        digits=5,
        point=0.00001,
        tick_size=0.00001,
        tick_value=1.0,
        contract_size=100000.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )


@pytest.fixture
def healthy_account():
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


@pytest.fixture
def normal_tick():
    return MarketTick(
        symbol="EURUSD",
        time=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc),
        bid=1.08500,
        ask=1.08515,
        last=1.08505,
        volume=10.0,
    )


@pytest.fixture
def buy_decision():
    return ConsensusDecision(
        symbol="EURUSD",
        action=SignalDirection.BUY,
        composite_score=0.78,
        calibrated_probability=0.72,
        active_regime="BULL_TREND_LOW_VOL",
        participating_agents=["AG01_TREND", "AG03_MOMENTUM"],
        suggested_entry=1.08500,
        suggested_stop=1.08200,
        suggested_target=1.09100,
    )


@pytest.fixture
def portfolio_manager(tmp_path):
    ks = KillSwitch(state_file_path=tmp_path / "pm_kill_switch.json")
    cb = CircuitBreakerManager()
    engine = RiskEngine(kill_switch=ks, circuit_breakers=cb)
    allocator = CapitalAllocator()
    corr_monitor = CorrelationMonitor()
    return PortfolioManager(
        risk_engine=engine,
        allocator=allocator,
        correlation_monitor=corr_monitor,
        dedup_cooldown_seconds=60,
    )


class TestPortfolioManager:
    """Testes de coordenação, deduplicação e encaminhamento do PortfolioManager."""

    def test_hold_decision_is_ignored(self, portfolio_manager, healthy_account, normal_tick, eurusd_spec):
        hold_decision = ConsensusDecision(
            symbol="EURUSD",
            action=SignalDirection.HOLD,
            composite_score=0.0,
            calibrated_probability=0.50,
            active_regime="SIDEWAYS",
            suggested_entry=1.08500,
            suggested_stop=1.08200,
            suggested_target=1.09100,
        )
        auth = portfolio_manager.process_consensus_decision(
            decision=hold_decision,
            strategy_id="STRAT_TREND",
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth is None

    def test_nominal_buy_proposal_approved(
        self, portfolio_manager, buy_decision, healthy_account, normal_tick, eurusd_spec
    ):
        auth = portfolio_manager.process_consensus_decision(
            decision=buy_decision,
            strategy_id="STRAT_TREND_EURUSD",
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth is not None
        assert auth.approved is True
        assert auth.authorized_lot == 0.83
        assert auth.risk_percentage == 0.25

    def test_deduplication_drops_repeated_decision_within_cooldown(
        self, portfolio_manager, buy_decision, healthy_account, normal_tick, eurusd_spec
    ):
        # 1ª chamada: aprovada
        auth1 = portfolio_manager.process_consensus_decision(
            decision=buy_decision,
            strategy_id="STRAT_TREND_EURUSD",
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth1 is not None
        assert auth1.approved is True

        # 2ª chamada imediata (mesmo símbolo e ação): deduplicada -> retorna None
        auth2 = portfolio_manager.process_consensus_decision(
            decision=buy_decision,
            strategy_id="STRAT_TREND_EURUSD",
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth2 is None

    def test_blocked_by_correlation_monitor(
        self, portfolio_manager, buy_decision, healthy_account, normal_tick, eurusd_spec
    ):
        # Posições abertas que já atingem limite de 2 pares Short USD
        open_positions = [
            Position(
                ticket=1,
                symbol="GBPUSD",
                magic=1,
                position_type="BUY",
                volume=0.1,
                open_price=1.25000,
                stop_loss=1.24800,
                current_price=1.25100,
                open_time=datetime.now(timezone.utc),
            ),
            Position(
                ticket=2,
                symbol="XAUUSD",
                magic=2,
                position_type="BUY",
                volume=0.1,
                open_price=2650.00,
                stop_loss=2640.00,
                current_price=2655.00,
                open_time=datetime.now(timezone.utc),
            ),
        ]
        auth = portfolio_manager.process_consensus_decision(
            decision=buy_decision,
            strategy_id="STRAT_TREND_EURUSD",
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=open_positions,
        )
        assert auth is not None
        assert auth.approved is False
        assert "CORRELATION_LIMIT_EXCEEDED" in auth.rejection_reason
