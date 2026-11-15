"""
QUANT HERMES — SIMULADOR DE ESTRESSE MONTE CARLO COM BLOCK BOOTSTRAP
Módulo: intelligence.learning.monte_carlo

Implementa análise de robustez estocástica não-paramétrica avançada:
1. IID Bootstrap: Amostragem aleatória uniforme com reposição (benchmark clássico).
2. Moving Block Bootstrap (Künsch, 1989): Blocos contíguos sobrepostos de comprimento b.
3. Circular Block Bootstrap (Politis & Romano, 1992): Blocos circulares periódicos.
4. Stationary Bootstrap (Politis & Romano, 1994): Blocos com comprimento geometricamente
   distribuído, garantindo estritamente a estacionariedade da série reamostrada.
5. Métricas de Cauda e Sequência de Perdas: Risco de ruína (DD >= 8%), VaR/CVaR (95%/99%),
   distribuição de sequências consecutivas de perdas e assimetria/curtose.
6. Comparativo Empírico IID vs. Block Bootstrap para auditoria de caudas grossas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple
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
    cvar_99: float
    median_terminal_equity: float
    mean_expectancy: float
    confidence_interval_95: Dict[str, float]
    bootstrap_method: str
    block_size: int
    max_consecutive_losses_p95: int
    max_consecutive_losses_worst: int
    skewness: float
    kurtosis: float


@dataclass(frozen=True)
class BootstrapComparisonReport:
    """Comparativo empírico direto entre IID Bootstrap e Block Bootstrap sobre a mesma série."""
    sample_size: int
    block_size: int
    iid_probability_of_ruin: float
    block_probability_of_ruin: float
    iid_max_drawdown_p95: float
    block_max_drawdown_p95: float
    iid_cvar_95: float
    block_cvar_95: float
    iid_max_loss_streak_p95: int
    block_max_loss_streak_p95: int
    ruin_underestimation_pct: float
    drawdown_underestimation_pct: float
    verdict: str


class MonteCarloStressTester:
    """
    Motor de estresse estatístico Monte Carlo multi-método.
    Garante que nenhuma estratégia seja aprovada com base em premissas IID ingênuas
    que desconsideram agrupamento de volatilidade e dependência de cauda.
    """

    def __init__(
        self,
        num_simulations: int = 1500,
        emergency_drawdown_limit: float = 0.08,
        max_acceptable_ruin_probability: float = 0.01,
        initial_capital: float = 10000.0,
        random_state: int = 42,
        default_block_size: Optional[int] = None,
    ) -> None:
        self.num_simulations = num_simulations
        self.emergency_drawdown_limit = emergency_drawdown_limit
        self.max_acceptable_ruin_probability = max_acceptable_ruin_probability
        self.initial_capital = initial_capital
        self.random_state = random_state
        self.default_block_size = default_block_size

    def estimate_optimal_block_size(self, pnls: np.ndarray) -> int:
        """
        Calcula o comprimento de bloco teoricamente justificado com base na regra
        assintótica de Lahiri (2003) e Politis & White (2004) para bootstrap de blocos:
        b_opt = max(2, round(n^(1/3) * (1 + 2 * rho_1 / (1 - rho_1^2))^(2/3)))
        onde rho_1 é o coeficiente de autocorrelação de lag 1.
        """
        n = len(pnls)
        if n < 10:
            return 2
        
        # Autocorrelação de lag 1
        variance = np.var(pnls)
        if variance > 1e-9:
            rho_1 = float(np.corrcoef(pnls[:-1], pnls[1:])[0, 1])
            if np.isnan(rho_1):
                rho_1 = 0.0
        else:
            rho_1 = 0.0

        # Limita rho para estabilidade numérica (-0.9 a 0.9)
        rho_clamped = max(-0.9, min(0.9, rho_1))
        scale = max(0.5, (1.0 + 2.0 * abs(rho_clamped) / (1.0 - rho_clamped**2 + 1e-6)) ** (1.0 / 3.0))
        
        b = int(np.round((n ** (1.0 / 3.0)) * scale))
        return max(2, min(b, n // 3))

    def run_stress_test(
        self,
        trade_pnls: List[float],
        trades_per_sim: Optional[int] = None,
        method: Literal["circular_block", "moving_block", "stationary", "iid"] = "circular_block",
        block_size: Optional[int] = None,
    ) -> MonteCarloReport:
        """
        Executa a simulação Monte Carlo sobre a lista de lucros/prejuízos dos trades.
        """
        if len(trade_pnls) < 10:
            raise ValueError(f"Mínimo de 10 trades requerido para simulação Monte Carlo, recebido {len(trade_pnls)}")

        rng = np.random.default_rng(self.random_state)
        pnls = np.array(trade_pnls, dtype=float)
        n_original = len(pnls)
        n_trades = trades_per_sim if trades_per_sim is not None else n_original

        # Determinação do tamanho de bloco
        if method == "iid":
            b_size = 1
        elif block_size is not None:
            b_size = max(1, min(block_size, n_original // 2))
        elif self.default_block_size is not None:
            b_size = max(1, min(self.default_block_size, n_original // 2))
        else:
            b_size = self.estimate_optimal_block_size(pnls)

        sim_max_drawdowns = np.zeros(self.num_simulations)
        sim_terminal_equities = np.zeros(self.num_simulations)
        sim_max_loss_streaks = np.zeros(self.num_simulations, dtype=int)
        ruin_events = 0

        # Loop de simulações Monte Carlo
        for sim_i in range(self.num_simulations):
            if method == "circular_block" and b_size > 1:
                sampled_pnls = self._sample_circular_block(pnls, n_trades, b_size, rng)
            elif method == "moving_block" and b_size > 1:
                sampled_pnls = self._sample_moving_block(pnls, n_trades, b_size, rng)
            elif method == "stationary" and b_size > 1:
                sampled_pnls = self._sample_stationary(pnls, n_trades, b_size, rng)
            else:
                sampled_pnls = rng.choice(pnls, size=n_trades, replace=True)

            equity_curve = np.zeros(n_trades + 1)
            equity_curve[0] = self.initial_capital
            equity_curve[1:] = self.initial_capital + np.cumsum(sampled_pnls)

            # Cálculo do drawdown máximo na trajetória
            running_max = np.maximum.accumulate(equity_curve)
            drawdowns = (running_max - equity_curve) / np.maximum(running_max, 1e-9)
            max_dd = float(np.max(drawdowns))
            sim_max_drawdowns[sim_i] = max_dd
            sim_terminal_equities[sim_i] = equity_curve[-1]

            # Contagem de sequência consecutiva máxima de perdas (Loss Streak)
            sim_max_loss_streaks[sim_i] = self._calculate_max_loss_streak(sampled_pnls)

            if max_dd >= self.emergency_drawdown_limit:
                ruin_events += 1

        prob_of_ruin = ruin_events / self.num_simulations
        p95_dd = float(np.percentile(sim_max_drawdowns, 95))
        p99_dd = float(np.percentile(sim_max_drawdowns, 99))
        worst_dd = float(np.max(sim_max_drawdowns))

        # VaR e CVaR sobre o retorno percentual final em relação ao capital inicial
        terminal_returns = (sim_terminal_equities - self.initial_capital) / self.initial_capital
        var_95 = float(-np.percentile(terminal_returns, 5))
        var_99 = float(-np.percentile(terminal_returns, 1))

        tail_95 = terminal_returns[terminal_returns <= -var_95]
        cvar_95 = float(-np.mean(tail_95)) if len(tail_95) > 0 else var_95

        tail_99 = terminal_returns[terminal_returns <= -var_99]
        cvar_99 = float(-np.mean(tail_99)) if len(tail_99) > 0 else var_99

        median_equity = float(np.median(sim_terminal_equities))
        expectancy = float(np.mean(pnls))

        # Assimetria e Curtose empírica da série de PnL original
        mean_pnl = np.mean(pnls)
        std_pnl = np.std(pnls) + 1e-9
        skewness = float(np.mean(((pnls - mean_pnl) / std_pnl) ** 3))
        kurtosis = float(np.mean(((pnls - mean_pnl) / std_pnl) ** 4) - 3.0)

        # Sequências de perdas
        p95_streak = int(np.percentile(sim_max_loss_streaks, 95))
        worst_streak = int(np.max(sim_max_loss_streaks))

        # Intervalo de confiança da curva de equity
        ci_lower = float(np.percentile(sim_terminal_equities, 2.5))
        ci_upper = float(np.percentile(sim_terminal_equities, 97.5))

        # Portão Constitucional de Robustez
        rejection_reasons = []
        if prob_of_ruin > self.max_acceptable_ruin_probability:
            rejection_reasons.append(
                f"Probabilidade de Ruína ({prob_of_ruin:.2%}) excede teto aceitável ({self.max_acceptable_ruin_probability:.2%})"
            )
        if p95_dd >= self.emergency_drawdown_limit:
            rejection_reasons.append(
                f"Drawdown no percentil 95% ({p95_dd:.2%}) viola limite de emergência ({self.emergency_drawdown_limit:.2%})"
            )
        if expectancy <= 0:
            rejection_reasons.append(f"Expectativa matemática de trade não-positiva: ${expectancy:.2f}")

        is_robust = len(rejection_reasons) == 0

        logger.info(
            "Simulação Monte Carlo concluída",
            extra={
                "method": method,
                "block_size": b_size,
                "prob_of_ruin": f"{prob_of_ruin:.2%}",
                "p95_dd": f"{p95_dd:.2%}",
                "p95_loss_streak": p95_streak,
                "is_robust": is_robust,
            },
        )

        return MonteCarloReport(
            is_robust=is_robust,
            rejection_reasons=rejection_reasons,
            num_simulations=self.num_simulations,
            num_trades_per_simulation=n_trades,
            probability_of_ruin=prob_of_ruin,
            max_drawdown_percentile_95=p95_dd,
            max_drawdown_percentile_99=p99_dd,
            max_drawdown_worst_case=worst_dd,
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            cvar_99=cvar_99,
            median_terminal_equity=median_equity,
            mean_expectancy=expectancy,
            confidence_interval_95={"lower": ci_lower, "upper": ci_upper},
            bootstrap_method=method,
            block_size=b_size,
            max_consecutive_losses_p95=p95_streak,
            max_consecutive_losses_worst=worst_streak,
            skewness=skewness,
            kurtosis=kurtosis,
        )

    def compare_iid_vs_block(
        self,
        trade_pnls: List[float],
        block_size: Optional[int] = None,
    ) -> BootstrapComparisonReport:
        """
        Executa auditoria comparativa direta entre IID e Block Bootstrap sobre a mesma série.
        Evidencia empiricamente o grau de subestimação do risco provocado pela premissa IID.
        """
        rep_iid = self.run_stress_test(trade_pnls, method="iid")
        rep_block = self.run_stress_test(trade_pnls, method="circular_block", block_size=block_size)

        dd_diff_pct = (
            ((rep_block.max_drawdown_percentile_95 - rep_iid.max_drawdown_percentile_95) / rep_iid.max_drawdown_percentile_95) * 100.0
            if rep_iid.max_drawdown_percentile_95 > 0 else 0.0
        )
        ruin_diff_pct = (
            ((rep_block.probability_of_ruin - rep_iid.probability_of_ruin) / (rep_iid.probability_of_ruin + 1e-6)) * 100.0
        )

        if rep_block.max_drawdown_percentile_95 > rep_iid.max_drawdown_percentile_95:
            verdict = "IID_UNDERESTIMATES_TAIL_RISK"
        elif rep_block.max_drawdown_percentile_95 < rep_iid.max_drawdown_percentile_95:
            verdict = "IID_OVERESTIMATES_TAIL_RISK"
        else:
            verdict = "IDENTICAL_TAIL_RISK"

        return BootstrapComparisonReport(
            sample_size=len(trade_pnls),
            block_size=rep_block.block_size,
            iid_probability_of_ruin=rep_iid.probability_of_ruin,
            block_probability_of_ruin=rep_block.probability_of_ruin,
            iid_max_drawdown_p95=rep_iid.max_drawdown_percentile_95,
            block_max_drawdown_p95=rep_block.max_drawdown_percentile_95,
            iid_cvar_95=rep_iid.cvar_95,
            block_cvar_95=rep_block.cvar_95,
            iid_max_loss_streak_p95=rep_iid.max_consecutive_losses_p95,
            block_max_loss_streak_p95=rep_block.max_consecutive_losses_p95,
            ruin_underestimation_pct=round(ruin_diff_pct, 2),
            drawdown_underestimation_pct=round(dd_diff_pct, 2),
            verdict=verdict,
        )

    @staticmethod
    def _calculate_max_loss_streak(pnls: np.ndarray) -> int:
        """Calcula o maior número de trades perdedores consecutivos em uma trajetória."""
        max_streak = 0
        current_streak = 0
        for p in pnls:
            if p < 0:
                current_streak += 1
                if current_streak > max_streak:
                    max_streak = current_streak
            else:
                current_streak = 0
        return max_streak

    @staticmethod
    def _sample_circular_block(
        data: np.ndarray,
        target_size: int,
        block_size: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """Circular Block Bootstrap (Politis & Romano, 1992)."""
        n = len(data)
        num_blocks = int(np.ceil(target_size / block_size))
        start_indices = rng.integers(0, n, size=num_blocks)
        
        sampled_blocks = []
        for start_idx in start_indices:
            block_indices = (start_idx + np.arange(block_size)) % n
            sampled_blocks.append(data[block_indices])
            
        full_sample = np.concatenate(sampled_blocks)
        return full_sample[:target_size]

    @staticmethod
    def _sample_moving_block(
        data: np.ndarray,
        target_size: int,
        block_size: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """Moving Block Bootstrap (Künsch, 1989): Blocos sobrepostos sem wrap-around."""
        n = len(data)
        max_start = max(1, n - block_size + 1)
        num_blocks = int(np.ceil(target_size / block_size))
        start_indices = rng.integers(0, max_start, size=num_blocks)

        sampled_blocks = []
        for start_idx in start_indices:
            sampled_blocks.append(data[start_idx : start_idx + block_size])

        full_sample = np.concatenate(sampled_blocks)
        return full_sample[:target_size]

    @staticmethod
    def _sample_stationary(
        data: np.ndarray,
        target_size: int,
        mean_block_size: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """
        Stationary Bootstrap (Politis & Romano, 1994):
        O comprimento de cada bloco segue uma distribuição geométrica com probabilidade p = 1/b.
        Garante rigorosamente a estacionariedade da série gerada.
        """
        n = len(data)
        p = 1.0 / mean_block_size
        sampled = []
        
        current_idx = rng.integers(0, n)
        while len(sampled) < target_size:
            sampled.append(data[current_idx])
            # Com probabilidade p, sorteia um novo ponto de partida aleatório
            if rng.random() < p:
                current_idx = rng.integers(0, n)
            else:
                current_idx = (current_idx + 1) % n

        return np.array(sampled[:target_size], dtype=float)
