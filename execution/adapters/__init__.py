"""
QUANT HERMES — Adaptadores de Execução
Módulo: execution.adapters
"""
from execution.adapters.base import PlatformConnectionError, TradingPlatformAdapter
from execution.adapters.paper import PaperTradingAdapter
from execution.adapters.windows_mt5 import WindowsMT5Adapter

__all__ = [
    "TradingPlatformAdapter",
    "PlatformConnectionError",
    "PaperTradingAdapter",
    "WindowsMT5Adapter",
]
