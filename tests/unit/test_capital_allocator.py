"""
QUANT HERMES — Testes do Alocador de Capital
Arquivo: tests/unit/test_capital_allocator.py
"""
import pytest
from portfolio.allocator import CapitalAllocator


@pytest.fixture
def allocator():
    return CapitalAllocator(
        default_risk_per_trade_pct=0.25,
        max_risk_per_trade_pct=0.50,
        max_portfolio_risk_pct=1.00,
    )


class TestCapitalAllocator:
    """Testes de alocação de risco e limites de portfólio."""

    def test_nominal_allocation(self, allocator):
        allocated = allocator.allocate_risk(
            strategy_id="STRAT_TREND_EURUSD",
            requested_risk_pct=0.25,
            current_family_open_risk_pct=0.0,
            total_open_risk_pct=0.0,
        )
        assert allocated == 0.25

    def test_clamp_to_max_trade_cap(self, allocator):
        # Solicita 0.80% (acima do cap de 0.50%)
        allocated = allocator.allocate_risk(
            strategy_id="STRAT_TREND_EURUSD",
            requested_risk_pct=0.80,
            current_family_open_risk_pct=0.0,
            total_open_risk_pct=0.0,
        )
        assert allocated == 0.50

    def test_clamp_to_remaining_family_budget(self, allocator):
        # Orçamento da família Trend é 0.50%. Já há 0.35% aberto.
        # Restam apenas 0.15%.
        allocated = allocator.allocate_risk(
            strategy_id="STRAT_TREND_EURUSD",
            requested_risk_pct=0.25,
            current_family_open_risk_pct=0.35,
            total_open_risk_pct=0.35,
        )
        assert allocated == 0.15

    def test_clamp_to_remaining_portfolio_budget(self, allocator):
        # Total aberto no portfólio já é 0.88%. Restam 0.12% de 1.00%.
        allocated = allocator.allocate_risk(
            strategy_id="STRAT_BREAKOUT_XAUUSD",
            requested_risk_pct=0.25,
            current_family_open_risk_pct=0.0,
            total_open_risk_pct=0.88,
        )
        assert allocated == 0.12

    def test_zero_allocation_when_portfolio_exhausted(self, allocator):
        allocated = allocator.allocate_risk(
            strategy_id="STRAT_MOMENTUM_GBPUSD",
            requested_risk_pct=0.25,
            current_family_open_risk_pct=0.0,
            total_open_risk_pct=1.00,
        )
        assert allocated == 0.0

    def test_inviolable_floor_protections(self):
        with pytest.raises(ValueError, match="0.50%"):
            CapitalAllocator(max_risk_per_trade_pct=0.60)

        with pytest.raises(ValueError, match="1.00%"):
            CapitalAllocator(max_portfolio_risk_pct=1.50)
