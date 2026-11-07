"""
QUANT HERMES — Modelos de Sinais e Consenso de Agentes
Módulo: core.models.agent
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import Field, field_validator
from core.models.base import HermesBaseModel, utc_now
from core.models.market import TimeFrame


class SignalDirection(str, Enum):
    """Direção da recomendação emitida por agentes ou estratégias."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class AgentSignal(HermesBaseModel):
    """Sinal emitido por um dos 8 agentes especializados ou famílias de estratégia."""

    signal_id: UUID = Field(default_factory=uuid4, description="ID exclusivo do sinal")
    timestamp: datetime = Field(default_factory=utc_now, description="Timestamp de geração")
    agent_id: str = Field(..., description="Identificador do agente (ex: AG01_TREND)")
    symbol: str = Field(..., description="Instrumento (ex: EURUSD, XAUUSD)")
    timeframe: TimeFrame = Field(..., description="Timeframe de análise")
    direction: SignalDirection = Field(..., description="BUY, SELL ou HOLD")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiança calibrada do agente (0.0 a 1.0)")
    suggested_entry: float = Field(..., gt=0.0, description="Preço de referência de entrada")
    suggested_stop: float = Field(..., gt=0.0, description="Nível numérico de Stop Loss sugerido")
    suggested_target: float = Field(..., gt=0.0, description="Nível de Take Profit sugerido")
    invalidation_level: float = Field(..., gt=0.0, description="Preço onde a tese é descaracterizada")
    rationale: dict[str, Any] = Field(default_factory=dict, description="Evidências e métricas que sustentam o sinal")
    model_version: str = Field(..., description="Versão do modelo ou lógica quantitativa")

    @field_validator("suggested_stop")
    @classmethod
    def validate_stop_coherence(cls, stop: float, info) -> float:
        direction = info.data.get("direction")
        entry = info.data.get("suggested_entry")
        if direction == SignalDirection.BUY and entry is not None and stop >= entry:
            raise ValueError(f"Para ordem BUY, Stop Loss ({stop}) deve ser estritamente menor que a entrada ({entry})")
        if direction == SignalDirection.SELL and entry is not None and stop <= entry:
            raise ValueError(f"Para ordem SELL, Stop Loss ({stop}) deve ser estritamente maior que a entrada ({entry})")
        return stop


class ConsensusDecision(HermesBaseModel):
    """Decisão ponderada consolidada pelo Motor de Consenso (AG08)."""

    decision_id: UUID = Field(default_factory=uuid4, description="ID exclusivo da decisão")
    timestamp: datetime = Field(default_factory=utc_now, description="Timestamp de deliberação")
    symbol: str = Field(..., description="Instrumento avaliado")
    action: SignalDirection = Field(..., description="Ação resultante: BUY, SELL ou HOLD")
    composite_score: float = Field(..., ge=-1.0, le=1.0, description="Score composto ponderado (-1.0 a +1.0)")
    calibrated_probability: float = Field(..., ge=0.0, le=1.0, description="Probabilidade calibrada de sucesso")
    active_regime: str = Field(..., description="Regime de mercado vigente no momento da decisão")
    participating_agents: list[str] = Field(default_factory=list, description="Lista de agentes que votaram")
    dissenting_agents: list[str] = Field(default_factory=list, description="Lista de agentes discordantes")
    invalidation_criteria: list[str] = Field(default_factory=list, description="Condições que cancelam a proposta")
    suggested_entry: float = Field(..., gt=0.0)
    suggested_stop: float = Field(..., gt=0.0)
    suggested_target: float = Field(..., gt=0.0)
