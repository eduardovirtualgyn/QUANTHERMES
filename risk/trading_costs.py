"""
QUANT HERMES — Custos de execução para backtest e risco
Módulo: risk.trading_costs

Spreads padrão são médias públicas aproximadas da RoboForex ProCent
(conta de spread, sem comissão): ouro ~0.18 USD, majors ~1.3–1.9 pips.
Não são uma cotação ao vivo e podem ser substituídos por configuração
por símbolo. Swap segue symbol_info (swap_long/swap_short e o dia de
swap triplo).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict

from core.models.market import SymbolSpecification

# Preço (não pontos). 1 pip em majors de 5 dígitos = 0.0001; USDJPY = 0.01; ouro em USD.
ROBOFOREX_PROCENT_SPREAD_PRICE: Dict[str, float] = {
    "EURUSD": 1.3 * 0.0001,
    "GBPUSD": 1.7 * 0.0001,
    "USDJPY": 1.4 * 0.01,
    "AUDUSD": 1.5 * 0.0001,
    "USDCAD": 1.8 * 0.0001,
    "USDCHF": 1.6 * 0.0001,
    "NZDUSD": 1.9 * 0.0001,
    "XAUUSD": 0.18,
}

# Slippage padrão em preço: fração pequena do spread típico.
ROBOFOREX_PROCENT_SLIPPAGE_PRICE: Dict[str, float] = {
    "EURUSD": 0.2 * 0.0001,
    "GBPUSD": 0.3 * 0.0001,
    "USDJPY": 0.2 * 0.01,
    "AUDUSD": 0.3 * 0.0001,
    "USDCAD": 0.3 * 0.0001,
    "USDCHF": 0.3 * 0.0001,
    "NZDUSD": 0.3 * 0.0001,
    "XAUUSD": 0.02,
}

# Swap em pontos do símbolo, por lote, por noite. Negativo é custo.
# Valores de simulação configuráveis, na ordem de grandeza publicada por
# contas ProCent; o terminal (symbol_info) prevalece quando vier preenchido.
ROBOFOREX_PROCENT_SWAP_POINTS: Dict[str, tuple[float, float]] = {
    "EURUSD": (-6.4, -3.2),
    "GBPUSD": (-5.1, -2.4),
    "USDJPY": (-4.8, -7.5),
    "AUDUSD": (-3.6, -1.8),
    "USDCAD": (-4.2, -2.6),
    "USDCHF": (-5.5, -1.2),
    "NZDUSD": (-2.9, -1.5),
    "XAUUSD": (-18.0, -12.0),
}


def default_spread_price(symbol: str) -> float:
    return ROBOFOREX_PROCENT_SPREAD_PRICE.get(symbol.upper(), 1.5 * 0.0001)


def default_slippage_price(symbol: str) -> float:
    return ROBOFOREX_PROCENT_SLIPPAGE_PRICE.get(symbol.upper(), 0.2 * 0.0001)


def mt5_weekday(day: date) -> int:
    """Dia MT5: 0=domingo … 3=quarta. datetime.weekday(): 0=segunda … 6=domingo."""
    return (day.weekday() + 1) % 7


def swap_money_per_lot(
    spec: SymbolSpecification,
    direction: str,
    when: datetime,
    price: float,
    use_catalog: bool = False,
) -> float:
    """
    Custo (negativo) ou crédito de uma noite de swap, por 1.0 lote,
    na moeda da conta. Quarta-feira (ou swap_rollover3days) cobra triplo.
    O catálogo ProCent só entra quando use_catalog=True e o spec não traz swap.
    """
    logical = (spec.canonical_name or spec.symbol).upper()
    long_rate = spec.swap_long
    short_rate = spec.swap_short
    if use_catalog and long_rate == 0.0 and short_rate == 0.0:
        catalog = ROBOFOREX_PROCENT_SWAP_POINTS.get(logical)
        if catalog is not None:
            long_rate, short_rate = catalog
    rate = long_rate if direction == "BUY" else short_rate
    multiplier = 3.0 if mt5_weekday(when.date()) == int(spec.swap_rollover3days) else 1.0
    mode = spec.swap_mode
    if mode == "account_currency":
        return rate * multiplier
    if mode == "interest":
        return (rate / 100.0) / 360.0 * spec.contract_size * price * multiplier
    # points
    if spec.tick_size <= 0.0:
        return 0.0
    return rate * (spec.point / spec.tick_size) * spec.tick_value * multiplier


def adverse_swap_money_per_lot(spec: SymbolSpecification, direction: str, price: float) -> float:
    """Uma noite adversa (só o custo) para o dimensionamento. Crédito não aumenta o lote."""
    from datetime import timezone

    # Segunda-feira: o dimensionamento não assume swap triplo. O backtest cobra o dia real.
    sample = datetime(2026, 1, 5, tzinfo=timezone.utc)
    money = swap_money_per_lot(spec, direction, sample, price, use_catalog=False)
    return abs(money) if money < 0.0 else 0.0
