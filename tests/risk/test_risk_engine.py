"""
QUANT HERMES — Testes do Motor Soberano de Risco (Risk Engine)
Arquivo: tests/risk/test_risk_engine.py
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from core.models.market import MarketTick, SymbolSpecification
from core.models.risk import AccountState, Position, TradeProposal
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
def valid_proposal():
    return TradeProposal(
        decision_id=uuid4(),
        strategy_id="STRAT_TREND_EURUSD",
        symbol="EURUSD",
        action="BUY",
        entry_price=1.08500,
        stop_loss=1.08200,
        take_profit=1.09100,
        target_risk_pct=0.25,
    )


@pytest.fixture
def normal_tick():
    return MarketTick(
        symbol="EURUSD",
        time=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc),  # Quarta-feira 14h UTC
        bid=1.08500,
        ask=1.08515,
        last=1.08505,
        volume=10.0,
    )


@pytest.fixture
def risk_engine(tmp_path):
    ks = KillSwitch(state_file_path=tmp_path / "engine_kill_switch.json")
    cb = CircuitBreakerManager()
    return RiskEngine(kill_switch=ks, circuit_breakers=cb)


class TestRiskEngine:
    """Suíte de testes de soberania e segurança do Risk Engine."""

    def test_evaluate_proposal_approved_nominal(
        self, risk_engine, valid_proposal, healthy_account, normal_tick, eurusd_spec
    ):
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth.approved is True
        assert auth.authorized_lot == 0.83  # 0.25% de $100k = $250 / (300 ticks * $1) = 0.83
        assert auth.risk_percentage == 0.25
        assert auth.risk_amount_money == 250.0
        assert auth.rejection_reason is None

    def test_evaluate_proposal_rejects_null_account_state_fail_safe(
        self, risk_engine, valid_proposal, normal_tick, eurusd_spec
    ):
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=None,  # Simula perda de dados da corretora
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth.approved is False
        assert "FAIL_SAFE" in auth.rejection_reason

    def test_evaluate_proposal_rejects_active_kill_switch(
        self, risk_engine, valid_proposal, healthy_account, normal_tick, eurusd_spec
    ):
        risk_engine.kill_switch.engage(reason="MANUAL_HALT_AUDIT")
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth.approved is False
        assert "KILL_SWITCH" in auth.rejection_reason

    def test_evaluate_proposal_rejects_tripped_circuit_breaker(
        self, risk_engine, valid_proposal, healthy_account, normal_tick, eurusd_spec
    ):
        # Perda diária além do limite de 1.50%
        account_loss = healthy_account.model_copy(update={"daily_pnl_pct": -1.80})
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=account_loss,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth.approved is False
        assert "CIRCUIT_BREAKER_DAILY_LOSS" in auth.rejection_reason

    def test_evaluate_proposal_rejects_max_open_positions(
        self, risk_engine, valid_proposal, healthy_account, normal_tick, eurusd_spec
    ):
        # Cria 3 posições existentes (atingindo o teto)
        dummy_positions = [
            Position(
                ticket=101,
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
                ticket=102,
                symbol="USDJPY",
                magic=2,
                position_type="BUY",
                volume=0.1,
                open_price=150.00,
                stop_loss=149.50,
                current_price=150.20,
                open_time=datetime.now(timezone.utc),
            ),
            Position(
                ticket=103,
                symbol="XAUUSD",
                magic=3,
                position_type="BUY",
                volume=0.1,
                open_price=2650.00,
                stop_loss=2640.00,
                current_price=2655.00,
                open_time=datetime.now(timezone.utc),
            ),
        ]
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=dummy_positions,
        )
        assert auth.approved is False
        assert "MAX_POSITIONS_LIMIT" in auth.rejection_reason

    def test_evaluate_proposal_rejects_duplicate_symbol_position(
        self, risk_engine, valid_proposal, healthy_account, normal_tick, eurusd_spec
    ):
        # Já existe uma posição aberta no mesmo ativo
        existing_pos = [
            Position(
                ticket=201,
                symbol="EURUSD",
                magic=1,
                position_type="BUY",
                volume=0.5,
                open_price=1.08400,
                stop_loss=1.08100,
                current_price=1.08500,
                open_time=datetime.now(timezone.utc),
            )
        ]
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=existing_pos,
        )
        assert auth.approved is False
        assert "SYMBOL_POSITION_LIMIT" in auth.rejection_reason

    def test_evaluate_proposal_rejects_spread_spike(
        self, risk_engine, valid_proposal, healthy_account, normal_tick, eurusd_spec
    ):
        # Spread médio = 0.00015. Spread do tick = 0.00045 (3.0x > max 2.0x)
        spike_tick = MarketTick(
            symbol="EURUSD",
            time=normal_tick.time,
            bid=1.08500,
            ask=1.08545,  # spread 0.00045
            last=1.08510,
            volume=5.0,
        )
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=healthy_account,
            current_tick=spike_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth.approved is False
        assert "SPREAD_ANOMALY" in auth.rejection_reason

    def test_evaluate_proposal_clamps_to_remaining_aggregate_risk(
        self, risk_engine, valid_proposal, healthy_account, normal_tick, eurusd_spec
    ):
        # Cria uma posição existente consumindo 0.85% de risco
        # Stop loss de 850 ticks * $1/tick * 1.0 lote = $850 em $100k = 0.85%
        pos = Position(
            ticket=301,
            symbol="EURUSD_OLD",
            magic=1,
            position_type="BUY",
            volume=1.0,
            open_price=1.08850,
            stop_loss=1.08000,
            current_price=1.08850,
            open_time=datetime.now(timezone.utc),
        )
        dummy_spec = eurusd_spec.model_copy(update={"symbol": "EURUSD_OLD"})

        # A proposta pede 0.25%, mas só restam 0.15% (1.00% - 0.85%)
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=healthy_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[pos],
            known_specs={"EURUSD_OLD": dummy_spec, "EURUSD": eurusd_spec},
        )
        assert auth.approved is True
        assert auth.risk_percentage == 0.15  # Limitado ao orçamento restante
        assert auth.risk_amount_money == 150.0  # 0.15% de $100k
        assert auth.authorized_lot == 0.50  # 150 / 300 = 0.50

    def test_evaluate_proposal_rejects_lot_below_volume_min(
        self, risk_engine, valid_proposal, normal_tick, eurusd_spec
    ):
        # Conta pequena ($100), risco 0.25% = $0.25
        # Perda por lote = $300 -> Lote bruto = 0.25 / 300 = 0.00083 < 0.01
        small_account = AccountState(
            login=999,
            server="Demo",
            currency="USD",
            balance=100.0,
            equity=100.0,
            margin=0.0,
            free_margin=100.0,
            peak_equity=100.0,
            daily_pnl_pct=0.0,
            weekly_pnl_pct=0.0,
            current_drawdown_pct=0.0,
        )
        auth = risk_engine.evaluate_proposal(
            proposal=valid_proposal,
            account_state=small_account,
            current_tick=normal_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth.approved is False
        assert "POSITION_SIZER" in auth.rejection_reason

