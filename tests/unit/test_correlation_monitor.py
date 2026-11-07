"""
QUANT HERMES — Testes do Monitor de Correlação
Arquivo: tests/unit/test_correlation_monitor.py
"""
import pytest
from datetime import datetime, timezone
from portfolio.correlation import CorrelationMonitor
from core.models.risk import Position


@pytest.fixture
def monitor():
    return CorrelationMonitor(max_correlation_threshold=0.70, max_correlated_pairs_open=2)


def make_pos(ticket: int, symbol: str, pos_type: str) -> Position:
    return Position(
        ticket=ticket,
        symbol=symbol,
        magic=1001,
        position_type=pos_type,
        volume=0.1,
        open_price=1.0,
        stop_loss=0.9,
        current_price=1.0,
        open_time=datetime.now(timezone.utc),
    )


class TestCorrelationMonitor:
    """Testes de integridade do monitor de correlação."""

    def test_correlation_symmetry_and_defaults(self, monitor):
        assert monitor.get_correlation("EURUSD", "GBPUSD") == 0.82
        assert monitor.get_correlation("GBPUSD", "EURUSD") == 0.82
        assert monitor.get_correlation("EURUSD", "EURUSD") == 1.0
        assert monitor.get_correlation("UNKNOWN_A", "UNKNOWN_B") == 0.0

    def test_dynamic_correlation_update_and_clamping(self, monitor):
        monitor.update_correlation("EURUSD", "USDJPY", -0.55)
        assert monitor.get_correlation("EURUSD", "USDJPY") == -0.55

        # Garante clamping em [-1.0, 1.0]
        monitor.update_correlation("AAA", "BBB", 1.50)
        assert monitor.get_correlation("AAA", "BBB") == 1.0

    def test_passes_when_no_open_positions(self, monitor):
        ok, reason = monitor.check_correlation_limit("EURUSD", "BUY", [])
        assert ok is True
        assert reason is None

    def test_passes_with_one_correlated_pair(self, monitor):
        # 1 posição aberta em EURUSD BUY (Short USD)
        open_pos = [make_pos(1, "EURUSD", "BUY")]
        # Proposta de GBPUSD BUY (Short USD, correlação 0.82)
        # 1 < max 2 -> Aprovado
        ok, reason = monitor.check_correlation_limit("GBPUSD", "BUY", open_pos)
        assert ok is True
        assert reason is None

    def test_blocks_when_correlated_pairs_limit_reached(self, monitor):
        # Já existem 2 posições com exposição Short USD (EURUSD BUY e XAUUSD BUY)
        open_pos = [
            make_pos(1, "EURUSD", "BUY"),
            make_pos(2, "XAUUSD", "BUY"),
        ]
        # Tentativa de abrir 3ª posição na mesma direção em GBPUSD BUY
        ok, reason = monitor.check_correlation_limit("GBPUSD", "BUY", open_pos)
        assert ok is False
        assert "CORRELATION_LIMIT_EXCEEDED" in reason
        assert "GBPUSD" in reason

