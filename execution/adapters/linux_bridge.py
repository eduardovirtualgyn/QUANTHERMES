"""
QUANT HERMES — ADAPTADOR DE PONTE LINUX PARA METATRADER 5 (DUAL-NODE BRIDGE)
Módulo: execution.adapters.linux_bridge

Responsabilidade:
- Permitir que o cérebro analítico e de risco do QUANT HERMES seja executado em
  contêineres Linux (Docker / VPS Linux), comunicando-se de forma segura e assíncrona
  com o nó executor Windows Server onde o terminal físico MetaTrader 5 reside.
- Implementar a interface abstrata TradingPlatformAdapter com garantias estritas
  de Fail-Safe, timeouts configuráveis e autenticação por token institucional.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import httpx

from core.secrets import require_env

from core.logger import get_logger
from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position
from execution.adapters.base import PlatformConnectionError, TradingPlatformAdapter

logger = get_logger("execution.adapters.linux_bridge")


class LinuxMT5BridgeAdapter(TradingPlatformAdapter):
    """
    Adaptador de execução remota para arquitetura de nó duplo (Linux Brain <-> Windows Gateway).
    Conecta-se ao microserviço MT5 Gateway através de túnel seguro com autenticação via cabeçalho.
    """

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:8001",
        bridge_token: Optional[str] = None,
        timeout_seconds: float = 5.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.bridge_token = bridge_token.strip() if bridge_token else require_env("HERMES_BRIDGE_TOKEN")
        self.timeout = timeout_seconds
        self._external_client = client
        self._internal_client: Optional[httpx.AsyncClient] = None
        self._is_connected: bool = False

    def _get_client(self) -> httpx.AsyncClient:
        """Retorna cliente HTTP assíncrono com cabeçalhos de autenticação."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            headers = {
                "X-Hermes-Bridge-Token": self.bridge_token,
                "Content-Type": "application/json",
                "User-Agent": "QUANT-HERMES-LINUX-BRIDGE/1.0",
            }
            self._internal_client = httpx.AsyncClient(
                base_url=self.gateway_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._internal_client

    async def connect(self) -> bool:
        """Inicializa e autentica a conexão com o MT5 Gateway remoto."""
        client = self._get_client()
        try:
            resp = await client.post("/api/v1/bridge/connect")
            if resp.status_code == 200 and resp.json().get("success", False):
                self._is_connected = True
                logger.info(
                    "Conexão com MT5 Gateway estabelecida com sucesso",
                    extra={"gateway_url": self.gateway_url},
                )
                return True
            else:
                self._is_connected = False
                logger.error(
                    "Falha na autenticação ou inicialização do MT5 Gateway",
                    extra={"status_code": resp.status_code, "body": resp.text},
                )
                return False
        except Exception as e:
            self._is_connected = False
            logger.critical("Erro de rede ao conectar com MT5 Gateway", extra={"error": str(e)})
            raise PlatformConnectionError(f"Falha de comunicação com MT5 Gateway: {e}") from e

    async def disconnect(self) -> None:
        """Encerra a conexão e libera recursos do cliente HTTP."""
        if self._is_connected:
            client = self._get_client()
            try:
                await client.post("/api/v1/bridge/disconnect")
            except Exception as e:
                logger.warning("Falha ao notificar desconexão ao MT5 Gateway", extra={"error": str(e)})
        self._is_connected = False
        if self._internal_client is not None and not self._internal_client.is_closed:
            await self._internal_client.aclose()
            self._internal_client = None
        logger.info("Adaptador Linux Bridge desconectado com sucesso")

    async def is_connected(self) -> bool:
        """Verifica se o canal de comunicação e o terminal remoto estão saudáveis."""
        if not self._is_connected:
            return False
        client = self._get_client()
        try:
            resp = await client.get("/api/v1/bridge/is_connected")
            return resp.status_code == 200 and resp.json().get("connected", False)
        except Exception:
            return False

    async def get_account_state(self) -> AccountState:
        """Consulta o estado financeiro consolidado da conta via nó remoto."""
        client = self._get_client()
        try:
            resp = await client.get("/api/v1/bridge/account")
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Erro HTTP {resp.status_code} ao obter conta: {resp.text}")
            return AccountState.model_validate(resp.json())
        except Exception as e:
            logger.error("Falha ao obter estado da conta via bridge", extra={"error": str(e)})
            raise PlatformConnectionError(f"Fail-Safe: Impossível obter conta do MT5 Gateway: {e}") from e

    async def get_symbol_info(self, symbol: str) -> SymbolSpecification:
        """Obtém as especificações do ativo a partir do terminal MT5 remoto."""
        client = self._get_client()
        try:
            resp = await client.get("/api/v1/bridge/symbol_info", params={"symbol": symbol})
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Erro ao obter symbol_info para {symbol}: {resp.text}")
            return SymbolSpecification.model_validate(resp.json())
        except Exception as e:
            logger.error("Falha ao obter symbol_info via bridge", extra={"symbol": symbol, "error": str(e)})
            raise PlatformConnectionError(f"Fail-Safe: Falha ao obter especificações de {symbol}: {e}") from e

    async def get_ticks(self, symbol: str, count: int = 100) -> List[MarketTick]:
        """Obtém últimos ticks do ativo a partir do nó executor."""
        client = self._get_client()
        try:
            resp = await client.get("/api/v1/bridge/ticks", params={"symbol": symbol, "count": count})
            if resp.status_code != 200:
                return []
            return [MarketTick.model_validate(t) for t in resp.json()]
        except Exception as e:
            logger.warning("Falha ao obter ticks via bridge", extra={"symbol": symbol, "error": str(e)})
            return []

    async def get_bars(self, symbol: str, timeframe: TimeFrame, count: int = 500) -> List[MarketBar]:
        """Obtém histórico recente de barras OHLCV a partir do nó executor."""
        client = self._get_client()
        tf_val = timeframe.value if hasattr(timeframe, "value") else str(timeframe)
        try:
            resp = await client.get(
                "/api/v1/bridge/bars",
                params={"symbol": symbol, "timeframe": tf_val, "count": count},
            )
            if resp.status_code != 200:
                return []
            return [MarketBar.model_validate(b) for b in resp.json()]
        except Exception as e:
            logger.warning("Falha ao obter barras via bridge", extra={"symbol": symbol, "error": str(e)})
            return []

    async def check_order(self, request: OrderRequest) -> Dict[str, Any]:
        """Verifica a viabilidade de margem e parâmetros da ordem remotamente."""
        client = self._get_client()
        try:
            resp = await client.post("/api/v1/bridge/check_order", json=request.model_dump(mode="json"))
            if resp.status_code == 200:
                return resp.json()
            return {"retcode": -1, "comment": f"Bridge error HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"retcode": -1, "comment": f"Network exception: {e}"}

    async def send_order(self, request: OrderRequest) -> OrderResult:
        """
        Despacha a ordem para execução no nó Windows com protocolo de idempotência e auditoria.
        """
        client = self._get_client()
        try:
            resp = await client.post("/api/v1/bridge/send_order", json=request.model_dump(mode="json"))
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Erro no despacho da ordem via gateway: {resp.text}")
            return OrderResult.model_validate(resp.json())
        except Exception as e:
            logger.critical("Falha de rede crítica no envio de ordem via bridge", extra={"error": str(e)})
            raise PlatformConnectionError(f"Fail-Safe: Falha no envio físico da ordem ao gateway: {e}") from e

    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Consulta posições abertas no terminal remoto."""
        client = self._get_client()
        params = {"symbol": symbol} if symbol else {}
        try:
            resp = await client.get("/api/v1/bridge/positions", params=params)
            if resp.status_code != 200:
                return []
            return [Position.model_validate(p) for p in resp.json()]
        except Exception as e:
            logger.error("Falha ao consultar posições via bridge", extra={"error": str(e)})
            return []

    async def close_position(self, ticket: int, volume: Optional[float] = None) -> OrderResult:
        """Envia solicitação de encerramento de posição ao nó remoto."""
        client = self._get_client()
        payload = {"ticket": ticket, "volume": volume}
        try:
            resp = await client.post("/api/v1/bridge/close_position", json=payload)
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Erro ao fechar posição #{ticket}: {resp.text}")
            return OrderResult.model_validate(resp.json())
        except Exception as e:
            logger.critical("Falha ao fechar posição via bridge", extra={"ticket": ticket, "error": str(e)})
            raise PlatformConnectionError(f"Falha ao fechar posição #{ticket} no gateway: {e}") from e

    async def modify_position(self, ticket: int, stop_loss: float, take_profit: float) -> OrderResult:
        """Modifica níveis de proteção de posição no terminal remoto."""
        client = self._get_client()
        payload = {"ticket": ticket, "stop_loss": stop_loss, "take_profit": take_profit}
        try:
            resp = await client.post("/api/v1/bridge/modify_position", json=payload)
            if resp.status_code != 200:
                raise PlatformConnectionError(f"Erro ao modificar posição #{ticket}: {resp.text}")
            return OrderResult.model_validate(resp.json())
        except Exception as e:
            logger.critical("Falha ao modificar posição via bridge", extra={"ticket": ticket, "error": str(e)})
            raise PlatformConnectionError(f"Falha ao modificar posição #{ticket} no gateway: {e}") from e
