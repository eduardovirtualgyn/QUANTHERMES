"""
Ponto de entrada ASGI do cérebro Linux.

Não importa MetaTrader5. O terminal fica no gateway Windows
(`execution.windows_gateway_asgi:app`). Este módulo falha no import
se HERMES_OPERATOR_TOKEN não estiver definido.
"""
from __future__ import annotations

from monitoring.server import create_monitoring_app

app = create_monitoring_app()
