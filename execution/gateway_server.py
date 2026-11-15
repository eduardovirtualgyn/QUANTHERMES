"""
QUANT HERMES — SERVIDOR GATEWAY MT5 (WINDOWS NODE SERVICE)
Módulo: execution.gateway_server

Executa no nó Windows dedicado com acesso direto à biblioteca MetaTrader5 (ou adapter local).
Expõe uma API REST protegida por token de autenticação estrito para consumo do nó Linux Brain.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Header, Query, status
from pydantic import BaseModel, Field

from core.logger import get_logger
from core.models.market import TimeFrame
from core.models.risk import OrderRequest
from execution.adapters.base import TradingPlatformAdapter

logger = get_logger("execution.gateway_server")


class ClosePositionRequest(BaseModel):
    ticket: int = Field(..., gt=0)
    volume: Optional[float] = Field(default=None, gt=0.0)


class ModifyPositionRequest(BaseModel):
    ticket: int = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0.0)
    take_profit: float = Field(default=0.0, ge=0.0)


def create_gateway_app(
    adapter: TradingPlatformAdapter,
    api_token: Optional[str] = None,
) -> FastAPI:
    """
    Fábrica da aplicação FastAPI do Gateway MT5.
    """
    expected_token = api_token or os.getenv("HERMES_GATEWAY_TOKEN", "HERMES_GATEWAY_TOKEN_DEFAULT")

    app = FastAPI(
        title="QUANT HERMES — MT5 Remote Gateway",
        version="1.0.0",
        description="Ponte de execução dedicada para MetaTrader 5 em topologia Dual-Node.",
    )

    def verify_token(authorization: Optional[str] = Header(None)) -> bool:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de autorização ausente ou malformado",
            )
        token = authorization.split("Bearer ", 1)[1].strip()
        if token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token de acesso ao MT5 Gateway inválido",
            )
        return True

    @app.get("/api/v1/health", dependencies=[Depends(verify_token)])
    async def get_health() -> Dict[str, Any]:
        connected = await adapter.is_connected()
        return {
            "status": "HEALTHY" if connected else "DISCONNECTED",
            "adapter_connected": connected,
            "version": "1.0.0",
        }

    @app.get("/api/v1/account", dependencies=[Depends(verify_token)])
    async def get_account() -> Dict[str, Any]:
        state = await adapter.get_account_state()
        return state.model_dump(mode="json")

    @app.get("/api/v1/symbols/{symbol}", dependencies=[Depends(verify_token)])
    async def get_symbol_spec(symbol: str) -> Dict[str, Any]:
        spec = await adapter.get_symbol_info(symbol.upper())
        return spec.model_dump(mode="json")

    @app.get("/api/v1/market/ticks/{symbol}", dependencies=[Depends(verify_token)])
    async def get_ticks(symbol: str, count: int = Query(default=100, ge=1, le=1000)) -> List[Dict[str, Any]]:
        ticks = await adapter.get_ticks(symbol.upper(), count=count)
        return [t.model_dump(mode="json") for t in ticks]

    @app.get("/api/v1/market/bars/{symbol}", dependencies=[Depends(verify_token)])
    async def get_bars(
        symbol: str,
        timeframe: str = Query(default="M15"),
        count: int = Query(default=500, ge=1, le=5000),
    ) -> List[Dict[str, Any]]:
        tf = TimeFrame(timeframe.upper())
        bars = await adapter.get_bars(symbol.upper(), timeframe=tf, count=count)
        return [b.model_dump(mode="json") for b in bars]

    @app.post("/api/v1/orders/check", dependencies=[Depends(verify_token)])
    async def check_order(request: OrderRequest) -> Dict[str, Any]:
        return await adapter.check_order(request)

    @app.post("/api/v1/orders/send", dependencies=[Depends(verify_token)])
    async def send_order(request: OrderRequest) -> Dict[str, Any]:
        result = await adapter.send_order(request)
        return result.model_dump(mode="json")

    @app.get("/api/v1/positions", dependencies=[Depends(verify_token)])
    async def get_positions(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        positions = await adapter.get_open_positions(symbol=symbol.upper() if symbol else None)
        return [p.model_dump(mode="json") for p in positions]

    @app.post("/api/v1/positions/close", dependencies=[Depends(verify_token)])
    async def close_position(payload: ClosePositionRequest) -> Dict[str, Any]:
        result = await adapter.close_position(ticket=payload.ticket, volume=payload.volume)
        return result.model_dump(mode="json")

    @app.post("/api/v1/positions/modify", dependencies=[Depends(verify_token)])
    async def modify_position(payload: ModifyPositionRequest) -> Dict[str, Any]:
        result = await adapter.modify_position(
            ticket=payload.ticket,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
        )
        return result.model_dump(mode="json")

    return app

