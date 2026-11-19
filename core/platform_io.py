"""
QUANT HERMES — I/O portátil (Windows e testes offline)
Módulo: core.platform_io

Sem fcntl, sem uvloop e sem sinais exclusivos de POSIX.
O console fica em UTF-8. O desligamento gracioso escuta Ctrl+C,
SIGTERM/SIGBREAK quando existem, e um arquivo de parada.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path


def configure_utf8_stdio() -> None:
    """Força UTF-8 no processo e nos streams, inclusive no console do Windows."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


class ShutdownController:
    """Pedido de parada compartilhado entre console, serviço e arquivo."""

    def __init__(self, stop_file: Path) -> None:
        self.stop_file = Path(stop_file)
        self._event = threading.Event()

    def install_signal_handlers(self) -> None:
        def _handle(signum: int, frame: object) -> None:
            del signum, frame
            self.request()

        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, _handle)
            except (ValueError, OSError):
                continue

    def request(self) -> None:
        self._event.set()
        try:
            self.stop_file.parent.mkdir(parents=True, exist_ok=True)
            self.stop_file.write_text("stop\n", encoding="utf-8")
        except OSError:
            return

    def requested(self) -> bool:
        if self._event.is_set():
            return True
        return self.stop_file.exists()

    def clear(self) -> None:
        self._event.clear()
        try:
            self.stop_file.unlink(missing_ok=True)
        except OSError:
            return
