"""
QUANT HERMES — PnL realizado e flutuante para circuit breakers
Módulo: execution.account_pnl

O percentual usa o saldo (moeda da conta, inclusive USC) como base.
O PnL flutuante de posições abertas entra no dia e na semana: contar a
perda aberta é conservador para o circuit breaker.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


def _money(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_rows(rows: Optional[Iterable[Any]]) -> list:
    if rows is None or isinstance(rows, (str, bytes)):
        return []
    if not isinstance(rows, (list, tuple)):
        return []
    return list(rows)


def realized_from_deals(deals: Optional[Iterable[Any]]) -> float:
    """Soma profit + swap + commission + fee dos deals fechados."""
    total = 0.0
    for deal in _as_rows(deals):
        total += _money(getattr(deal, "profit", 0.0))
        total += _money(getattr(deal, "swap", 0.0))
        total += _money(getattr(deal, "commission", 0.0))
        total += _money(getattr(deal, "fee", 0.0))
    return total


def unrealized_from_positions(positions: Optional[Iterable[Any]]) -> float:
    """Soma profit + swap das posições ainda abertas."""
    total = 0.0
    for position in _as_rows(positions):
        total += _money(getattr(position, "profit", 0.0))
        total += _money(getattr(position, "swap", 0.0))
    return total


def pnl_percent(balance: float, realized: float, unrealized: float) -> float:
    """Percentual (realizado + flutuante) sobre o saldo. 0 se o saldo não for positivo."""
    if balance <= 0.0:
        return 0.0
    return round(((realized + unrealized) / balance) * 100.0, 4)
