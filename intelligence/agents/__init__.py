"""
QUANT HERMES — Módulo de Agentes Especializados de Inteligência
Módulo: intelligence.agents
"""
from intelligence.agents.base import BaseIntelligenceAgent
from intelligence.agents.ag01_trend import TrendIntelligenceAgent
from intelligence.agents.ag02_structure import MarketStructureAgent
from intelligence.agents.ag03_momentum import MomentumBreakoutAgent
from intelligence.agents.ag04_mean_reversion import MeanReversionAgent
from intelligence.agents.ag05_gold_macro import GoldMacroAgent
from intelligence.agents.ag06_quantitative import QuantitativeAgent
from intelligence.agents.ag07_adversarial import AdversarialResearchAgent, AdversarialDebateResult

__all__ = [
    "BaseIntelligenceAgent",
    "TrendIntelligenceAgent",
    "MarketStructureAgent",
    "MomentumBreakoutAgent",
    "MeanReversionAgent",
    "GoldMacroAgent",
    "QuantitativeAgent",
    "AdversarialResearchAgent",
    "AdversarialDebateResult",
]
