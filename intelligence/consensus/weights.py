"""
QUANT HERMES — Matriz de Pesos de Regimes e Fatores de Qualidade dos Agentes
Módulo: intelligence.consensus.weights
"""
from __future__ import annotations

from typing import Dict
from core.models.regime import MarketRegimeType

# Matriz de pesos w_i(R) por Agente e Regime de Mercado
# Soma dos pesos por regime normalizada para 1.0
REGIME_AGENT_WEIGHTS: Dict[MarketRegimeType, Dict[str, float]] = {
    MarketRegimeType.TREND_BULL_STRONG: {
        "AG01_TREND": 0.35,
        "AG02_STRUCTURE": 0.25,
        "AG03_MOMENTUM": 0.20,
        "AG06_QUANT": 0.15,
        "AG05_GOLD_MACRO": 0.05,
        "AG04_MEAN_REVERSION": 0.00,  # Veto em forte tendência de alta
    },
    MarketRegimeType.TREND_BEAR_STRONG: {
        "AG01_TREND": 0.35,
        "AG02_STRUCTURE": 0.25,
        "AG03_MOMENTUM": 0.20,
        "AG06_QUANT": 0.15,
        "AG05_GOLD_MACRO": 0.05,
        "AG04_MEAN_REVERSION": 0.00,  # Veto em forte tendência de baixa
    },
    MarketRegimeType.RANGING_LOW_VOL: {
        "AG04_MEAN_REVERSION": 0.40,
        "AG02_STRUCTURE": 0.25,
        "AG06_QUANT": 0.20,
        "AG01_TREND": 0.05,
        "AG03_MOMENTUM": 0.05,
        "AG05_GOLD_MACRO": 0.05,
    },
    MarketRegimeType.EXPANSION_HIGH_VOL: {
        "AG03_MOMENTUM": 0.35,
        "AG02_STRUCTURE": 0.25,
        "AG05_GOLD_MACRO": 0.15,
        "AG06_QUANT": 0.15,
        "AG01_TREND": 0.10,
        "AG04_MEAN_REVERSION": 0.00,
    },
    MarketRegimeType.UNCERTAIN_TRANSITION: {
        "AG06_QUANT": 0.30,
        "AG02_STRUCTURE": 0.30,
        "AG01_TREND": 0.15,
        "AG04_MEAN_REVERSION": 0.10,
        "AG03_MOMENTUM": 0.10,
        "AG05_GOLD_MACRO": 0.05,
    },
}

# Fatores padrão de qualidade histórica fora da amostra Q_i (0.50 a 1.00)
DEFAULT_QUALITY_FACTORS: Dict[str, float] = {
    "AG01_TREND": 0.88,
    "AG02_STRUCTURE": 0.85,
    "AG03_MOMENTUM": 0.82,
    "AG04_MEAN_REVERSION": 0.84,
    "AG05_GOLD_MACRO": 0.86,
    "AG06_QUANT": 0.90,
    "AG07_ADVERSARIAL": 0.88,
    "AG08_PORTFOLIO": 0.92,
}
