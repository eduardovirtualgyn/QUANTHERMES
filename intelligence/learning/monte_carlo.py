"""
QUANT HERMES — SIMULADOR DE ESTRESSE MONTE CARLO
Módulo: intelligence.learning.monte_carlo

Implementa análise de robustez estocástica não-paramétrica via bootstrapping com reposição.
Submete a distribuição de trades a milhares de permutações para calcular:
- Probabilidade de Ruína (atingir o circuit breaker constitucional de 8.00% de drawdown)
- VaR e CVaR (Expected Shortfall) nos percentis 95% e 99%
- Expectativa matemática de trade e intervalo de confiança da curva de equity
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np

from core.logger import get_logger

logger = get_logger("monte_carlo_stress")


@dataclass(frozen=True)
class MonteCarloReport:
    """Relatório quantitativo consolidado da simulação de estresse Monte Carlo."""
    is_robust: bool
    rejection_reasons: List[str]
    num_simulations: int
    num_trades_per_simulation: int
    probability_of_ruin: float
    max_drawdown_percentile_95: float
    max_drawdown_percentile_99: float
    max_drawdown_worst_case: float
    var_95: float
    var_99: float
    cvar_95: float
    median_terminal_equity: float
    mean_expectancy: float
    confidence_interval_95: Dict[str, float]


class MonteCarloStressTester:
    """
    Motor de estresse estatístico Monte Carlo.
    Garante que nenhuma estratégia chegue à produção sem comprovar resistência a
    riscos de cauda (Fat-Tails) e sequências adversas de perdas consecutivas.
    """

    def __init__(
        self,
        num_simulations: int = 1500,
        emergency_drawdown_limit: float = 0.08,
        max_acceptable_ruin_probability: float = 0.01,
        initial_capital: float = 10000.0,
        random_state: int = 42,
    ) -> None:
        self.num_simulations = num_simulations
        self.emergency_drawdown_limit = emergency_drawdown_limit
        self.max_acceptable_ruin_probability = max_acceptable_ruin_probability
        self.initial_capital = initial_capital
        self.random_state = random_state

    def run_stress_test(
        self,
        trade_pnls: List[float],
        trades_per_sim: Optional[int] = None,
    ) -> MonteCarloReport:
        """
        Executa a simulação Monte Carlo sobre a lista de lucros/prejuízos dos trades.
        """
        if len(trade_pnls) < 10:
            raise ValueError(f"Mínimo de 10 trades requerido para simulação Monte Carlo, recebido {len(trade_pnls)}")

        rng = np.random.default_rng(self.random_state)
        pnls = np.array(trade_pnls, dtype=float)
        n_trades = trades_per_sim if trades_per_sim is not None else len(pnls)

        sim_max_drawdowns = np.zeros(self.num_simulations)
        sim_terminal_equities = np.zeros(self.num_simulations)
        ruin_events = 0

        # Executa as simulações vetorizadas / em batch
        for sim_i in range(self.num_simulations):
            sampled_pnls = rng.choice(pnls, size=n_trades, replace=True)
            equity_curve = np.zeros(n_trades + 1)
            equity_curve[0] = self.initial_capital
            equity_curve[1:] = self.initial_capital + np.cumsum(sampled_pnls)

            # Calcula drawdown da trajetória
            running_max = np.maximum.accumulate(equity_curve)
            drawdowns = (running_max - equity_curve) / np.maximum(running_max, 1e-9)
            max_dd = float(np.max(drawdowns))
            sim_max_drawdowns[sim_i] = max_dd
            sim_terminal_equities[sim_i] = equity_curve[-1]

            if max_dd >= self.emergency_drawdown_limit:
                ruin_events += 1

        prob_of_ruin = ruin_events / self.num_simulations
        p95_dd = float(np.percentile(sim_max_drawdowns, 95))
        p99_dd = float(np.percentile(sim_max_drawdowns, 99))
        worst_dd = float(np.max(sim_max_drawdowns))

        # Value at Risk (VaR) e Conditional VaR (CVaR) sobre a perda máxima relativa
        var_95 = p95_dd
        var_99 = p99_dd
        tail_95 = sim_max_drawdowns[sim_max_drawdowns >= p95_dd]
        cvar_95 = float(np.mean(tail_95)) if len(tail_95) > 0 else p95_dd

        median_term_eq = float(np.median(sim_terminal_equities))
        ci_lower = float(np.percentile(sim_terminal_equities, 2.5))
        ci_upper = float(np.percentile(sim_terminal_equities, 97.5))

        # Expectância matemática histórica dos trades
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = len(wins) / len(pnls)
        loss_rate = len(losses) / len(pnls)
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

        # Critérios de Rejeição / Robustez Constitucional
        rejections: List[str] = []
        if prob_of_ruin > self.max_acceptable_ruin_probability:
            rejections.append(
                f"Probabilidade de Ruína ({prob_of_ruin:.2%}) excede o limite máximo tolerado de {self.max_acceptable_ruin_probability:.2%}"
            )
        if p99_dd > self.emergency_drawdown_limit:
            rejections.append(
                f"Drawdown no percentil 99 ({p99_dd:.2%}) viola o limite de emergência de {self.emergency_drawdown_limit:.2%}"
            )
        if expectancy <= 0.0:
            rejections.append(f"Expectativa matemática não é positiva: {expectancy:.2f}")

        is_robust = len(rejections) == 0

        logger.info(
            "Simulação Monte Carlo concluída",
            extra={
                "is_robust": is_robust,
                "prob_of_ruin": round(prob_of_ruin, 4),
                "p95_dd": round(p95_dd, 4),
                "p99_dd": round(p99_dd, 4),
                "simulations": self.num_simulations,
            },
        )

        return MonteCarloReport(
            is_robust=is_robust,
            rejection_reasons=rejections,
            num_simulations=self.num_simulations,
            num_trades_per_simulation=n_trades,
            probability_of_ruin=round(prob_of_ruin, 4),
            max_drawdown_percentile_95=round(p95_dd, 4),
            max_drawdown_percentile_99=round(p99_dd, 4),
            max_drawdown_worst_case=round(worst_dd, 4),
            var_95=round(var_95, 4),
            var_99=round(var_99, 4),
            cvar_95=round(cvar_95, 4),
            median_terminal_equity=round(median_term_eq, 2),
            mean_expectancy=round(expectancy, 2),
            confidence_interval_95={"lower": round(ci_lower, 2), "upper": round(ci_upper, 2)},
        )
