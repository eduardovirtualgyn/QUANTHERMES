"""
QUANT HERMES — Módulo de Consenso Ponderado (Consensus Engine)
Módulo: intelligence.consensus
"""
from intelligence.consensus.engine import ConsensusEngine
from intelligence.consensus.weights import DEFAULT_QUALITY_FACTORS, REGIME_AGENT_WEIGHTS

__all__ = ["ConsensusEngine", "REGIME_AGENT_WEIGHTS", "DEFAULT_QUALITY_FACTORS"]

