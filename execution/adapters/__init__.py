"""
QUANT HERMES — Adaptadores de Execução
Módulo: execution.adapters
"""
from execution.adapters.base import PlatformConnectionError, TradingPlatformAdapter
from execution.adapters.linux_bridge import LinuxMT5BridgeAdapter
from execution.adapters.paper import PaperTradingAdapter

# WindowsMT5Adapter não é importado aqui: o pacote MetaTrader5 é exclusivo do
# Windows. O cérebro Linux importa paper/remote/linux_bridge sem tocar nessa DLL.
__all__ = [
    "TradingPlatformAdapter",
    "PlatformConnectionError",
    "PaperTradingAdapter",
    "LinuxMT5BridgeAdapter",
]

