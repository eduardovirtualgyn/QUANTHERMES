"""
QUANT HERMES — Alocador Dinâmico de Capital e Orçamento de Risco
Módulo: portfolio.allocator
"""
from __future__ import annotations

from typing import Dict, Optional
from core.logger import get_logger

logger = get_logger("portfolio.allocator")

# Orçamento máximo de risco padrão por família de estratégia (percentual da equity)
_DEFAULT_FAMILY_BUDGETS: Dict[str, float] = {
    "trend": 0.50,
    "breakout": 0.50,
    "momentum": 0.50,
    "mean_reversion": 0.35,
    "smc": 0.35,
    "scalping": 0.25,
    "swing": 0.50,
}


class CapitalAllocator:
    """
    Alocador prudencial de capital por estratégia e família operacional.
    Garante:
    1. Respeito ao teto de risco por operação (padrão 0.25%, teto inviolável 0.50%).
    2. Respeito ao orçamento de risco por família de estratégia (ex: máx 0.50% em Trend).
    3. Respeito ao teto agregado de 1.00% da conta em risco simultâneo.
    """

    def __init__(
        self,
        default_risk_per_trade_pct: float = 0.25,
        max_risk_per_trade_pct: float = 0.50,
        max_portfolio_risk_pct: float = 1.00,
        family_budgets: Optional[Dict[str, float]] = None,
    ):
        if max_risk_per_trade_pct > 0.50:
            raise ValueError("max_risk_per_trade_pct não pode exceder 0.50%")
        if max_portfolio_risk_pct > 1.00:
            raise ValueError("max_portfolio_risk_pct não pode exceder 1.00%")

        self.default_risk_per_trade_pct = default_risk_per_trade_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_portfolio_risk_pct = max_portfolio_risk_pct
        self.family_budgets = family_budgets or _DEFAULT_FAMILY_BUDGETS.copy()

    def get_strategy_family(self, strategy_id: str) -> str:
        """Determina a família da estratégia a partir do seu identificador."""
        strat_lower = strategy_id.lower()
        for family in self.family_budgets:
            if family in strat_lower:
                return family
        return "trend"  # Família padrão de menor risco relativo

    def allocate_risk(
        self,
        strategy_id: str,
        requested_risk_pct: float,
        current_family_open_risk_pct: float,
        total_open_risk_pct: float,
    ) -> float:
        """
        Determina o percentual de risco autorizado para a proposta.
        Retorna 0.0 caso não haja orçamento disponível na família ou no portfólio.
        """
        family = self.get_strategy_family(strategy_id)
        family_budget = self.family_budgets.get(family, 0.50)

        # Orçamento restante na família
        family_remaining = max(0.0, family_budget - current_family_open_risk_pct)
        if family_remaining <= 0.01:
            logger.warning(
                "risk_allocation_rejected_family_budget_exhausted",
                strategy=strategy_id,
                family=family,
                family_open_risk=current_family_open_risk_pct,
                budget=family_budget,
            )
            return 0.0

        # Orçamento restante no portfólio global
        portfolio_remaining = max(0.0, self.max_portfolio_risk_pct - total_open_risk_pct)
        if portfolio_remaining <= 0.01:
            logger.warning(
                "risk_allocation_rejected_portfolio_budget_exhausted",
                strategy=strategy_id,
                total_open_risk=total_open_risk_pct,
                max_budget=self.max_portfolio_risk_pct,
            )
            return 0.0

        # Alocação é o mínimo entre pedido, limite por trade, orçamento familiar e global
        allocated = min(
            requested_risk_pct,
            self.max_risk_per_trade_pct,
            family_remaining,
            portfolio_remaining,
        )

        allocated = round(allocated, 4)
        if allocated < 0.05:  # Piso mínimo razoável de alocação (0.05%)
            return 0.0

        return allocated

