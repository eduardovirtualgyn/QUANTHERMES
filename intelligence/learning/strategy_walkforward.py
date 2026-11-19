"""
QUANT HERMES — Walk-forward das estratégias, fora da amostra, com custos
Módulo: intelligence.learning.strategy_walkforward

Avalia cada estratégia (e cada conjunto de parâmetros) só na janela de teste.
O ajuste de testes múltiplos usa o Deflated Sharpe Ratio (Bailey e López de Prado)
e um limiar de Bonferroni sobre o t-stat da expectância em R.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Type

import numpy as np
from scipy.stats import norm

from core.models.market import MarketBar, SymbolSpecification
from intelligence.learning.validation import (
    ValidationFoldResult,
    ValidationReport,
    audit_market_data_integrity,
)
from risk.engine import RiskEngine
from risk.trading_costs import default_spread_price
from strategies.backtest.engine import BacktestEngine
from strategies.backtest.metrics import r_expectancy_stats
from strategies.base import BaseStrategy
from strategies.breakout.volatility_breakout import VolatilityBreakoutStrategy
from strategies.mean_reversion.statistical_reversion import StatisticalMeanReversionStrategy
from strategies.momentum.momentum_surge import MomentumSurgeStrategy
from strategies.pullback.trend_pullback import TrendPullbackStrategy
from strategies.scalping.micro_momentum import MicroMomentumScalpingStrategy
from strategies.smc.structure_break import SMCStructureStrategy
from strategies.swing.macro_swing import MacroSwingStrategy

STRATEGY_CATALOG: List[Type[BaseStrategy]] = [
    MicroMomentumScalpingStrategy,
    VolatilityBreakoutStrategy,
    MomentumSurgeStrategy,
    TrendPullbackStrategy,
    StatisticalMeanReversionStrategy,
    SMCStructureStrategy,
    MacroSwingStrategy,
]

DEFAULT_PARAMETER_SETS: List[Dict[str, Any]] = [
    {"min_rr_ratio": 1.5},
    {"min_rr_ratio": 2.0},
]


def deflated_sharpe_probability(
    observed_sharpe: float,
    trial_sharpes: Sequence[float],
    n_obs: int,
    skew: float,
    kurtosis: float,
) -> float:
    """
    Probabilidade de o Sharpe observado exceder o máximo esperado sob a nula,
    dados N ensaios. Sharpe aqui é por observação (não anualizado).
    """
    n_trials = max(1, len(trial_sharpes))
    if n_obs < 3 or n_trials < 1:
        return 0.0
    if n_trials == 1:
        sr0 = 0.0
    else:
        variance = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0
        variance = max(variance, 1.0 / max(n_obs - 1, 1))
        euler = 0.5772156649015329
        z1 = float(norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(norm.ppf(1.0 - 1.0 / (n_trials * np.e)))
        sr0 = np.sqrt(variance) * ((1.0 - euler) * z1 + euler * z2)
    denom_inner = 1.0 - skew * observed_sharpe + ((kurtosis - 1.0) / 4.0) * observed_sharpe ** 2
    denom = np.sqrt(max(denom_inner, 1e-12))
    z_score = ((observed_sharpe - sr0) * np.sqrt(n_obs - 1)) / denom
    return float(norm.cdf(z_score))


def _per_period_sharpe(values: Sequence[float]) -> tuple[float, float, float]:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 3 or float(np.std(arr, ddof=1)) <= 0.0:
        return 0.0, 0.0, 3.0
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    sharpe = mean / std
    skew = float(np.mean(((arr - mean) / std) ** 3))
    kurt = float(np.mean(((arr - mean) / std) ** 4))
    return sharpe, skew, kurt


def default_strategies() -> List[BaseStrategy]:
    built: List[BaseStrategy] = []
    for cls in STRATEGY_CATALOG:
        for params in DEFAULT_PARAMETER_SETS:
            try:
                built.append(cls(**params))
            except TypeError:
                built.append(cls())
    return built


def _spec_or_default(bars: List[MarketBar], spec: Optional[SymbolSpecification]) -> SymbolSpecification:
    if spec is not None:
        return spec
    return SymbolSpecification(
        symbol=bars[0].symbol,
        canonical_name=bars[0].symbol,
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


def evaluate_strategies_oos(validator: Any, bars: List[MarketBar], spec: Optional[SymbolSpecification], strategies: Optional[List[BaseStrategy]]) -> ValidationReport:
    """Roda o validador purgado sobre estratégias, com os custos do próprio validador."""
    integrity = audit_market_data_integrity(bars)
    if not integrity.is_valid:
        pass

    spec = _spec_or_default(bars, spec)
    strategies = strategies or default_strategies()
    n_trials = max(1, len(strategies))
    splits = validator.generate_purged_splits_by_timestamp(bars)
    engine = BacktestEngine(risk_engine=RiskEngine(), initial_balance=10000.0)
    spread = validator.spread_points if validator.spread_points > 0 else default_spread_price(spec.canonical_name)
    slippage = validator.slippage_points

    fold_results: List[ValidationFoldResult] = []
    trial_r: Dict[int, List[float]] = {i: [] for i in range(len(strategies))}
    trial_costs: Dict[int, float] = {i: 0.0 for i in range(len(strategies))}

    for fold_idx, (_train_idx, test_idx, purged_count, embargo_count) in enumerate(splits):
        if len(test_idx) < 5:
            continue
        test_start = int(test_idx[0])
        test_end = int(test_idx[-1]) + 1
        warmup_start = max(0, test_start - 80)
        window = bars[warmup_start:test_end]
        test_start_time = bars[test_start].time
        fold_pnls: List[float] = []
        gross_profit = 0.0
        gross_loss = 0.0
        total_costs = 0.0
        wins = 0
        losses = 0

        for trial_idx, strategy in enumerate(strategies):
            result = engine.run(
                strategy=strategy,
                bars=window,
                spec=spec,
                spread_points=spread,
                slippage_price=slippage,
                charge_swap=True,
            )
            oos = [trade for trade in result.trades if trade.entry_time >= test_start_time]
            for trade in oos:
                fold_pnls.append(trade.pnl)
                trial_r[trial_idx].append(trade.r_multiple)
                cost = abs(trade.spread_cost) + abs(min(trade.swap_paid, 0.0))
                # Comissão configurada no validador, por lote, ida e volta.
                commission = validator.commission_per_lot * trade.lot_size
                cost += commission
                total_costs += cost
                trial_costs[trial_idx] += cost
                if trade.pnl > 0:
                    wins += 1
                    gross_profit += trade.pnl
                else:
                    losses += 1
                    gross_loss += abs(trade.pnl)

        total_trades = wins + losses
        win_rate = (wins / total_trades * 100.0) if total_trades else 0.0
        pf = round(gross_profit / max(gross_loss + total_costs, 1e-9), 4) if total_trades else 0.0
        net_profit = sum(fold_pnls) - total_costs
        equity = 10000.0
        peak = equity
        max_dd = 0.0
        curve = [equity]
        for pnl in fold_pnls:
            equity += pnl
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
            curve.append(equity)
        if len(fold_pnls) > 1 and float(np.std(fold_pnls)) > 0:
            # Sharpe do fold em frequência de trade, só para o campo legado.
            # A decisão usa o Sharpe por barra / DSR calculado no consolidado.
            sharpe = float(np.mean(fold_pnls) / np.std(fold_pnls, ddof=1))
            downside = [p for p in fold_pnls if p < 0]
            down_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else float(np.std(fold_pnls, ddof=1))
            sortino = float(np.mean(fold_pnls) / max(down_std, 1e-9))
        else:
            sharpe = 0.0
            sortino = 0.0
        friction_2x = total_costs * 2.0 if total_trades else 0.0
        pf_2x = round(gross_profit / max(gross_loss + friction_2x, 1e-9), 4) if total_trades else 0.0

        fold_results.append(
            ValidationFoldResult(
                fold_idx=fold_idx,
                train_start_time=bars[0].time.isoformat(),
                train_end_time=bars[max(0, test_start - 1)].time.isoformat(),
                test_start_time=bars[test_start].time.isoformat(),
                test_end_time=bars[test_end - 1].time.isoformat(),
                purged_bars_count=purged_count,
                embargoed_bars_count=embargo_count,
                accuracy=round(win_rate / 100.0, 4),
                total_trades=total_trades,
                winning_trades=wins,
                losing_trades=losses,
                win_rate_pct=round(win_rate, 2),
                gross_profit=round(gross_profit, 2),
                gross_loss=round(gross_loss, 2),
                total_costs_paid=round(total_costs, 2),
                net_profit=round(net_profit, 2),
                profit_factor=pf,
                max_drawdown_pct=round(max_dd * 100.0, 2),
                sharpe_ratio=round(sharpe, 4),
                sortino_ratio=round(sortino, 4),
                cost_sensitivity_pf_2x=pf_2x,
            )
        )

    if not fold_results:
        return ValidationReport(
            is_approved_for_production=False,
            rejection_reasons=["Nenhum fold atendeu aos critérios mínimos de balanceamento"],
            total_folds=0,
            mean_profit_factor=0.0,
            mean_win_rate=0.0,
            mean_sharpe=0.0,
            mean_sortino=0.0,
            max_drawdown_observed=1.0,
            total_oos_trades=0,
            total_net_pnl=0.0,
            total_transaction_costs=0.0,
            cost_sensitivity_pf_2x_mean=0.0,
            fold_results=[],
            n_trials=n_trials,
        )

    trial_sharpes = []
    best_sharpe = 0.0
    best_skew = 0.0
    best_kurt = 3.0
    best_n = 0
    all_r: List[float] = []
    for values in trial_r.values():
        all_r.extend(values)
        sharpe, skew, kurt = _per_period_sharpe(values)
        trial_sharpes.append(sharpe)
        if abs(sharpe) >= abs(best_sharpe):
            best_sharpe = sharpe
            best_skew = skew
            best_kurt = kurt
            best_n = len(values)

    dsr = deflated_sharpe_probability(best_sharpe, trial_sharpes, max(best_n, 3), best_skew, best_kurt)
    stats = r_expectancy_stats(all_r)
    # t crítico aproximado de duas caudas ~ 1.96; Bonferroni divide o alpha.
    bonferroni_alpha = 0.05 / n_trials
    # p aproximado pela normal para |t|
    if stats["n"] >= 2 and stats["t_stat"] != 0.0:
        p_value = float(2.0 * (1.0 - norm.cdf(abs(stats["t_stat"]))))
    else:
        p_value = 1.0
    multiple_testing_passed = bool(stats["expectancy_r"] > 0.0 and p_value < bonferroni_alpha and dsr >= 0.95)

    mean_pf = float(np.mean([f.profit_factor for f in fold_results]))
    mean_wr = float(np.mean([f.win_rate_pct for f in fold_results])) / 100.0
    mean_sh = float(np.mean([f.sharpe_ratio for f in fold_results]))
    mean_so = float(np.mean([f.sortino_ratio for f in fold_results]))
    max_dd_obs = float(max(f.max_drawdown_pct for f in fold_results)) / 100.0
    total_trades_all = sum(f.total_trades for f in fold_results)
    total_pnl_all = sum(f.net_profit for f in fold_results)
    total_costs_all = sum(f.total_costs_paid for f in fold_results)
    mean_pf_2x = float(np.mean([f.cost_sensitivity_pf_2x for f in fold_results]))

    rejection_reasons = []
    if mean_pf < validator.min_oos_profit_factor:
        rejection_reasons.append(
            f"Profit Factor OOS médio ({mean_pf:.2f}) abaixo do piso ({validator.min_oos_profit_factor:.2f})"
        )
    if mean_wr < validator.min_oos_win_rate:
        rejection_reasons.append(
            f"Taxa de acerto OOS média ({mean_wr:.2%}) abaixo do mínimo ({validator.min_oos_win_rate:.2%})"
        )
    if max_dd_obs > validator.max_oos_drawdown:
        rejection_reasons.append(
            f"Drawdown máximo observado ({max_dd_obs:.2%}) viola limite de emergência ({validator.max_oos_drawdown:.2%})"
        )
    if total_trades_all < validator.min_oos_trades:
        rejection_reasons.append(
            f"Amostra total de trades OOS ({total_trades_all}) insuficiente (mínimo {validator.min_oos_trades})"
        )
    if not multiple_testing_passed:
        rejection_reasons.append(
            f"Ajuste de testes múltiplos: DSR={dsr:.3f} em {n_trials} ensaios "
            f"(estratégias × parâmetros); p={p_value:.4f} contra Bonferroni {bonferroni_alpha:.4f}"
        )

    return ValidationReport(
        is_approved_for_production=len(rejection_reasons) == 0,
        rejection_reasons=rejection_reasons,
        total_folds=len(fold_results),
        mean_profit_factor=round(mean_pf, 2),
        mean_win_rate=round(mean_wr, 4),
        mean_sharpe=round(mean_sh, 4),
        mean_sortino=round(mean_so, 4),
        max_drawdown_observed=round(max_dd_obs, 4),
        total_oos_trades=total_trades_all,
        total_net_pnl=round(total_pnl_all, 2),
        total_transaction_costs=round(total_costs_all, 2),
        cost_sensitivity_pf_2x_mean=round(mean_pf_2x, 4),
        fold_results=fold_results,
        n_trials=n_trials,
        bonferroni_alpha=round(bonferroni_alpha, 6),
        deflated_sharpe_probability=round(dsr, 4),
        expectancy_r=round(stats["expectancy_r"], 4),
        multiple_testing_passed=multiple_testing_passed,
    )
