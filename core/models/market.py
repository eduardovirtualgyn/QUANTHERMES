"""
QUANT HERMES — Modelos de Dados de Mercado
Módulo: core.models.market
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from typing_extensions import Self
from pydantic import Field, field_validator, model_validator
from core.models.base import HermesBaseModel


class TimeFrame(str, Enum):
    """Timeframes suportados nativamente pelo QUANT HERMES."""
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


class MarketTick(HermesBaseModel):
    """Estrutura imutável de tick de mercado recebido da plataforma."""

    symbol: str = Field(..., description="Símbolo do ativo (ex: EURUSD, XAUUSD)")
    time: datetime = Field(..., description="Timestamp do tick")
    bid: float = Field(..., gt=0.0, description="Preço de Bid atual")
    ask: float = Field(..., gt=0.0, description="Preço de Ask atual")
    last: float = Field(default=0.0, ge=0.0, description="Último preço negociado")
    volume: float = Field(default=0.0, ge=0.0, description="Volume do tick")
    flags: int = Field(default=0, description="Flags do tick do MT5")

    @property
    def spread(self) -> float:
        """Calcula o spread nominal entre Ask e Bid."""
        return round(self.ask - self.bid, 6)

    @field_validator("ask")
    @classmethod
    def validate_ask_gte_bid(cls, v: float, info) -> float:
        bid = info.data.get("bid")
        if bid is not None and v < bid:
            raise ValueError(f"Ask ({v}) não pode ser menor que Bid ({bid})")
        return v


class MarketBar(HermesBaseModel):
    """Estrutura imutável de candle/barra OHLCV."""

    symbol: str = Field(..., description="Símbolo do ativo")
    timeframe: TimeFrame = Field(..., description="Timeframe da barra")
    time: datetime = Field(..., description="Timestamp de abertura do candle")
    open: float = Field(..., gt=0.0, description="Preço de abertura")
    high: float = Field(..., gt=0.0, description="Preço máximo")
    low: float = Field(..., gt=0.0, description="Preço mínimo")
    close: float = Field(..., gt=0.0, description="Preço de fechamento")
    tick_volume: int = Field(..., ge=0, description="Volume de ticks")
    spread: int = Field(default=0, ge=0, description="Spread em pontos")
    is_closed: bool = Field(default=True, description="Indica se o candle está totalmente fechado")

    @model_validator(mode="after")
    def validate_bar_coherence(self) -> Self:
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) não pode ser menor que Low ({self.low})")
        if self.high < self.open:
            raise ValueError(f"High ({self.high}) não pode ser menor que Open ({self.open})")
        if self.high < self.close:
            raise ValueError(f"High ({self.high}) não pode ser menor que Close ({self.close})")
        if self.low > self.open:
            raise ValueError(f"Low ({self.low}) não pode ser maior que Open ({self.open})")
        if self.low > self.close:
            raise ValueError(f"Low ({self.low}) não pode ser maior que Close ({self.close})")
        return self


class SymbolSpecification(HermesBaseModel):
    """Especificação e características de trading do ativo fornecidas pela corretora."""

    symbol: str = Field(..., description="Símbolo oficial na corretora")
    canonical_name: str = Field(..., description="Nome canônico interno (EURUSD, XAUUSD)")
    category: Literal["forex_major", "forex_cross", "metal", "index", "crypto"] = Field(
        ..., description="Categoria do instrumento"
    )
    base_currency: str = Field(..., description="Moeda base")
    quote_currency: str = Field(..., description="Moeda de cotação")
    digits: int = Field(..., ge=0, description="Casas decimais de cotação")
    point: float = Field(..., gt=0.0, description="Tamanho do ponto (ex: 0.00001)")
    tick_size: float = Field(..., gt=0.0, description="Tamanho mínimo de variação")
    tick_value: float = Field(..., gt=0.0, description="Valor financeiro do tick por lote")
    contract_size: float = Field(..., gt=0.0, description="Tamanho do contrato padrão")
    volume_min: float = Field(..., gt=0.0, description="Lote mínimo permitido")
    volume_max: float = Field(..., gt=0.0, description="Lote máximo permitido")
    volume_step: float = Field(..., gt=0.0, description="Passo de incremento de volume")
    stops_level: int = Field(default=0, ge=0, description="Distância mínima para Stop em pontos")
    filling_mode: Literal["FOK", "IOC", "RETURN"] = Field(
        default="IOC", description="Modo de preenchimento de ordem suportado"
    )
    swap_long: float = Field(default=0.0, description="Swap de compra por lote por noite (pontos ou moeda)")
    swap_short: float = Field(default=0.0, description="Swap de venda por lote por noite (pontos ou moeda)")
    swap_rollover3days: int = Field(
        default=3, ge=0, le=6, description="Dia MT5 do swap triplo (0=domingo … 3=quarta)"
    )
    swap_mode: Literal["points", "account_currency", "interest"] = Field(
        default="points", description="Unidade do swap reportada pelo symbol_info"
    )
