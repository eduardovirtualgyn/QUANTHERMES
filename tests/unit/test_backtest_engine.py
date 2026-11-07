"""
QUANT HERMES — Testes do Motor de Backtesting Histórico
Arquivo: tests/unit/test_backtest_engine.py
"""
import numpy as np
import pytest
from datetime import datetime, timedelta, timezone

from core.models.market import MarketBar, SymbolSpecification, TimeFrame
from risk.engine import RiskEngine
from risk.kill_switch import KillSwitch
from risk.circuit_breakers import CircuitBreakerManager
from strategies.backtest.engine import BacktestEngine
from strategies.breakout.volatility_breakout import VolatilityBreakoutStrategy
from strategies.scalping.micro_momentum import MicroMomentumScalpingStrategy


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
def backtest_bars():
    """Gera 80 barras sintéticas onde ocorrem oportunidades de breakout."""
    np.random.seed(123)
    bars = []
    base_time = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    price = 1.08500

    for i in range(80):
        # Gera breakout na barra 40
        if i == 40:
            open_p = price
            close_p = open_p + 0.00400  # Explosão para cima
            high_p = close_p + 0.00050
            low_p = open_p - 0.00010
        elif i > 40 and i <= 45:
            # Continua subindo para atingir take profit
            open_p = price
            close_p = open_p + 0.00100
            high_p = close_p + 0.00150
            low_p = open_p
        else:
            open_p = price
            close_p = open_p + np.random.normal(0, 0.0002)
            high_p = max(open_p, close_p) + 0.0001
            low_p = min(open_p, close_p) - 0.0001

        bars.append(
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M5,
                time=base_time + timedelta(minutes=5 * i),
                open=round(open_p, 5),
                high=round(high_p, 5),
                low=round(low_p, 5),
                close=round(close_p, 5),
                tick_volume=100.0,
            )
        )
        price = close_p

    return bars


@pytest.fixture
def backtest_engine(tmp_path):
    ks = KillSwitch(state_file_path=tmp_path / "bt_ks.json")
    cb = CircuitBreakerManager()
    risk_engine = RiskEngine(kill_switch=ks, circuit_breakers=cb)
    return BacktestEngine(risk_engine=risk_engine, initial_balance=100000.0)


class TestBacktestEngine:
    """Testes de integridade do motor de backtesting."""

    def test_backtest_executes_and_produces_metrics(self, backtest_engine, backtest_bars, eurusd_spec):
        strat = VolatilityBreakoutStrategy(min_rr_ratio=2.0)
        result = backtest_engine.run(
            strategy=strat,
            bars=backtest_bars,
            spec=eurusd_spec,
            risk_per_trade_pct=0.25,
        )

        assert result.strategy_id == strat.strategy_id
        assert result.symbol == "EURUSD"
        assert len(result.equity_curve) > 0
        assert result.max_drawdown_pct >= 0.0
        assert isinstance(result.win_rate_pct, float)
        assert isinstance(result.profit_factor, float)

    def test_backtest_with_insufficient_bars_returns_empty_result(self, backtest_engine, eurusd_spec):
        bars = [
            MarketBar(
                symbol="EURUSD",
                timeframe=TimeFrame.M5,
                time=datetime.now(timezone.utc),
                open=1.085,
                high=1.086,
                low=1.084,
                close=1.085,
                tick_volume=10.0,
            )
        ]
        strat = MicroMomentumScalpingStrategy()
        result = backtest_engine.run(strat, bars, eurusd_spec)
        assert result.total_trades == 0
        assert len(result.trades) == 0

    def test_backtest_respects_risk_engine_authorization(self, tmp_path, backtest_bars, eurusd_spec):
        # Se o Kill Switch estiver armado no RiskEngine, nenhuma ordem deve ser aceita
        ks = KillSwitch(state_file_path=tmp_path / "bt_ks_frozen.json")
        ks.engage(reason="PREVENT_BACKTEST_ORDERS")
        risk_engine = RiskEngine(kill_switch=ks)
        engine = BacktestEngine(risk_engine=risk_engine, initial_balance=100000.0)

        strat = VolatilityBreakoutStrategy()
        result = engine.run(strat, backtest_bars, eurusd_spec)
        assert result.total_trades == 0  # Todas as ordens foram recusadas pelo Risk Engine
