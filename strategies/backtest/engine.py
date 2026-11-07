"""
QUANT HERMES — Motor Determinístico de Backtesting Histórico
Módulo: strategies.backtest.engine
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import numpy as np

from core.logger import get_logger
from core.models.agent import AgentSignal, SignalDirection
from core.models.base import utc_now
from core.models.market import MarketBar, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, Position, TradeProposal
from risk.engine import RiskEngine
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


class BacktestEngine:
    """
    Simulador determinístico de backtesting sobre dados históricos.
    Garante:
    1. Prevenção estrita de Viés de Antecipação (Anti-Lookahead Bias) — a estratégia
       só tem visibilidade até o índice da barra atual (t).
    2. Modelagem realista de execução: verificação de Stop Loss e Take Profit
       barra a barra através das máximas e mínimas (High/Low).
    3. Integração com o RiskEngine para dimensionamento fiel e autorização soberana.
    4. Estatísticas avançadas de performance (Sharpe, Profit Factor, Drawdown).
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
        spread_points: float = 0.00015,
    ) -> BacktestResult:
        """
        Executa a simulação completa da estratégia sobre a lista cronológica de barras.
        """
        if len(bars) < 30:
            return BacktestResult(
                strategy_id=strategy.strategy_id,
                symbol=spec.symbol,
                timeframe="UNKNOWN",
            )

        symbol = spec.symbol
        timeframe_str = bars[0].timeframe.value if hasattr(bars[0].timeframe, "value") else str(bars[0].timeframe)

        equity = self.initial_balance
        peak_equity = self.initial_balance
        max_drawdown = 0.0

        equity_curve: List[float] = [equity]
        trades: List[BacktestTrade] = []
        active_trade: Optional[BacktestTrade] = None
        trade_counter = 0

        # Itera sequencialmente sobre as barras para eliminar qualquer viés futuro
        # Janela mínima para permitir cálculo de indicadores
        min_warmup = 30

        for t in range(min_warmup, len(bars)):
            current_bar = bars[t]
            # Visibilidade estritamente até a barra t (passado + presente)
            historical_slice = bars[: t + 1]

            # 1. Gerencia posição em aberto contra a barra atual
            if active_trade is not None:
                # Checa se Stop Loss ou Take Profit foi atingido
                exit_price = None
                exit_reason = None

                if active_trade.direction == "BUY":
                    if current_bar.low <= active_trade.stop_loss:
                        exit_price = active_trade.stop_loss
                        exit_reason = "STOP_LOSS"
                    elif current_bar.high >= active_trade.take_profit:
                        exit_price = active_trade.take_profit
                        exit_reason = "TAKE_PROFIT"

                elif active_trade.direction == "SELL":
                    if current_bar.high >= active_trade.stop_loss:
                        exit_price = active_trade.stop_loss
                        exit_reason = "STOP_LOSS"
                    elif current_bar.low <= active_trade.take_profit:
                        exit_price = active_trade.take_profit
                        exit_reason = "TAKE_PROFIT"

                if exit_price is not None:
                    # Encerra o trade
                    active_trade.exit_time = current_bar.time
                    active_trade.exit_price = exit_price
                    active_trade.exit_reason = exit_reason

                    # Calcula PnL financeiro
                    sl_dist = abs(active_trade.entry_price - active_trade.stop_loss)
                    if active_trade.direction == "BUY":
                        price_diff = exit_price - active_trade.entry_price
                    else:
                        price_diff = active_trade.entry_price - exit_price

                    pnl_ticks = price_diff / spec.tick_size
                    pnl_money = pnl_ticks * spec.tick_value * active_trade.lot_size
                    r_mult = price_diff / sl_dist if sl_dist > 0 else 0.0

                    active_trade.pnl = round(pnl_money, 2)
                    active_trade.pnl_pct = round((pnl_money / equity) * 100.0, 3)
                    active_trade.r_multiple = round(r_mult, 2)

                    equity += pnl_money
                    peak_equity = max(peak_equity, equity)
                    dd = ((peak_equity - equity) / peak_equity) * 100.0
                    max_drawdown = max(max_drawdown, dd)

                    trades.append(active_trade)
                    active_trade = None

            # Registra equity atualizada
            equity_curve.append(round(equity, 2))

            # 2. Se não houver posição aberta, avalia novo sinal da estratégia
            if active_trade is None:
                signal: Optional[AgentSignal] = strategy.analyze(
                    bars=historical_slice,
                    symbol=symbol,
                    timeframe=current_bar.timeframe,
                )

                if signal is not None and signal.direction in (SignalDirection.BUY, SignalDirection.SELL):
                    # Simula avaliação e autorização do Risk Engine
                    account_state = AccountState(
                        login=11111,
                        server="BacktestServer",
                        balance=equity,
                        equity=equity,
                        free_margin=equity,
                        peak_equity=peak_equity,
                        current_drawdown_pct=((peak_equity - equity) / peak_equity) * 100.0,
                    )

                    proposal = TradeProposal(
                        decision_id=signal.signal_id,
                        strategy_id=strategy.strategy_id,
                        symbol=symbol,
                        action=signal.direction.value,
                        entry_price=signal.suggested_entry,
                        stop_loss=signal.suggested_stop,
                        take_profit=signal.suggested_target,
                        target_risk_pct=risk_per_trade_pct,
                    )

                    auth = self.risk_engine.evaluate_proposal(
                        proposal=proposal,
                        account_state=account_state,
                        current_tick=None,
                        normal_spread=spread_points,
                        spec=spec,
                        open_positions=[],
                    )

                    if auth.approved and auth.authorized_lot > 0:
                        trade_counter += 1
                        active_trade = BacktestTrade(
                            trade_id=trade_counter,
                            symbol=symbol,
                            direction=signal.direction.value,
                            entry_time=current_bar.time,
                            entry_price=signal.suggested_entry,
                            stop_loss=signal.suggested_stop,
                            take_profit=signal.suggested_target,
                            lot_size=auth.authorized_lot,
                        )

        # 3. Consolidação estatística
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]

        total_trades_count = len(trades)
        win_rate = (len(winning_trades) / total_trades_count * 100.0) if total_trades_count > 0 else 0.0

        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        total_net_pnl = round(equity - self.initial_balance, 2)
        total_return_pct = round((total_net_pnl / self.initial_balance) * 100.0, 2)

        # Cálculo do Sharpe Ratio simplificado por trades
        trade_returns = [t.pnl_pct for t in trades]
        if len(trade_returns) > 1 and np.std(trade_returns) > 0:
            sharpe = (np.mean(trade_returns) / np.std(trade_returns)) * np.sqrt(252)
        else:
            sharpe = 0.0

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
            sharpe_ratio=round(float(sharpe), 2),
            trades=trades,
            equity_curve=equity_curve,
        )
