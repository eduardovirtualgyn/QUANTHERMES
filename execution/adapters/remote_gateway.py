"""
QUANT HERMES — ADAPTADOR REMOTO DE GATEWAY MT5 (DUAL-NODE BRIDGE)
Módulo: execution.adapters.remote_gateway

Implementa a interface TradingPlatformAdapter para operação distribuída em dois nós:
- Nó 1 (Linux VPS / Container): Cérebro quantitativo, Risk Engine, Agentes, Dashboard.
- Nó 2 (Windows Server / MT5 Terminal): Gateway leve com acesso nativo à DLL do MetaTrader 5.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import httpx

from core.secrets import require_env

from core.logger import get_logger
from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position
from execution.adapters.base import PlatformConnectionError, TradingPlatformAdapter

logger = get_logger("execution.adapters.remote_gateway")


class RemoteMT5GatewayAdapter(TradingPlatformAdapter):
    """
    Adaptador cliente para comunicação remota segura com o microserviço MT5 Gateway.
    Permite que o QUANT HERMES opere em contêineres Linux sem necessidade de Wine.
    """

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:8001",
        api_token: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.api_token = api_token.strip() if api_token else require_env("HERMES_GATEWAY_TOKEN")
        self.timeout = timeout_seconds
        self._is_connected = False
        self._client: Optional[httpx.AsyncClient] = None

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "X-Client-Id": "HERMES_QUANT_BRAIN_LINUX",
        }

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.gateway_url,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
        return self._client

    async def connect(self) -> bool:
        """Testa conectividade com o nó Gateway Windows e valida autenticação."""
        try:
            client = await self._ensure_client()
            resp = await client.get("/api/v1/health")
            if resp.status_code == 200 and resp.json().get("status") == "HEALTHY":
                self._is_connected = True
                logger.info("Conectado com sucesso ao MT5 Gateway Remoto", extra={"url": self.gateway_url})
                return True
            else:
                self._is_connected = False
                logger.error("Falha ao autenticar com MT5 Gateway Remoto", extra={"status": resp.status_code})
                return False
        except Exception as e:
            self._is_connected = False
            logger.error("Erro de conexão com MT5 Gateway Remoto", extra={"error": str(e), "url": self.gateway_url})
            return False

    async def disconnect(self) -> None:
        """Encerra graciosamente a sessão com o Gateway."""
        self._is_connected = False
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        logger.info("Sessão com MT5 Gateway Remoto encerrada")

    async def is_connected(self) -> bool:
        return self._is_connected

    async def get_account_state(self) -> AccountState:
        """Consulta o estado consolidado da conta de trading no MT5 remoto."""
        client = await self._ensure_client()
        try:
            resp = await client.get("/api/v1/account")
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Gateway retornou HTTP {resp.status_code}: {resp.text}")
            return AccountState.model_validate(resp.json())
        except Exception as e:
            self._is_connected = False
            raise PlatformConnectionError(f"Erro ao consultar AccountState via Gateway: {e}") from e

    async def get_symbol_info(self, symbol: str) -> SymbolSpecification:
        """Obtém especificações de instrumento do MT5 remoto."""
        client = await self._ensure_client()
        try:
            resp = await client.get(f"/api/v1/symbols/{symbol}")
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Símbolo {symbol} não encontrado no Gateway (HTTP {resp.status_code})")
            return SymbolSpecification.model_validate(resp.json())
        except Exception as e:
            raise PlatformConnectionError(f"Falha ao obter especificações de {symbol}: {e}") from e

    async def get_ticks(self, symbol: str, count: int = 100) -> List[MarketTick]:
        """Obtém últimos ticks do ativo a partir do MT5 remoto."""
        client = await self._ensure_client()
        try:
            resp = await client.get(f"/api/v1/market/ticks/{symbol}?count={count}")
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Falha ao obter ticks de {symbol} (HTTP {resp.status_code})")
            return [MarketTick.model_validate(item) for item in resp.json()]
        except Exception as e:
            raise PlatformConnectionError(f"Erro de comunicação ao obter ticks: {e}") from e

    async def get_bars(self, symbol: str, timeframe: TimeFrame, count: int = 500) -> List[MarketBar]:
        """Obtém candles OHLCV recentes do ativo."""
        client = await self._ensure_client()
        tf_str = timeframe.value if hasattr(timeframe, "value") else str(timeframe)
        try:
            resp = await client.get(f"/api/v1/market/bars/{symbol}?timeframe={tf_str}&count={count}")
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Falha ao obter barras de {symbol} (HTTP {resp.status_code})")
            return [MarketBar.model_validate(item) for item in resp.json()]
        except Exception as e:
            raise PlatformConnectionError(f"Erro ao obter barras: {e}") from e

    async def check_order(self, request: OrderRequest) -> dict[str, Any]:
        """Valida previamente a ordem no terminal MT5 remoto."""
        client = await self._ensure_client()
        try:
            resp = await client.post("/api/v1/orders/check", json=request.model_dump(mode="json"))
            if resp.status_code != 200:
                return {"retcode": -1, "comment": f"Gateway Error: {resp.status_code}"}
            return resp.json()
        except Exception as e:
            return {"retcode": -1, "comment": f"Network Error: {e}"}

    async def send_order(self, request: OrderRequest) -> OrderResult:
        """Despacha a ordem aprovada para o terminal MT5 remoto."""
        client = await self._ensure_client()
        try:
            resp = await client.post("/api/v1/orders/send", json=request.model_dump(mode="json"))
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Erro ao despachar ordem no Gateway: {resp.text}")
            return OrderResult.model_validate(resp.json())
        except Exception as e:
            self._is_connected = False
            raise PlatformConnectionError(f"Falha de conexão ao enviar ordem: {e}") from e

    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Consulta posições abertas no terminal MT5 remoto."""
        client = await self._ensure_client()
        url = "/api/v1/positions"
        if symbol:
            url += f"?symbol={symbol}"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Falha ao obter posições abertas: {resp.text}")
            return [Position.model_validate(p) for p in resp.json()]
        except Exception as e:
            raise PlatformConnectionError(f"Erro ao consultar posições abertas: {e}") from e

    async def close_position(self, ticket: int, volume: Optional[float] = None) -> OrderResult:
        """Envia solicitação de encerramento de posição no MT5 remoto."""
        client = await self._ensure_client()
        payload = {"ticket": ticket, "volume": volume}
        try:
            resp = await client.post("/api/v1/positions/close", json=payload)
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Falha ao fechar posição #{ticket}: {resp.text}")
            return OrderResult.model_validate(resp.json())
        except Exception as e:
            raise PlatformConnectionError(f"Erro de comunicação ao fechar posição: {e}") from e

    async def modify_position(self, ticket: int, stop_loss: float, take_profit: float) -> OrderResult:
        """Modifica níveis de proteção de posição ativa no MT5 remoto."""
        client = await self._ensure_client()
        payload = {"ticket": ticket, "stop_loss": stop_loss, "take_profit": take_profit}
        try:
            resp = await client.post("/api/v1/positions/modify", json=payload)
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Falha ao modificar posição #{ticket}: {resp.text}")
            return OrderResult.model_validate(resp.json())
        except Exception as e:
            raise PlatformConnectionError(f"Erro de comunicação ao modificar posição: {e}") from e

