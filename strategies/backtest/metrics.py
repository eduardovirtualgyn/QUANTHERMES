"""
QUANT HERMES — Métricas de backtest honestas
Módulo: strategies.backtest.metrics

O Sharpe usa o retorno por barra e a frequência real do timeframe,
não a raiz de 252 aplicada a retornos por trade.
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

BARS_PER_YEAR = {
    "M1": 252 * 24 * 60,
    "M5": 252 * 24 * 12,
    "M15": 252 * 24 * 4,
    "H1": 252 * 24,
    "H4": 252 * 6,
    "D1": 252,
}


def bars_per_year(timeframe: str) -> int:
    return int(BARS_PER_YEAR.get(timeframe, 252 * 24 * 4))


def sharpe_from_equity(equity_curve: Sequence[float], timeframe: str) -> float:
    """Sharpe anualizado a partir da curva de equity por barra (ddof=1)."""
    equity = np.asarray(equity_curve, dtype=float)
    if equity.size < 3:
        return 0.0
    previous = equity[:-1]
    valid = previous > 0
    returns = np.zeros(equity.size - 1, dtype=float)
    returns[valid] = (equity[1:][valid] - previous[valid]) / previous[valid]
    returns = returns[np.isfinite(returns)]
    if returns.size < 3:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std <= 0.0:
        return 0.0
    periods = bars_per_year(timeframe)
    return float((np.mean(returns) / std) * np.sqrt(periods))


def r_expectancy_stats(r_multiples: Iterable[float]) -> dict[str, float]:
    """Expectância em R, t-stat e intervalo de confiança normal de 95%."""
    values = np.asarray(list(r_multiples), dtype=float)
    values = values[np.isfinite(values)]
    n = int(values.size)
    if n == 0:
        return {
            "expectancy_r": 0.0,
            "t_stat": 0.0,
            "ci95_low_r": 0.0,
            "ci95_high_r": 0.0,
            "n": 0,
        }
    mean = float(np.mean(values))
    if n < 2:
        return {
            "expectancy_r": mean,
            "t_stat": 0.0,
            "ci95_low_r": mean,
            "ci95_high_r": mean,
            "n": n,
        }
    std = float(np.std(values, ddof=1))
    if std <= 0.0:
        return {
            "expectancy_r": mean,
            "t_stat": 0.0,
            "ci95_low_r": mean,
            "ci95_high_r": mean,
            "n": n,
        }
    se = std / np.sqrt(n)
    t_stat = mean / se
    return {
        "expectancy_r": mean,
        "t_stat": float(t_stat),
        "ci95_low_r": float(mean - 1.96 * se),
        "ci95_high_r": float(mean + 1.96 * se),
        "n": n,
    }
