"""
QUANT HERMES — Escolha do adapter de execução
Módulo: execution.runtime

No Windows, o processo único fala com o MetaTrader 5 direto.
O gateway remoto só entra se HERMES_REMOTE_GATEWAY=1 (desligado por padrão).
Fora do Windows, ou em modo paper, usa o adapter em memória. Não conecta aqui.
"""
from __future__ import annotations

import os
import sys

from core.config import HermesConfig
from execution.adapters.paper import PaperTradingAdapter
from execution.adapters.base import TradingPlatformAdapter

_PAPER_MODES = {"paper", "backtest", "development", "paper_trading"}
_DIRECT_MT5_MODES = {"mt5", "mt5_demo", "live_demo"}


def _enabled(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def remote_gateway_enabled(config: HermesConfig) -> bool:
    return _enabled(os.getenv("HERMES_REMOTE_GATEWAY"), config.execution.remote_gateway_enabled)


def execution_mode(config: HermesConfig) -> str:
    return os.getenv("HERMES_EXECUTION_MODE", config.execution.mode).strip().lower()


def build_trading_adapter(config: HermesConfig) -> TradingPlatformAdapter:
    """
    Monta o adapter sem abrir socket de corretora.
    A conexão acontece depois, em adapter.connect(), quando o operador sobe o processo.
    """
    if remote_gateway_enabled(config):
        from core.secrets import require_env
        from execution.adapters.remote_gateway import RemoteMT5GatewayAdapter

        return RemoteMT5GatewayAdapter(
            gateway_url=os.getenv("HERMES_GATEWAY_URL", "http://127.0.0.1:8001"),
            api_token=require_env("HERMES_GATEWAY_TOKEN"),
        )

    mode = execution_mode(config)
    if mode in _PAPER_MODES or mode not in _DIRECT_MT5_MODES:
        return PaperTradingAdapter(currency=config.broker.account_currency or "USC")

    if sys.platform != "win32":
        raise RuntimeError(
            "O modo MT5 direto só roda no Windows, no mesmo usuário e na mesma máquina do terminal RoboForex. "
            "O gateway remoto está desligado. Para testes sem terminal use HERMES_EXECUTION_MODE=paper."
        )

    from execution.adapters.windows_mt5 import WindowsMT5Adapter

    login_raw = os.getenv("MT5_LOGIN", "").strip()
    login = int(login_raw) if login_raw.isdigit() and int(login_raw) > 0 else None
    return WindowsMT5Adapter(
        path=os.getenv("MT5_PATH") or None,
        login=login,
        password=os.getenv("MT5_PASSWORD") or None,
        server=os.getenv("MT5_SERVER") or None,
        symbol_suffix=config.broker.symbol_suffix,
        symbol_aliases=dict(config.broker.symbol_aliases),
        max_retry_attempts=config.execution.max_retry_attempts,
        retry_delay_seconds=config.execution.retry_delay_seconds,
    )
