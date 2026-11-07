"""
QUANT HERMES — Interface Abstrata para Estratégias Quantitativas
Módulo: strategies.base
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.logger import get_logger
from core.models.agent import AgentSignal, SignalDirection
from core.models.base import utc_now
from core.models.market import MarketBar, MarketTick, TimeFrame

logger = get_logger("strategies.base")


class BaseStrategy(ABC):
    """
    Classe base para todas as famílias de estratégias quantitativas do QUANT HERMES.
    Princípio Soberano:
    1. Estratégias produzem 'AgentSignal' com entry, stop loss e take profit matematicamente coerentes.
    2. Estratégias NUNCA enviam ordens para corretores ou alteram parâmetros de risco diretamente.
    3. Toda proposta deve obrigatoriamente respeitar a razão mínima de Risco/Retorno (min_rr_ratio).
    """

    def __init__(
        self,
        strategy_id: str,
        family: str,
        target_symbols: List[str],
        target_timeframes: List[TimeFrame],
        min_rr_ratio: float = 1.5,
        model_version: str = "1.0.0",
    ):
        self.strategy_id = strategy_id
        self.family = family
        self.target_symbols = [s.upper() for s in target_symbols]
        self.target_timeframes = target_timeframes
        self.min_rr_ratio = min_rr_ratio
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
    ) -> Optional[AgentSignal]:
        """
        Constrói e valida formalmente um AgentSignal.
        Garante que a relação risco/retorno satisfaça o mínimo configurado.
        """
        if direction == SignalDirection.HOLD:
            return None

        risk_dist = abs(entry - stop_loss)
        reward_dist = abs(take_profit - entry)

        if risk_dist <= 0.0 or reward_dist <= 0.0:
            logger.warning("strategy_signal_rejected_zero_distance", strategy=self.strategy_id)
            return None

        rr_ratio = round(reward_dist / risk_dist, 2)
        if rr_ratio < self.min_rr_ratio:
            logger.debug(
                "strategy_signal_filtered_insufficient_rr",
                strategy=self.strategy_id,
                rr=rr_ratio,
                min_rr=self.min_rr_ratio,
            )
            return None

        # Validação estrita de direção do stop loss
        if direction == SignalDirection.BUY and stop_loss >= entry:
            logger.error("strategy_signal_rejected_invalid_buy_sl", strategy=self.strategy_id)
            return None
        if direction == SignalDirection.SELL and stop_loss <= entry:
            logger.error("strategy_signal_rejected_invalid_sell_sl", strategy=self.strategy_id)
            return None

        rat = rationale or {}
        rat["rr_ratio"] = rr_ratio
        rat["family"] = self.family

        return AgentSignal(
            agent_id=self.strategy_id,
            symbol=symbol.upper(),
            timeframe=timeframe,
            direction=direction,
            confidence=min(1.0, max(0.0, float(confidence))),
            suggested_entry=entry,
            suggested_stop=stop_loss,
            suggested_target=take_profit,
            invalidation_level=invalidation_level,
            rationale=rat,
            model_version=self.model_version,
            timestamp=utc_now(),
        )

    @abstractmethod
    def analyze(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: TimeFrame,
        current_tick: Optional[MarketTick] = None,
    ) -> Optional[AgentSignal]:
        """
        Executa a análise quantitativa da estratégia sobre as barras históricas.
        Retorna AgentSignal se uma oportunidade satisfatória for identificada, ou None.
        """
        pass
