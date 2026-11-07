"""
QUANT HERMES — Interface Abstrata para Plataformas de Negociação
Módulo: execution.adapters.base
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional
from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position


class PlatformConnectionError(Exception):
    """Exceção levantada quando ocorre falha na conexão com o terminal ou corretora."""
    pass


class TradingPlatformAdapter(ABC):
    """
    Interface abstrata soberana para comunicação com plataformas de negociação.
    Desacopla completamente a lógica analítica do QUANT HERMES das particularidades
    de APIs proprietárias (MetaTrader 5, Paper Trading, Backtest Engine, etc.).
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Inicializa e autentica a conexão com a plataforma de trading."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Encerra graciosamente a conexão com a plataforma."""
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        """Retorna True se a conexão com o terminal/servidor estiver ativa e saudável."""
        pass

    @abstractmethod
    async def get_account_state(self) -> AccountState:
        """
        Retorna o estado financeiro consolidado da conta (balance, equity, margem, drawdown).
        Deve falhar de maneira segura (Fail-Safe) caso os dados não estejam disponíveis.
        """
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> SymbolSpecification:
        """Retorna as especificações reais do ativo (tick size, tick value, contract size, volume limits)."""
        pass

    @abstractmethod
    async def get_ticks(self, symbol: str, count: int = 100) -> List[MarketTick]:
        """Obtém a lista dos últimos ticks negociados do ativo."""
        pass

    @abstractmethod
    async def get_bars(self, symbol: str, timeframe: TimeFrame, count: int = 500) -> List[MarketBar]:
        """Obtém o histórico recente de candles/barras OHLCV do ativo."""
        pass

    @abstractmethod
    async def check_order(self, request: OrderRequest) -> dict[str, Any]:
        """
        Executa verificação prévia de viabilidade da ordem (margem necessária, spread, limites).
        Equivalente assíncrono ao OrderCheck do MT5.
        """
        pass

    @abstractmethod
    async def send_order(self, request: OrderRequest) -> OrderResult:
        """
        Despacha a ordem para execução no broker com garantia de idempotência e retorno auditável.
        """
        pass

    @abstractmethod
    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Retorna a lista de posições abertas no terminal, opcionalmente filtrada por símbolo."""
        pass

    @abstractmethod
    async def close_position(self, ticket: int, volume: Optional[float] = None) -> OrderResult:
        """Fecha uma posição aberta total ou parcialmente."""
        pass

    @abstractmethod
    async def modify_position(self, ticket: int, stop_loss: float, take_profit: float) -> OrderResult:
        """Modifica os níveis de Stop Loss e Take Profit de uma posição ativa."""
        pass

