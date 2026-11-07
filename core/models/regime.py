"""
QUANT HERMES — Modelos de Detecção e Classificação de Regimes
Módulo: core.models.regime
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import Field
from core.models.base import HermesBaseModel, utc_now


class MarketRegimeType(str, Enum):
    """Regimes de mercado detectados pelo Quantitative Intelligence Engine."""
    TREND_BULL_STRONG = "TREND_BULL_STRONG"
    TREND_BEAR_STRONG = "TREND_BEAR_STRONG"
    RANGING_LOW_VOL = "RANGING_LOW_VOL"
    EXPANSION_HIGH_VOL = "EXPANSION_HIGH_VOL"
    UNCERTAIN_TRANSITION = "UNCERTAIN_TRANSITION"


class RegimeClassification(HermesBaseModel):
    """Resultado estocástico/quantitativo da classificação de regime de mercado."""

    symbol: str = Field(..., description="Instrumento avaliado")
    timeframe: str = Field(..., description="Timeframe da análise de regime")
    active_regime: MarketRegimeType = Field(..., description="Regime com maior probabilidade a posteriori")
    probabilities: dict[str, float] = Field(..., description="Distribuição de probabilidades por estado")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Nível de confiança da classificação")
    entropy: float = Field(..., ge=0.0, description="Entropia de Shannon (medida de incerteza)")
    is_uncertain: bool = Field(default=False, description="Flag que sinaliza regime de alta incerteza")
    timestamp: datetime = Field(default_factory=utc_now)
