"""
QUANT HERMES — Interface Base para Agentes Especializados de Inteligência
Módulo: intelligence.agents.base
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.logger import get_logger
from core.models.agent import AgentSignal, SignalDirection
from core.models.base import utc_now
from core.models.market import MarketBar, MarketTick, TimeFrame

logger = get_logger("intelligence.agents.base")


class BaseIntelligenceAgent(ABC):
    """
    Classe base abstrata para todos os 8 Agentes Especializados do QUANT HERMES.
    Princípio:
    - Agentes analisam, formulam hipóteses e recomendam sinais com confiança calibrada.
    - Agentes NUNCA enviam ordens diretamente ao broker ou alteram parâmetros de risco.
    """

    def __init__(
        self,
        agent_id: str,
        name: str,
        quality_factor: float = 0.85,
        model_version: str = "1.0.0",
    ):
        self.agent_id = agent_id
        self.name = name
        # Fator Q_i: Qualidade histórica fora da amostra (0.50 a 1.00)
        self.quality_factor = max(0.50, min(1.00, quality_factor))
        self.model_version = model_version

    def build_signal(
        self,
        symbol: str,
        timeframe: TimeFrame,
        direction: SignalDirection,
        confidence: float,
        entry: float,
        stop_loss: float,
        take_profit: float,
        invalidation_level: float,
        rationale: Optional[Dict[str, Any]] = None,
    ) -> AgentSignal:
        """Constrói uma instância validada e imutável de AgentSignal."""
        return AgentSignal(
            agent_id=self.agent_id,
            symbol=symbol.upper(),
            timeframe=timeframe,
            direction=direction,
            confidence=round(max(0.0, min(1.0, float(confidence))), 4),
            suggested_entry=entry,
            suggested_stop=stop_loss,
            suggested_target=take_profit,
            invalidation_level=invalidation_level,
            rationale=rationale or {},
            model_version=self.model_version,
            timestamp=utc_now(),
        )

    @abstractmethod
    def analyze(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick: Optional[MarketTick] = None,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentSignal]:
        """
        Analisa os dados multi-timeframe e retorna a recomendação analítica do agente.
        """
        pass

