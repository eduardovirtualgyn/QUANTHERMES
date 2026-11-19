"""
QUANT HERMES — Preenchimento intrabar conservador
Módulo: strategies.backtest.fills

Barras MT5 são cotadas no bid.
- Compra entra no ask (bid + spread) e ainda paga slippage.
- Venda entra no bid e perde slippage.
- Gap que atravessa o stop preenche no open (pior que o stop).
- Se stop e alvo cabem na mesma barra, o stop acontece primeiro.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.models.market import MarketBar


@dataclass(frozen=True)
class Fill:
    price: float
    reason: str


def entry_price(direction: str, reference: float, spread_price: float, slippage_price: float) -> float:
    """Preço de entrada já com spread e slippage adversos."""
    if direction == "BUY":
        return reference + spread_price + slippage_price
    return reference - slippage_price


def exit_fill(
    direction: str,
    bar: MarketBar,
    stop_loss: float,
    take_profit: float,
    spread_price: float,
    slippage_price: float,
) -> Optional[Fill]:
    """
    Retorna o preenchimento de saída nesta barra, ou None se a posição segue aberta.
    """
    if direction == "BUY":
        stop_hit = bar.low <= stop_loss
        target_hit = take_profit > 0.0 and bar.high >= take_profit
        if stop_hit:
            if bar.open <= stop_loss:
                price = bar.open - slippage_price
            else:
                price = stop_loss - slippage_price
            return Fill(price=price, reason="STOP_LOSS")
        if target_hit:
            # Alvo no bid. Gap favorável não é capturado: preenche no alvo, menos slippage.
            return Fill(price=take_profit - slippage_price, reason="TAKE_PROFIT")
        return None

    stop_hit = bar.high >= stop_loss
    target_hit = take_profit > 0.0 and bar.low <= take_profit
    if stop_hit:
        # Recompra no ask. Gap contra a posição preenche no open + spread.
        if bar.open >= stop_loss:
            price = bar.open + spread_price + slippage_price
        else:
            price = stop_loss + spread_price + slippage_price
        return Fill(price=price, reason="STOP_LOSS")
    if target_hit:
        return Fill(price=take_profit + spread_price + slippage_price, reason="TAKE_PROFIT")
    return None
