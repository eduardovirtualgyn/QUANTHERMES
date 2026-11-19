"""
QUANT HERMES — Motor Determinístico de Backtesting Histórico
Módulo: strategies.backtest.engine
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from core.logger import get_logger
from core.models.agent import AgentSignal, SignalDirection
from core.models.market import MarketBar, MarketTick, SymbolSpecification
from core.models.risk import AccountState, TradeProposal
from risk.engine import RiskEngine
from risk.trading_costs import default_slippage_price, default_spread_price, swap_money_per_lot
from strategies.backtest.fills import entry_price, exit_fill
from strategies.backtest.metrics import r_expectancy_stats, sharpe_from_equity
from strategies.base import BaseStrategy

logger = get_logger("strategies.backtest.engine")


@dataclass
class BacktestTrade:
    """Registro de uma operação simulada no backtest."""
    trade_id: int
    symbol: str
    direction: str
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str = "OPEN"
    swap_paid: float = 0.0
    spread_cost: float = 0.0


@dataclass
class BacktestResult:
    """Métricas consolidadas de desempenho do backtest quantitativo."""
    strategy_id: str
    symbol: str
    timeframe: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    total_net_pnl: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    expectancy_r: float = 0.0
    t_stat: float = 0.0
    ci95_low_r: float = 0.0
    ci95_high_r: float = 0.0
    total_costs: float = 0.0
    total_swap: float = 0.0
    total_spread_slippage: float = 0.0


class BacktestEngine:
    """
    Simulador determinístico de backtesting sobre dados históricos.
    Garante:
    1. Prevenção estrita de viés de antecipação — a estratégia só vê barras até t.
    2. Saída conservadora: gap no stop preenche no open; stop e alvo na mesma barra
       assumem o stop primeiro; compra no ask e venda no bid.
    3. Custos por símbolo: spread, slippage e swap (incluindo o dia triplo).
    4. Sharpe anualizado pela frequência real da barra, mais expectância em R,
       profit factor, drawdown, número de trades e t-stat/IC.
    """

    def __init__(
        self,
        risk_engine: Optional[RiskEngine] = None,
        initial_balance: float = 100000.0,
    ):
        self.risk_engine = risk_engine or RiskEngine()
        self.initial_balance = initial_balance

    def run(
        self,
        strategy: BaseStrategy,
        bars: List[MarketBar],
        spec: SymbolSpecification,
        risk_per_trade_pct: float = 0.25,
        spread_points: Optional[float] = None,
        slippage_price: Optional[float] = None,
        charge_swap: bool = True,
    ) -> BacktestResult:
        """
        Executa a simulação completa da estratégia sobre a lista cronológica de barras.
        `spread_points` é a distância de preço do spread (o nome histórico do argumento).
        """
        symbol = spec.canonical_name or spec.symbol
        if len(bars) < 30:
            return BacktestResult(
                strategy_id=strategy.strategy_id,
                symbol=symbol,
                timeframe="UNKNOWN",
            )

        timeframe_str = bars[0].timeframe.value if hasattr(bars[0].timeframe, "value") else str(bars[0].timeframe)
        spread = spread_points if spread_points is not None else default_spread_price(symbol)
        slippage = slippage_price if slippage_price is not None else default_slippage_price(symbol)
        spread = max(0.0, float(spread))
        slippage = max(0.0, float(slippage))

        equity = self.initial_balance
        peak_equity = self.initial_balance
        max_drawdown = 0.0
        equity_curve: List[float] = [equity]
        trades: List[BacktestTrade] = []
        active_trade: Optional[BacktestTrade] = None
        last_swap_date = None
        trade_counter = 0
        total_swap = 0.0
        total_friction = 0.0
        min_warmup = 30

        for t in range(min_warmup, len(bars)):
            current_bar = bars[t]
            historical_slice = bars[: t + 1]

            if active_trade is not None and charge_swap:
                bar_day = current_bar.time.date()
                if last_swap_date is None:
                    last_swap_date = active_trade.entry_time.date()
                while last_swap_date < bar_day:
                    last_swap_date = last_swap_date + timedelta(days=1)
                    night = datetime.combine(last_swap_date, datetime.min.time(), tzinfo=current_bar.time.tzinfo)
                    swap_value = swap_money_per_lot(
                        spec,
                        active_trade.direction,
                        night,
                        active_trade.entry_price,
                        use_catalog=True,
                    ) * active_trade.lot_size
                    active_trade.swap_paid = round(active_trade.swap_paid + swap_value, 4)
                    equity += swap_value
                    total_swap += swap_value

            if active_trade is not None:
                fill = exit_fill(
                    direction=active_trade.direction,
                    bar=current_bar,
                    stop_loss=active_trade.stop_loss,
                    take_profit=active_trade.take_profit,
                    spread_price=spread,
                    slippage_price=slippage,
                )
                if fill is not None:
                    active_trade.exit_time = current_bar.time
                    active_trade.exit_price = fill.price
                    active_trade.exit_reason = fill.reason

                    sl_dist = abs(active_trade.entry_price - active_trade.stop_loss)
                    if active_trade.direction == "BUY":
                        price_diff = fill.price - active_trade.entry_price
                    else:
                        price_diff = active_trade.entry_price - fill.price

                    pnl_ticks = price_diff / spec.tick_size if spec.tick_size else 0.0
                    pnl_money = pnl_ticks * spec.tick_value * active_trade.lot_size
                    r_mult = price_diff / sl_dist if sl_dist > 0 else 0.0

                    active_trade.pnl = round(pnl_money, 2)
                    active_trade.pnl_pct = round((pnl_money / equity) * 100.0, 4) if equity else 0.0
                    active_trade.r_multiple = round(r_mult, 4)

                    equity += pnl_money
                    peak_equity = max(peak_equity, equity)
                    dd = ((peak_equity - equity) / peak_equity) * 100.0 if peak_equity else 0.0
                    max_drawdown = max(max_drawdown, dd)

                    trades.append(active_trade)
                    active_trade = None
                    last_swap_date = None

            equity_curve.append(round(equity, 2))

            if active_trade is None:
                signal: Optional[AgentSignal] = strategy.analyze(
                    bars=historical_slice,
                    symbol=symbol,
                    timeframe=current_bar.timeframe,
                )
                if signal is None or signal.direction not in (SignalDirection.BUY, SignalDirection.SELL):
                    continue

                direction = signal.direction.value
                filled_entry = entry_price(direction, signal.suggested_entry, spread, slippage)
                stop = signal.suggested_stop
                target = signal.suggested_target
                if direction == "BUY" and stop >= filled_entry:
                    continue
                if direction == "SELL" and stop <= filled_entry:
                    continue
                if filled_entry <= 0.0:
                    continue

                bid = current_bar.close
                ask = current_bar.close + spread
                tick = MarketTick(
                    symbol=symbol,
                    time=current_bar.time,
                    bid=max(bid, 1e-8),
                    ask=max(ask, bid),
                    last=current_bar.close,
                    volume=float(current_bar.tick_volume),
                )
                raw_dd = ((peak_equity - equity) / peak_equity) * 100.0 if peak_equity else 0.0
                account_state = AccountState(
                    login=11111,
                    server="BacktestServer",
                    balance=max(equity, 0.0),
                    equity=max(equity, 0.0),
                    free_margin=max(equity, 0.0),
                    peak_equity=max(peak_equity, equity, 0.0),
                    current_drawdown_pct=min(100.0, max(0.0, raw_dd)),
                )
                try:
                    proposal = TradeProposal(
                        decision_id=signal.signal_id,
                        strategy_id=strategy.strategy_id,
                        symbol=symbol,
                        action=direction,
                        entry_price=filled_entry,
                        stop_loss=stop,
                        take_profit=target,
                        target_risk_pct=risk_per_trade_pct,
                    )
                except ValueError:
                    continue

                auth = self.risk_engine.evaluate_proposal(
                    proposal=proposal,
                    account_state=account_state,
                    current_tick=tick,
                    normal_spread=spread if spread > 0 else None,
                    spec=spec,
                    open_positions=[],
                )
                if not auth.approved or auth.authorized_lot <= 0:
                    continue

                friction = (spread + slippage) / spec.tick_size * spec.tick_value * auth.authorized_lot
                total_friction += friction
                trade_counter += 1
                active_trade = BacktestTrade(
                    trade_id=trade_counter,
                    symbol=symbol,
                    direction=direction,
                    entry_time=current_bar.time,
                    entry_price=filled_entry,
                    stop_loss=stop,
                    take_profit=target,
                    lot_size=auth.authorized_lot,
                    spread_cost=round(friction, 4),
                )
                last_swap_date = current_bar.time.date()

        winning_trades = [trade for trade in trades if trade.pnl > 0]
        losing_trades = [trade for trade in trades if trade.pnl <= 0]
        total_trades_count = len(trades)
        win_rate = (len(winning_trades) / total_trades_count * 100.0) if total_trades_count > 0 else 0.0
        gross_profit = sum(trade.pnl for trade in winning_trades)
        gross_loss = abs(sum(trade.pnl for trade in losing_trades))
        profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        total_net_pnl = round(equity - self.initial_balance, 2)
        total_return_pct = round((total_net_pnl / self.initial_balance) * 100.0, 4) if self.initial_balance else 0.0
        stats = r_expectancy_stats(trade.r_multiple for trade in trades)
        sharpe = sharpe_from_equity(equity_curve, timeframe_str)

        return BacktestResult(
            strategy_id=strategy.strategy_id,
            symbol=symbol,
            timeframe=timeframe_str,
            total_trades=total_trades_count,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate_pct=round(win_rate, 2),
            profit_factor=profit_factor,
            total_net_pnl=total_net_pnl,
            total_return_pct=total_return_pct,
            max_drawdown_pct=round(max_drawdown, 2),
            sharpe_ratio=round(float(sharpe), 4),
            trades=trades,
            equity_curve=equity_curve,
            expectancy_r=round(stats["expectancy_r"], 4),
            t_stat=round(stats["t_stat"], 4),
            ci95_low_r=round(stats["ci95_low_r"], 4),
            ci95_high_r=round(stats["ci95_high_r"], 4),
            total_costs=round(total_friction + abs(min(total_swap, 0.0)), 4),
            total_swap=round(total_swap, 4),
            total_spread_slippage=round(total_friction, 4),
        )
