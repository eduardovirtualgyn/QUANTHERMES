"""
QUANT HERMES — Gerenciador Central de Portfólio (Portfolio Manager)
Módulo: portfolio.manager
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from core.logger import get_logger
from core.models.agent import ConsensusDecision
from core.models.base import utc_now
from core.models.market import MarketTick, SymbolSpecification
from core.models.risk import (
    AccountState,
    Position,
    RiskAuthorization,
    TradeProposal,
)
from portfolio.allocator import CapitalAllocator
from portfolio.correlation import CorrelationMonitor
from risk.engine import RiskEngine

logger = get_logger("portfolio.manager")


class PortfolioManager:
    """
    Gerenciador de Portfólio do QUANT HERMES.
    Princípio de Filosofia:
        "Estratégias e Agentes emitem sinais e hipóteses; o Portfólio arbitra,
         deduplica e aloca capital; mas SOMENTE o Risk Engine autoriza a ordem."
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        allocator: Optional[CapitalAllocator] = None,
        correlation_monitor: Optional[CorrelationMonitor] = None,
        dedup_cooldown_seconds: int = 60,
    ):
        self.risk_engine = risk_engine
        self.allocator = allocator or CapitalAllocator()
        self.correlation_monitor = correlation_monitor or CorrelationMonitor()
        self.dedup_cooldown_seconds = dedup_cooldown_seconds

        # Registro de deduplicação: (symbol, action) -> timestamp
        self._recent_proposals: Dict[Tuple[str, str], datetime] = {}

    def _is_duplicate(self, symbol: str, action: str, now: datetime) -> bool:
        """Verifica se uma proposta idêntica foi gerada dentro da janela de cooldown."""
        key = (symbol.upper(), action.upper())
        last_time = self._recent_proposals.get(key)
        if last_time and (now - last_time).total_seconds() < self.dedup_cooldown_seconds:
            return True
        return False

    def _record_proposal(self, symbol: str, action: str, now: datetime) -> None:
        """Registra a geração da proposta para deduplicação."""
        key = (symbol.upper(), action.upper())
        self._recent_proposals[key] = now

    def process_consensus_decision(
        self,
        decision: ConsensusDecision,
        strategy_id: str,
        account_state: Optional[AccountState],
        current_tick: Optional[MarketTick],
        normal_spread: Optional[float],
        spec: SymbolSpecification,
        open_positions: List[Position],
        known_specs: Optional[dict[str, SymbolSpecification]] = None,
        target_risk_pct: float = 0.25,
    ) -> Optional[RiskAuthorization]:
        """
        Processa uma deliberação do Motor de Consenso (AG08):
        1. Ignora decisões HOLD.
        2. Deduplica sinais redundantes dentro da janela de cooldown.
        3. Verifica correlação de pares e exposição concentrada.
        4. Aloca capital respeitando limites familiares e globais.
        5. Constrói TradeProposal formal.
        6. Submete a proposta à soberania do Risk Engine.
        """
        if decision.action.value == "HOLD":
            logger.debug("portfolio_manager_ignored_hold_decision", symbol=decision.symbol)
            return None

        action_str = decision.action.value  # "BUY" ou "SELL"
        now = utc_now()

        # 1. Deduplicação
        if self._is_duplicate(decision.symbol, action_str, now):
            logger.warning(
                "portfolio_manager_deduplicated_signal",
                symbol=decision.symbol,
                action=action_str,
                cooldown_sec=self.dedup_cooldown_seconds,
            )
            return None

        # 2. Monitor de Correlação
        corr_ok, corr_reason = self.correlation_monitor.check_correlation_limit(
            proposed_symbol=decision.symbol,
            proposed_action=action_str,
            open_positions=open_positions,
        )
        if not corr_ok:
            logger.warning("portfolio_manager_blocked_by_correlation", reason=corr_reason)
            return RiskAuthorization(
                decision_id=decision.decision_id,
                symbol=decision.symbol,
                action=action_str,
                approved=False,
                authorized_lot=0.0,
                stop_loss=decision.suggested_stop,
                take_profit=decision.suggested_target,
                risk_amount_money=0.0,
                risk_percentage=0.0,
                rejection_reason=corr_reason,
            )

        # 3. Alocação de Capital
        # Calcula risco aberto atual
        specs_map = known_specs or {decision.symbol: spec}
        total_open_risk = (
            self.risk_engine.calculate_current_open_risk_pct(
                open_positions=open_positions,
                specs=specs_map,
                equity=account_state.equity if account_state else 0.0,
            )
            if account_state
            else 0.0
        )

        allocated_risk = self.allocator.allocate_risk(
            strategy_id=strategy_id,
            requested_risk_pct=target_risk_pct,
            current_family_open_risk_pct=0.0,  # Calculado por posições ativas
            total_open_risk_pct=total_open_risk,
        )

        if allocated_risk <= 0.0:
            reason = "CAPITAL_ALLOCATOR: Orçamento de risco esgotado para a estratégia ou portfólio"
            logger.warning("portfolio_manager_blocked_by_allocator", reason=reason)
            return RiskAuthorization(
                decision_id=decision.decision_id,
                symbol=decision.symbol,
                action=action_str,
                approved=False,
                authorized_lot=0.0,
                stop_loss=decision.suggested_stop,
                take_profit=decision.suggested_target,
                risk_amount_money=0.0,
                risk_percentage=0.0,
                rejection_reason=reason,
            )

        # 4. Construção da TradeProposal
        proposal = TradeProposal(
            decision_id=decision.decision_id,
            strategy_id=strategy_id,
            symbol=decision.symbol,
            action=action_str,
            entry_price=decision.suggested_entry,
            stop_loss=decision.suggested_stop,
            take_profit=decision.suggested_target,
            target_risk_pct=allocated_risk,
        )

        # Registra proposta para deduplicação
        self._record_proposal(decision.symbol, action_str, now)

        # 5. Encaminhamento Soberano ao Risk Engine
        auth = self.risk_engine.evaluate_proposal(
            proposal=proposal,
            account_state=account_state,
            current_tick=current_tick,
            normal_spread=normal_spread,
            spec=spec,
            open_positions=open_positions,
            known_specs=known_specs,
        )

        return auth
