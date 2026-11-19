"""
Processo único do QUANT HERMES no Windows.

Sobe monitoramento e, no modo mt5_demo, o adapter direto do MetaTrader 5.
Não conecta na importação. Paper não exige terminal.
A API recusa qualquer bind que não seja loopback.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform_io import ShutdownController, configure_utf8_stdio  # noqa: E402


def bind_host() -> str:
    host = os.getenv("HERMES_BIND_HOST", "127.0.0.1").strip()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            f"Recusado: HERMES_BIND_HOST={host}. A API só escuta em 127.0.0.1."
        )
    return "127.0.0.1" if host == "localhost" else host


def should_require_terminal(mode: str, remote: bool) -> bool:
    if remote:
        return False
    return mode in {"mt5", "mt5_demo", "live_demo"}


def main() -> int:
    configure_utf8_stdio()
    os.chdir(ROOT)
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    from core.config import load_hermes_config
    from deploy.preflight_check import PreflightChecker
    from execution.runtime import build_trading_adapter, execution_mode, remote_gateway_enabled

    config = load_hermes_config(ROOT / "config")
    mode = execution_mode(config)
    remote = remote_gateway_enabled(config)
    stop = ShutdownController(ROOT / "data" / "storage" / "hermes.stop")
    stop.clear()
    stop.install_signal_handlers()

    report = PreflightChecker(base_dir=ROOT).run_all_checks(
        require_terminal=should_require_terminal(mode, remote)
    )
    sys.stdout.write(report.summary() + "\n")
    if not report.is_ready:
        return 1

    # Constrói o adapter. connect() só ocorre se o modo for MT5 direto, abaixo.
    adapter = build_trading_adapter(config)
    host = bind_host()
    port = int(os.getenv("HERMES_BIND_PORT", str(config.execution.bind_port)))

    import asyncio

    import uvicorn

    async def _serve() -> None:
        connected = await adapter.connect()
        if not connected and should_require_terminal(mode, remote):
            raise RuntimeError("Terminal MetaTrader 5 não conectou. Nenhuma ordem foi enviada.")
        config_uv = uvicorn.Config(
            "monitoring.asgi:app",
            host=host,
            port=port,
            log_config=None,
        )
        server = uvicorn.Server(config_uv)

        async def _watch_stop() -> None:
            while not stop.requested():
                await asyncio.sleep(0.5)
            server.should_exit = True

        await asyncio.gather(server.serve(), _watch_stop())
        disconnect = getattr(adapter, "disconnect", None)
        if disconnect is not None:
            result = disconnect()
            if asyncio.iscoroutine(result):
                await result

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
