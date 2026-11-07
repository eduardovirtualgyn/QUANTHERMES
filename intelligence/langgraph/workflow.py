"""
QUANT HERMES — Orquestrador de Fluxo Multiagente (Multi-Agent Workflow)
Módulo: intelligence.langgraph.workflow
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.logger import get_logger
from core.models.agent import AgentSignal, ConsensusDecision, SignalDirection
from core.models.base import utc_now
from core.models.market import MarketBar, MarketTick, TimeFrame
from core.models.regime import MarketRegimeType, RegimeClassification
from intelligence.agents.ag01_trend import TrendIntelligenceAgent
from intelligence.agents.ag02_structure import MarketStructureAgent
from intelligence.agents.ag03_momentum import MomentumBreakoutAgent
from intelligence.agents.ag04_mean_reversion import MeanReversionAgent
from intelligence.agents.ag05_gold_macro import GoldMacroAgent
from intelligence.agents.ag06_quantitative import QuantitativeAgent
from intelligence.agents.ag07_adversarial import AdversarialDebateResult, AdversarialResearchAgent
from intelligence.consensus.engine import ConsensusEngine

logger = get_logger("intelligence.langgraph.workflow")


@dataclass
class MultiAgentCycleResult:
    """Resultado consolidado de um ciclo completo de inteligência multiagente."""
    symbol: str
    active_regime: MarketRegimeType
    classification: RegimeClassification
    agent_signals: List[AgentSignal] = field(default_factory=list)
    adversarial_debate: Optional[AdversarialDebateResult] = None
    consensus: Optional[ConsensusDecision] = None
    timestamp: datetime = field(default_factory=utc_now)


class MultiAgentWorkflow:
    """
    Grafo de orquestração analítica do QUANT HERMES.
    Coordena as 4 etapas fundamentais da inteligência:
    1. Classificação estocástica do Regime de Mercado (AG06).
    2. Execução analítica dos Agentes Especialistas (AG01 a AG06).
    3. Investigação adversarial dialética e detecção de armadilhas (AG07).
    4. Deliberação e pontuação composta pelo Motor de Consenso (AG08).
    """

    def __init__(
        self,
        ag01_trend: Optional[TrendIntelligenceAgent] = None,
        ag02_structure: Optional[MarketStructureAgent] = None,
        ag03_momentum: Optional[MomentumBreakoutAgent] = None,
        ag04_mean_reversion: Optional[MeanReversionAgent] = None,
        ag05_gold_macro: Optional[GoldMacroAgent] = None,
        ag06_quant: Optional[QuantitativeAgent] = None,
        ag07_adversarial: Optional[AdversarialResearchAgent] = None,
        consensus_engine: Optional[ConsensusEngine] = None,
    ):
        self.ag01 = ag01_trend or TrendIntelligenceAgent()
        self.ag02 = ag02_structure or MarketStructureAgent()
        self.ag03 = ag03_momentum or MomentumBreakoutAgent()
        self.ag04 = ag04_mean_reversion or MeanReversionAgent()
        self.ag05 = ag05_gold_macro or GoldMacroAgent()
        self.ag06 = ag06_quant or QuantitativeAgent()
        self.ag07 = ag07_adversarial or AdversarialResearchAgent()
        self.consensus = consensus_engine or ConsensusEngine()

    def run_cycle(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick: Optional[MarketTick] = None,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> MultiAgentCycleResult:
        """
        Executa um ciclo completo de inferência multiagente.
        """
        # 1. Determina regime de mercado através do AG06
        primary_tf = TimeFrame.M15 if TimeFrame.M15 in bars_multi_tf else TimeFrame.M5
        primary_bars = bars_multi_tf.get(primary_tf, [])

        classification = self.ag06.classify_regime(primary_bars, symbol, primary_tf.value)
        active_regime = classification.active_regime

        # 2. Executa os agentes especialistas
        specialist_agents = [
            self.ag01,
            self.ag02,
            self.ag03,
            self.ag04,
            self.ag05,
            self.ag06,
        ]

        signals: List[AgentSignal] = []
        for agent in specialist_agents:
            try:
                sig = agent.analyze(
                    bars_multi_tf=bars_multi_tf,
                    symbol=symbol,
                    current_tick=current_tick,
                    macro_context=macro_context,
                )
                if sig is not None:
                    signals.append(sig)
            except Exception as exc:
                logger.error("agent_execution_failed", agent=agent.agent_id, error=str(exc))

        # 3. Investigação Adversarial (AG07)
        # Identifica direção preliminar majoritária entre os sinais emitidos
        buy_votes = sum(1 for s in signals if s.direction == SignalDirection.BUY)
        sell_votes = sum(1 for s in signals if s.direction == SignalDirection.SELL)

        candidate_dir = SignalDirection.HOLD
        if buy_votes > sell_votes:
            candidate_dir = SignalDirection.BUY
        elif sell_votes > buy_votes:
            candidate_dir = SignalDirection.SELL

        adversarial_result = self.ag07.debate(
            candidate_direction=candidate_dir,
            bars=primary_bars,
            symbol=symbol,
            macro_context=macro_context,
        )

        # 4. Deliberação ponderada pelo Motor de Consenso (AG08)
        consensus_decision = self.consensus.deliberate(
            signals=signals,
            active_regime=active_regime,
            symbol=symbol,
            adversarial_result=adversarial_result,
        )

        return MultiAgentCycleResult(
            symbol=symbol,
            active_regime=active_regime,
            classification=classification,
            agent_signals=signals,
            adversarial_debate=adversarial_result,
            consensus=consensus_decision,
        )

