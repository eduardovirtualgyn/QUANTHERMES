"""
QUANT HERMES — Modelos Base e Tipagem Imutável
Módulo: core.models.base
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Gera timestamp UTC consciente de fuso horário."""
    return datetime.now(timezone.utc)


class HermesBaseModel(BaseModel):
    """Modelo base para todos os contratos tipados do sistema QUANT HERMES."""

    model_config = ConfigDict(
        frozen=True,               # Imutabilidade estrita das mensagens
        extra="forbid",            # Proíbe campos adicionais não declarados
        validate_assignment=True,  # Valida atribuições
        arbitrary_types_allowed=False,
    )


class IdentifiableEvent(HermesBaseModel):
    """Evento identificável por ID único e carimbo de data/hora UTC."""

    event_id: UUID = Field(default_factory=uuid4, description="Identificador único universal do evento")
    timestamp: datetime = Field(default_factory=utc_now, description="Timestamp UTC de criação")

