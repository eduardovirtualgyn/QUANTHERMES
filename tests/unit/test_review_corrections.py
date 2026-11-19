"""Correções da revisão externa: PnL, fills parciais, requote, margem, swap, config, recuperação."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import yaml

from core.config import load_hermes_config
from core.models.market import MarketBar, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, Position, RiskAuthorization, TradeProposal
from core.secrets import MissingSecretError
from execution.account_pnl import pnl_percent, realized_from_deals, unrealized_from_positions
from execution.adapters.windows_mt5 import WindowsMT5Adapter
from execution.idempotency import OrderLifecycleState, SqliteIdempotencyStore
from execution.order_executor import OrderExecutor
from execution.state_manager import ExecutionStateManager
from execution.symbols import SymbolMapper
from monitoring.server import create_monitoring_app
from risk.circuit_breakers import CircuitBreakerManager
from risk.engine import RiskEngine
from risk.position_sizer import PositionSizer
from risk.trading_costs import swap_money_per_lot
from strategies.backtest.fills import exit_fill


def _spec(**overrides) -> SymbolSpecification:
    data = dict(
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
    data.update(overrides)
    return SymbolSpecification(**data)


def _account(**overrides) -> AccountState:
    data = dict(
        login=1,
        server="demo",
        balance=10000.0,
        equity=10000.0,
        free_margin=10000.0,
        margin=0.0,
        peak_equity=10000.0,
    )
    data.update(overrides)
    return AccountState(**data)


def _proposal() -> TradeProposal:
    return TradeProposal(
        decision_id=uuid4(),
        strategy_id="STRAT_TEST",
        symbol="EURUSD",
        action="BUY",
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        target_risk_pct=0.25,
    )


class _Broker:
    def __init__(self, positions):
        self._positions = positions

    async def get_open_positions(self, symbol=None):
        return list(self._positions)


def test_symbol_mapper_suffix_and_alias():
    mapper = SymbolMapper(suffix="m", aliases={"XAUUSD": "GOLD.m"})
    assert mapper.to_broker("EURUSD") == "EURUSDm"
    assert mapper.to_logical("EURUSDm") == "EURUSD"
    assert mapper.to_broker("XAUUSD") == "GOLD.m"
    assert mapper.same_instrument("EURUSD", "EURUSDm")


def test_pnl_from_deals_and_positions_trips_daily_breaker():
    deals = [SimpleNamespace(profit=-100.0, swap=-5.0, commission=-2.0, fee=0.0)]
    positions = [SimpleNamespace(profit=-60.0, swap=-3.0)]
    realized = realized_from_deals(deals)
    unrealized = unrealized_from_positions(positions)
    daily = pnl_percent(10000.0, realized, unrealized)
    assert daily == pytest.approx(-1.70, abs=0.01)
    account = _account(daily_pnl_pct=daily, weekly_pnl_pct=daily)
    ok, reason = CircuitBreakerManager().check_all(account, current_time=datetime(2026, 11, 18, 12, tzinfo=timezone.utc))
    assert ok is False
    assert "DAILY" in reason


def test_terminal_min_lot_beats_config_and_does_not_round_up():
    spec = _spec(volume_min=0.01, volume_step=0.01, volume_max=100.0)
    lot = PositionSizer.calculate_lot(
        risk_money=20.0,
        entry_price=1.1000,
        stop_loss_price=1.0900,
        spec=spec,
        config_min_volume=0.10,
    )
    # 20 / (0.01/0.00001) = 0.02. O mínimo do YAML (0.10) não arredonda para cima.
    assert lot == 0.02
    below = PositionSizer.normalize_lot(0.009, spec.volume_min, spec.volume_max, spec.volume_step)
    assert below == 0.0


def test_swap_triple_wednesday_is_three_times_monday():
    spec = _spec(swap_long=-2.0, swap_short=-1.0, swap_rollover3days=3, swap_mode="points")
    monday = datetime(2026, 1, 5, tzinfo=timezone.utc)  # segunda, dia MT5 = 1
    wednesday = datetime(2026, 1, 7, tzinfo=timezone.utc)  # quarta, dia MT5 = 3
    once = swap_money_per_lot(spec, "BUY", monday, 1.10, use_catalog=False)
    triple = swap_money_per_lot(spec, "BUY", wednesday, 1.10, use_catalog=False)
    assert once < 0
    assert triple == pytest.approx(once * 3)


def test_gap_through_stop_fills_at_open_and_both_sides_stop_first():
    # Compra: abre abaixo do stop (gap) e a barra também alcança o alvo.
    bar = MarketBar(
        symbol="EURUSD",
        timeframe=TimeFrame.M15,
        time=datetime(2026, 11, 18, 12, tzinfo=timezone.utc),
        open=1.0900,
        high=1.1200,
        low=1.0890,
        close=1.1100,
        tick_volume=10,
    )
    fill = exit_fill("BUY", bar, stop_loss=1.0950, take_profit=1.1100, spread_price=0.00013, slippage_price=0.00002)
    assert fill is not None
    assert fill.reason == "STOP_LOSS"
    assert fill.price == pytest.approx(1.0900 - 0.00002)
    assert fill.price < 1.0950


def test_margin_check_rejects_when_usage_exceeds_cap():
    engine = RiskEngine(max_margin_usage_pct=20.0, stop_out_level_pct=30.0)
    account = _account(equity=10000.0, free_margin=9000.0, margin=1000.0)
    ok, reason = engine.assess_margin(account, margin_required=5000.0)
    assert ok is False
    assert "MARGIN" in reason
    ok_small, _ = engine.assess_margin(account, margin_required=100.0)
    assert ok_small is True


def test_invalid_config_fails_fast(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    source = load_hermes_config()
    assert source.broker.account_currency == "USC"
    root = Path(__file__).resolve().parents[2]
    for name in ("system.yaml", "instruments.yaml", "strategies.yaml", "models.yaml", "risk.yaml"):
        (config_dir / name).write_text((root / "config" / name).read_text(encoding="utf-8"), encoding="utf-8")
    risk = yaml.safe_load((config_dir / "risk.yaml").read_text(encoding="utf-8"))
    risk["per_trade"]["risk_percentage"] = 5.0
    (config_dir / "risk.yaml").write_text(yaml.safe_dump(risk), encoding="utf-8")
    with pytest.raises(Exception):
        load_hermes_config(config_dir)


def test_monitoring_startup_requires_operator_token(monkeypatch):
    monkeypatch.delenv("HERMES_OPERATOR_TOKEN", raising=False)
    with pytest.raises(MissingSecretError):
        create_monitoring_app()


@pytest.mark.asyncio
async def test_partial_fill_is_tracked_not_rejected(tmp_path):
    from execution.adapters.paper import PaperTradingAdapter

    adapter = PaperTradingAdapter(initial_balance=10000.0)
    await adapter.connect()
    executor = OrderExecutor(adapter=adapter, store=SqliteIdempotencyStore(db_path=tmp_path / "idem.db"))
    original = adapter.send_order

    async def _partial(request):
        result = await original(request)
        return result.model_copy(update={"retcode": 10010, "volume_executed": request.volume / 2, "comment": "PARTIAL"})

    adapter.send_order = _partial  # type: ignore[method-assign]
    proposal = _proposal()
    auth = RiskAuthorization(
        decision_id=proposal.decision_id,
        symbol="EURUSD",
        action="BUY",
        approved=True,
        authorized_lot=0.10,
        stop_loss=1.0950,
        take_profit=1.1100,
    )
    result = await executor.execute_order(proposal, auth)
    assert result.success is True
    assert result.retcode == 10010
    assert result.volume_executed == pytest.approx(0.05)
    stored = executor.store.get_intent_by_key(result.idempotency_key)
    assert stored["state"] == OrderLifecycleState.PARTIALLY_FILLED.value
    positions = await adapter.get_open_positions()
    assert len(positions) == 1


@pytest.mark.asyncio
async def test_recovery_matches_suffixed_symbol_and_peak_survives(tmp_path):
    mapper = SymbolMapper(suffix=".m")
    store = SqliteIdempotencyStore(db_path=tmp_path / "idem.db")
    proposal = _proposal()
    auth = RiskAuthorization(
        decision_id=proposal.decision_id,
        symbol="EURUSD",
        action="BUY",
        approved=True,
        authorized_lot=0.10,
        stop_loss=1.0950,
        take_profit=1.1100,
    )
    store.register_intent_pre_submission(
        intent_id=proposal.proposal_id,
        idempotency_key="recover-1",
        decision_id=proposal.decision_id,
        auth_id=auth.auth_id,
        strategy_id=proposal.strategy_id,
        symbol="EURUSD",
        action="BUY",
        requested_lot=0.10,
        authorized_lot=0.10,
        entry_price=1.10,
        stop_loss=1.095,
        take_profit=1.11,
        magic=100001,
    )
    position = Position(
        ticket=77,
        symbol="EURUSD.m",
        magic=100001,
        position_type="BUY",
        volume=0.10,
        open_price=1.10,
        stop_loss=1.095,
        current_price=1.101,
        open_time=datetime(2026, 11, 18, tzinfo=timezone.utc),
    )
    executor = OrderExecutor(adapter=_Broker([position]), store=store, symbol_mapper=mapper)
    recovered = await executor.recover_unresolved_orders()
    assert recovered[0]["status"] == "RECONCILED_FILLED"
    assert recovered[0]["ticket"] == 77

    state_path = tmp_path / "state.json"
    manager = ExecutionStateManager(str(state_path))
    manager.current_state.peak_equity = 12500.0
    manager.current_state.current_drawdown_pct = 4.0
    manager.save_state()
    restored = ExecutionStateManager(str(state_path))
    loaded = restored.load_state()
    assert loaded is not None
    assert loaded.peak_equity == 12500.0


@pytest.mark.asyncio
async def test_requote_reprices_and_preserves_idempotency():
    adapter = WindowsMT5Adapter(max_retry_attempts=3, retry_delay_seconds=0.0)
    mock_mt5 = MagicMock()
    mock_mt5.ORDER_TYPE_BUY = 0
    mock_mt5.TRADE_ACTION_DEAL = 1
    mock_mt5.ORDER_TIME_GTC = 0
    mock_mt5.ORDER_FILLING_IOC = 1
    mock_mt5.ORDER_FILLING_FOK = 0
    mock_mt5.ORDER_FILLING_RETURN = 2
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.TRADE_RETCODE_DONE_PARTIAL = 10010
    mock_mt5.TRADE_RETCODE_REQUOTE = 10004
    mock_mt5.TRADE_RETCODE_PRICE_CHANGED = 10020
    mock_mt5.TRADE_RETCODE_PRICE_OFF = 10021
    mock_mt5.TRADE_RETCODE_TIMEOUT = 10012
    mock_mt5.TRADE_RETCODE_CONNECTION = 10031
    info = MagicMock()
    info.filling_mode = 2
    mock_mt5.symbol_info.return_value = info
    mock_mt5.symbol_info_tick.return_value = SimpleNamespace(bid=1.1002, ask=1.1004)
    prices = []

    def _send(req):
        prices.append(req["price"])
        result = MagicMock()
        if len(prices) == 1:
            result.retcode = 10004
            result.order = 0
            result.deal = 0
            result.volume = 0.0
            result.price = 0.0
            result.comment = "Requote"
            return result
        result.retcode = 10009
        result.order = 42
        result.deal = 43
        result.volume = req["volume"]
        result.price = req["price"]
        result.comment = "Done"
        return result

    mock_mt5.order_send.side_effect = _send
    request = OrderRequest(
        auth_id=uuid4(),
        symbol="EURUSD",
        action="BUY",
        volume=0.10,
        price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        magic=7,
        idempotency_key="requote-key",
    )
    with patch("execution.adapters.windows_mt5.mt5", mock_mt5):
        first = await adapter.send_order(request)
        second = await adapter.send_order(request)
    assert first.success is True
    assert first.price_executed == pytest.approx(1.1004)
    assert prices[0] == pytest.approx(1.1000)
    assert prices[1] == pytest.approx(1.1004)
    assert mock_mt5.order_send.call_count == 2
    assert second.success is True
    assert second.order_ticket == first.order_ticket
    assert mock_mt5.order_send.call_count == 2


@pytest.mark.asyncio
async def test_windows_partial_fill_is_success():
    adapter = WindowsMT5Adapter(max_retry_attempts=1, retry_delay_seconds=0.0)
    mock_mt5 = MagicMock()
    mock_mt5.ORDER_TYPE_BUY = 0
    mock_mt5.TRADE_ACTION_DEAL = 1
    mock_mt5.ORDER_TIME_GTC = 0
    mock_mt5.ORDER_FILLING_IOC = 1
    mock_mt5.ORDER_FILLING_RETURN = 2
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.TRADE_RETCODE_DONE_PARTIAL = 10010
    info = MagicMock()
    info.filling_mode = 2
    mock_mt5.symbol_info.return_value = info
    result = MagicMock(retcode=10010, order=9, deal=10, volume=0.04, price=1.1, comment="Partial")
    mock_mt5.order_send.return_value = result
    request = OrderRequest(
        auth_id=uuid4(),
        symbol="EURUSD",
        action="BUY",
        volume=0.10,
        price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        magic=7,
        idempotency_key="partial-mt5",
    )
    with patch("execution.adapters.windows_mt5.mt5", mock_mt5):
        filled = await adapter.send_order(request)
    assert filled.success is True
    assert filled.retcode == 10010
    assert filled.volume_executed == pytest.approx(0.04)
    assert mock_mt5.order_send.call_count == 1


def test_peak_equity_restore_on_paper_adapter():
    from execution.adapters.paper import PaperTradingAdapter

    adapter = PaperTradingAdapter(initial_balance=10000.0)
    adapter.restore_peak_equity(12000.0)
    assert adapter.current_peak_equity() == 12000.0
