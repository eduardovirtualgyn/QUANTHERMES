"""
QUANT HERMES — Testes do Dimensionador Matemático de Lotes (Position Sizer)
Arquivo: tests/risk/test_position_sizer.py
"""
import pytest
from core.models.market import SymbolSpecification
from risk.position_sizer import PositionSizer


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
def xauusd_spec():
    return SymbolSpecification(
        symbol="XAUUSD",
        canonical_name="XAUUSD",
        category="metal",
        base_currency="XAU",
        quote_currency="USD",
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        contract_size=100.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )


class TestPositionSizer:
    """Suíte de testes de precisão e segurança do PositionSizer."""

    def test_eurusd_standard_sizing(self, eurusd_spec):
        """
        Risco: $250.0
        Entrada: 1.08500, Stop Loss: 1.08200 (distância = 300 pontos = 0.00300)
        Tick size: 0.00001, Tick value: 1.0
        Perda por lote = (0.00300 / 0.00001) * 1.0 = $300.0
        Lote bruto = 250 / 300 = 0.833333...
        Lote normalizado (floor 0.01) = 0.83
        """
        lot = PositionSizer.calculate_lot(
            risk_money=250.0,
            entry_price=1.08500,
            stop_loss_price=1.08200,
            spec=eurusd_spec,
        )
        assert lot == 0.83

    def test_floor_rounding_never_rounds_up(self, eurusd_spec):
        """
        Garante que 0.1299999 nunca seja arredondado para 0.13.
        O arredondamento deve ser estritamente para baixo (Floor) para proteger o risco.
        """
        raw_lot = 0.129999
        lot = PositionSizer.normalize_lot(
            raw_lot=raw_lot,
            vol_min=eurusd_spec.volume_min,
            vol_max=eurusd_spec.volume_max,
            vol_step=eurusd_spec.volume_step,
        )
        assert lot == 0.12

    def test_lot_below_min_returns_zero(self, eurusd_spec):
        """
        Se o capital em risco for tão baixo que resulte em lote inferior ao mínimo (0.01),
        o sistema deve retornar 0.0 (Fail-Safe), proibindo a abertura com risco desproporcional.
        """
        # Risco de apenas $2 para 300 pontos de SL -> lote seria ~0.0066 < 0.01
        lot = PositionSizer.calculate_lot(
            risk_money=2.0,
            entry_price=1.08500,
            stop_loss_price=1.08200,
            spec=eurusd_spec,
        )
        assert lot == 0.0

    def test_lot_exceeding_max_is_clamped(self, eurusd_spec):
        """
        Se o lote bruto calculado exceder volume_max, ele é limitado ao volume_max.
        """
        lot = PositionSizer.normalize_lot(
            raw_lot=150.0,
            vol_min=eurusd_spec.volume_min,
            vol_max=eurusd_spec.volume_max,
            vol_step=eurusd_spec.volume_step,
        )
        assert lot == 100.0

    def test_xauusd_gold_sizing(self, xauusd_spec):
        """
        Risco: $500.0
        Entrada: 2650.00, Stop Loss: 2645.00 ($5.00 de distância = 500 ticks)
        Tick size: 0.01, Tick value: $1.00
        Perda por lote = (5.00 / 0.01) * 1.0 = $500.0
        Lote bruto = 500 / 500 = 1.00 lote
        """
        lot = PositionSizer.calculate_lot(
            risk_money=500.0,
            entry_price=2650.00,
            stop_loss_price=2645.00,
            spec=xauusd_spec,
        )
        assert lot == 1.00

    def test_commission_factored_in_sizing(self, eurusd_spec):
        """
        Com comissão de $7 por lote, a perda por lote aumenta, reduzindo o tamanho do lote.
        """
        lot_without_comm = PositionSizer.calculate_lot(
            risk_money=250.0,
            entry_price=1.08500,
            stop_loss_price=1.08200,
            spec=eurusd_spec,
            commission_per_lot=0.0,
        )
        lot_with_comm = PositionSizer.calculate_lot(
            risk_money=250.0,
            entry_price=1.08500,
            stop_loss_price=1.08200,
            spec=eurusd_spec,
            commission_per_lot=7.0,
        )
        assert lot_without_comm == 0.83
        assert lot_with_comm == 0.81  # 250 / 307 = 0.8143 -> 0.81

    def test_invalid_parameters_return_zero(self, eurusd_spec):
        """Preços idênticos (distância zero) ou risco zero devem retornar 0.0."""
        assert PositionSizer.calculate_lot(0.0, 1.085, 1.082, eurusd_spec) == 0.0
        assert PositionSizer.calculate_lot(-50.0, 1.085, 1.082, eurusd_spec) == 0.0
        assert PositionSizer.calculate_lot(100.0, 1.085, 1.085, eurusd_spec) == 0.0
