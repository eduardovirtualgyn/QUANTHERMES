"""
QUANT HERMES — Mapeamento de símbolos lógicos para símbolos da corretora
Módulo: execution.symbols

Contas RoboForex ProCent (e outras) publicam o mesmo instrumento com sufixo
(EURUSD, EURUSDm, EURUSD.m, XAUUSD.). Todo o sistema conversa em símbolo
lógico (EURUSD, XAUUSD) e só o adaptador fala o nome do terminal.
"""
from __future__ import annotations

from typing import Dict, Optional


class SymbolMapper:
    """Traduz símbolo lógico ↔ símbolo do broker."""

    def __init__(
        self,
        suffix: str = "",
        aliases: Optional[Dict[str, str]] = None,
    ) -> None:
        self.suffix = suffix or ""
        self.aliases: Dict[str, str] = {}
        self._reverse: Dict[str, str] = {}
        for logical, broker in (aliases or {}).items():
            logical_key = logical.upper()
            broker_name = str(broker)
            self.aliases[logical_key] = broker_name
            self._reverse[broker_name.upper()] = logical_key

    def to_broker(self, logical_symbol: str) -> str:
        """Nome enviado ao terminal MT5."""
        key = logical_symbol.upper()
        if key in self.aliases:
            return self.aliases[key]
        if self.suffix and not key.endswith(self.suffix.upper()):
            return f"{logical_symbol}{self.suffix}"
        return logical_symbol

    def to_logical(self, broker_symbol: str) -> str:
        """Nome canônico interno a partir do nome publicado pelo broker."""
        raw = broker_symbol.upper()
        if raw in self._reverse:
            return self._reverse[raw]
        suffix = self.suffix.upper()
        if suffix and raw.endswith(suffix) and len(raw) > len(suffix):
            return raw[: -len(suffix)]
        return raw

    def same_instrument(self, left: str, right: str) -> bool:
        """Verdadeiro quando os dois nomes apontam para o mesmo instrumento."""
        return self.to_logical(left) == self.to_logical(right)
