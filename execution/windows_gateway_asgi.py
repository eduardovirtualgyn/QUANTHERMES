"""
Ponto de entrada ASGI do gateway MT5. Somente no host Windows com o terminal.

O cérebro Linux não importa este módulo. Wine não é o caminho suportado:
o cérebro fala HTTP com este gateway. A escuta é em 127.0.0.1; o acesso
remoto exige VPN ou reverse proxy com TLS.
"""
from __future__ import annotations

import os

from execution.gateway.mt5_gateway import create_gateway_app

app = create_gateway_app()


def main() -> None:
    import uvicorn

    port = int(os.getenv("HERMES_GATEWAY_PORT", "8001"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
