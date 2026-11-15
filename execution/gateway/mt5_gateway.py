"""
QUANT HERMES — MICROSERVIÇO GATEWAY PARA EXECUÇÃO REMOTA MT5
Módulo: execution.gateway.mt5_gateway

Responsabilidade:
- Executar no nó Windows Server (onde o terminal MT5 físico está instalado).
- Expor endpoints seguros REST para consumo exclusivo do nó analítico Linux.
- Validar o cabeçalho X-Hermes-Bridge-Token em todas as requisições.
- Serializar o envio físico de ordens em thread dedicada STA COM (max_workers=1).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.logger import get_logger
from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position
from execution.adapters.base import TradingPlatformAdapter
from execution.adapters.windows_mt5 import WindowsMT5Adapter

logger = get_logger("execution.gateway.mt5_gateway")


class ClosePositionRequest(BaseModel):
    ticket: int = Field(..., gt=0)
    volume: Optional[float] = Field(default=None, gt=0.0)


class ModifyPositionRequest(BaseModel):
    ticket: int = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0.0)
    take_profit: float = Field(default=0.0, ge=0.0)


def create_gateway_app(
    adapter: Optional[TradingPlatformAdapter] = None,
    secret_token: Optional[str] = None,
) -> FastAPI:
    """Fábrica da aplicação FastAPI para o Gateway MT5."""
    app = FastAPI(
        title="QUANT HERMES — MT5 Remote Gateway",
        version="1.0.0",
        description="Ponte de execução de alta performance para arquitetura dual-node (Linux <-> Windows).",
    )

    expected_token = secret_token or os.getenv("HERMES_BRIDGE_TOKEN", "HERMES_BRIDGE_SECRET_2026")
    exec_adapter = adapter or WindowsMT5Adapter()

    async def verify_bridge_token(
        x_hermes_bridge_token: Optional[str] = Header(None, alias="X-Hermes-Bridge-Token")
    ) -> str:
        if not x_hermes_bridge_token or x_hermes_bridge_token != expected_token:
            logger.warning("Tentativa de acesso não autorizado ao MT5 Gateway", extra={"provided_token": str(x_hermes_bridge_token)[:4]})
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso não autorizado: Token da ponte MT5 inválido ou ausente.",
            )
        return x_hermes_bridge_token

    @app.post("/api/v1/bridge/connect", dependencies=[Depends(verify_bridge_token)])
    async def bridge_connect() -> Dict[str, Any]:
        success = await exec_adapter.connect()
        return {"success": success, "connected": await exec_adapter.is_connected()}

    @app.post("/api/v1/bridge/disconnect", dependencies=[Depends(verify_bridge_token)])
    async def bridge_disconnect() -> Dict[str, Any]:
        await exec_adapter.disconnect()
        return {"success": True, "connected": False}

    @app.get("/api/v1/bridge/is_connected", dependencies=[Depends(verify_bridge_token)])
    async def bridge_is_connected() -> Dict[str, Any]:
        connected = await exec_adapter.is_connected()
        return {"connected": connected}

    @app.get("/api/v1/bridge/account", dependencies=[Depends(verify_bridge_token)])
    async def bridge_get_account() -> Dict[str, Any]:
        account = await exec_adapter.get_account_state()
        return account.model_dump()

    @app.get("/api/v1/bridge/symbol_info", dependencies=[Depends(verify_bridge_token)])
    async def bridge_get_symbol_info(symbol: str = Query(...)) -> Dict[str, Any]:
        info = await exec_adapter.get_symbol_info(symbol)
        return info.model_dump()

    @app.get("/api/v1/bridge/ticks", dependencies=[Depends(verify_bridge_token)])
    async def bridge_get_ticks(symbol: str = Query(...), count: int = Query(100, ge=1, le=10000)) -> List[Dict[str, Any]]:
        ticks = await exec_adapter.get_ticks(symbol=symbol, count=count)
        return [t.model_dump() for t in ticks]

    @app.get("/api/v1/bridge/bars", dependencies=[Depends(verify_bridge_token)])
    async def bridge_get_bars(
        symbol: str = Query(...),
        timeframe: str = Query("M15"),
        count: int = Query(500, ge=1, le=50000),
    ) -> List[Dict[str, Any]]:
        tf = TimeFrame(timeframe)
        bars = await exec_adapter.get_bars(symbol=symbol, timeframe=tf, count=count)
        return [b.model_dump() for b in bars]

    @app.post("/api/v1/bridge/check_order", dependencies=[Depends(verify_bridge_token)])
    async def bridge_check_order(request: OrderRequest) -> Dict[str, Any]:
        return await exec_adapter.check_order(request)

    @app.post("/api/v1/bridge/send_order", dependencies=[Depends(verify_bridge_token)])
    async def bridge_send_order(request: OrderRequest) -> Dict[str, Any]:
        result = await exec_adapter.send_order(request)
        return result.model_dump()

    @app.get("/api/v1/bridge/positions", dependencies=[Depends(verify_bridge_token)])
    async def bridge_get_positions(symbol: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
        positions = await exec_adapter.get_open_positions(symbol=symbol)
        return [p.model_dump() for p in positions]

    @app.post("/api/v1/bridge/close_position", dependencies=[Depends(verify_bridge_token)])
    async def bridge_close_position(payload: ClosePositionRequest) -> Dict[str, Any]:
        res = await exec_adapter.close_position(ticket=payload.ticket, volume=payload.volume)
        return res.model_dump()

    @app.post("/api/v1/bridge/modify_position", dependencies=[Depends(verify_bridge_token)])
    async def bridge_modify_position(payload: ModifyPositionRequest) -> Dict[str, Any]:
        res = await exec_adapter.modify_position(
            ticket=payload.ticket,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
        )
        return res.model_dump()

    return app


if __name__ == "__main__":
    import uvicorn
    gateway_port = int(os.getenv("HERMES_GATEWAY_PORT", "8001"))
    app = create_gateway_app()
    logger.info("Iniciando MT5 Gateway na porta %d...", gateway_port)
    uvicorn.run(app, host="0.0.0.0", port=gateway_port)
