"""
QUANT HERMES — ORQUESTRADOR CENTRAL AUTÔNOMO DE TRADING
Módulo: execution.orchestrator

Responsabilidade:
- Orquestração ponta-a-ponta do pipeline autônomo de negociação quantitativa:
  Market Data -> HMM Regimes -> Strategies -> Multi-Agent Consensus ->
  Portfolio Management -> Sovereign Risk Engine -> Order Execution -> Reconciler.
- Execução cíclica assíncrona em modo Paper Trading ou Terminal MT5 (Demo).
- Governança estrita: Somente o Risk Engine autoriza o despacho de ordens.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.event_bus import PrioritizedEventBus
from core.logger import get_logger
from core.models.agent import AgentSignal, ConsensusDecision, SignalDirection
from core.models.market import MarketBar, MarketTick, TimeFrame
from core.models.regime import MarketRegimeType, RegimeClassification
from core.models.risk import AccountState, OrderResult, Position, RiskAuthorization, TradeProposal
from data.ingestion.collector import MarketDataCollector
from execution.adapters.base import TradingPlatformAdapter
from execution.order_executor import OrderExecutor
from execution.state_manager import ExecutionState, ExecutionStateManager
from intelligence.agents.ag01_trend import TrendIntelligenceAgent
from intelligence.agents.ag02_structure import MarketStructureAgent
from intelligence.agents.ag03_momentum import MomentumBreakoutAgent
from intelligence.agents.ag04_mean_reversion import MeanReversionAgent
from intelligence.agents.ag05_gold_macro import GoldMacroAgent
from intelligence.agents.ag06_quantitative import QuantitativeAgent
from intelligence.agents.ag07_adversarial import AdversarialResearchAgent
from intelligence.consensus.engine import ConsensusEngine
from intelligence.regime.hmm_detector import HMMRegimeDetector
from portfolio.manager import PortfolioManager
from portfolio.reconciler import PositionReconciler, ReconciliationReport
from risk.engine import RiskEngine
from strategies.base import BaseStrategy
from strategies.breakout.volatility_breakout import VolatilityBreakoutStrategy
from strategies.mean_reversion.statistical_reversion import StatisticalMeanReversionStrategy
from strategies.momentum.momentum_surge import MomentumSurgeStrategy
from strategies.pullback.trend_pullback import TrendPullbackStrategy
from strategies.scalping.micro_momentum import MicroMomentumScalpingStrategy
from strategies.smc.structure_break import SMCStructureStrategy
from strategies.swing.macro_swing import MacroSwingStrategy

logger = get_logger("autonomous_orchestrator")


@dataclass
class SessionSummary:
    """Relatório consolidado de uma sessão autônoma de trading."""
    session_id: str
    start_time_utc: str
    end_time_utc: str
    total_bars_processed: int
    signals_generated: int
    consensus_deliberations: int
    proposals_submitted: int
    proposals_approved: int
    proposals_rejected: int
    orders_executed: int
    final_account_equity: float
    tracked_positions: List[int]
    reconciliation_reports_count: int


class AutonomousTradingOrchestrator:
    """
    Orquestrador Soberano do QUANT HERMES.
    Conecta de ponta-a-ponta toda a inteligência quantitativa à execução e risco.
    """

    def __init__(
        self,
        adapter: TradingPlatformAdapter,
        symbols: Optional[List[str]] = None,
        event_bus: Optional[PrioritizedEventBus] = None,
        storage_path: str = "data/storage/execution_state.json",
    ) -> None:
        self.adapter = adapter
        self.symbols = symbols or ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
        self.event_bus = event_bus or PrioritizedEventBus()

        # 1. Componentes de Execução e Estado
        self.state_manager = ExecutionStateManager(storage_path=storage_path)
        self.order_executor = OrderExecutor(adapter=self.adapter)
        self.reconciler = PositionReconciler()

        # 2. Componentes de Risco e Portfólio
        self.risk_engine = RiskEngine()
        self.portfolio_manager = PortfolioManager(risk_engine=self.risk_engine)

        # 3. Componentes de Inteligência e Consenso
        self.hmm_detector = HMMRegimeDetector()
        self.consensus_engine = ConsensusEngine()

        # 4. Agentes Especializados (AG01 a AG07)
        self.agents = {
            "AG01": TrendIntelligenceAgent(),
            "AG02": MarketStructureAgent(),
            "AG03": MomentumBreakoutAgent(),
            "AG04": MeanReversionAgent(),
            "AG05": GoldMacroAgent(),
            "AG06": QuantitativeAgent(hmm_detector=self.hmm_detector),
            "AG07": AdversarialResearchAgent(),
        }

        # 5. Estratégias Quantitativas Padrão
        self.strategies: List[BaseStrategy] = [
            MicroMomentumScalpingStrategy(),
            VolatilityBreakoutStrategy(),
            MomentumSurgeStrategy(),
            TrendPullbackStrategy(),
            StatisticalMeanReversionStrategy(),
            SMCStructureStrategy(),
            MacroSwingStrategy(),
        ]

        # 6. Buffers de Mercado e Coleta
        self.collector = MarketDataCollector(adapter=self.adapter, event_bus=self.event_bus)
        self._bars_buffer: Dict[str, List[MarketBar]] = {sym: [] for sym in self.symbols}
        self._current_regimes: Dict[str, RegimeClassification] = {}
        self._internal_positions: Dict[int, Position] = {}
        self._session_metrics = {
            "bars": 0,
            "signals": 0,
            "consensus": 0,
            "proposals": 0,
            "approved": 0,
            "rejected": 0,
            "orders": 0,
            "reconciliations": 0,
        }

        self.is_initialized: bool = False
        self.is_running: bool = False

    async def initialize(self) -> None:
        """
        Inicializa e conecta a plataforma, valida especificações e restaura o estado anterior.
        """
        logger.info("Iniciando AutonomousTradingOrchestrator do QUANT HERMES")

        # Conecta à plataforma de execução
        is_conn = self.adapter.is_connected()
        if asyncio.iscoroutine(is_conn):
            is_conn = await is_conn

        if not is_conn:
            connect_call = self.adapter.connect()
            connected = await connect_call if asyncio.iscoroutine(connect_call) else connect_call
            if not connected:
                raise ConnectionError("Falha ao conectar com o adapter de trading")

        # Valida especificações dos símbolos
        for symbol in self.symbols:
            spec_call = self.adapter.get_symbol_info(symbol)
            spec = await spec_call if asyncio.iscoroutine(spec_call) else spec_call
            if not spec:
                logger.warning("Especificação não disponível para símbolo no broker", extra={"symbol": symbol})

        # Restaura estado operacional persistido
        saved_state = self.state_manager.load_state()
        if saved_state:
            logger.info("Estado prévio restaurado", extra={"tracked": len(saved_state.tracked_tickets)})

        # Executa protocolo de recuperação pós-crash de ordens não resolvidas no SQLite
        recovered = await self.order_executor.recover_unresolved_orders()
        if recovered:
            logger.info("Ordens recuperadas no startup pelo OrderExecutor", extra={"count": len(recovered)})

        # Executa reconciliação de inicialização
        await self.run_reconciliation_cycle()

        self.state_manager.current_state.system_status = "RUNNING"
        self.state_manager.save_state()

        self.is_initialized = True
        self.is_running = True
        logger.info("AutonomousTradingOrchestrator inicializado e pronto para operação")

    async def process_tick(self, tick: MarketTick) -> None:
        """
        Atualiza o estado de mercado em tempo real e monitora circuit breakers.
        """
        if not self.is_running:
            return

        await self.collector.ingest_tick(tick)

    async def process_bar(self, bar: MarketBar) -> Optional[OrderResult]:
        """
        Ciclo analítico e de execução acionado a cada nova barra fechada:
        1. Atualiza buffer de barras.
        2. Detecta regime de mercado via HMM / AG06.
        3. Executa as estratégias quantitativas.
        4. Roda análise multiagente e consenso AG08.
        5. Submete ao PortfolioManager.
        6. Submete a TradeProposal ao RiskEngine soberano.
        7. Se aprovado, despacha a ordem via OrderExecutor.
        """
        if not self.is_running:
            return None

        self._session_metrics["bars"] += 1
        sym = bar.symbol
        if sym not in self._bars_buffer:
            self._bars_buffer[sym] = []

        self._bars_buffer[sym].append(bar)
        bars = self._bars_buffer[sym]

        # 1. Detecção e Atualização de Regime
        regime_classif = self._classify_regime_for_symbol(sym, bars)
        self._current_regimes[sym] = regime_classif

        # 2. Execução das Estratégias Quantitativas
        active_signal: Optional[AgentSignal] = None
        emitting_strategy: Optional[BaseStrategy] = None

        tf = TimeFrame(bar.timeframe.value)
        bars_multi_tf = {tf: bars}

        for strategy in self.strategies:
            target_symbols = getattr(strategy, "target_symbols", [sym])
            if sym not in target_symbols:
                continue

            try:
                sig = strategy.analyze(bars=bars, symbol=sym, timeframe=tf)
                if sig and sig.direction in (SignalDirection.BUY, SignalDirection.SELL):
                    active_signal = sig
                    emitting_strategy = strategy
                    self._session_metrics["signals"] += 1
                    break  # Seleciona o primeiro sinal qualificado da barra
            except Exception as e:
                logger.warning(
                    "Erro ao analisar estratégia quantitativa",
                    extra={"strategy": getattr(strategy, "strategy_id", "UNKNOWN"), "symbol": sym, "error": str(e)},
                )

        if not active_signal or not emitting_strategy:
            return None

        # 3. Análise dos Agentes Especializados de Inteligência (AG01..AG07)
        agent_signals: List[AgentSignal] = []
        for ag_id, agent in self.agents.items():
            try:
                ag_sig = agent.analyze(bars_multi_tf=bars_multi_tf, symbol=sym)
                if ag_sig:
                    agent_signals.append(ag_sig)
            except Exception as e:
                logger.warning(
                    "Erro na análise de agente especializado",
                    extra={"agent": ag_id, "symbol": sym, "error": str(e)},
                )

        # 4. Deliberação do Motor de Consenso (AG08)
        consensus = self.consensus_engine.deliberate(
            signals=agent_signals,
            active_regime=regime_classif.active_regime,
            symbol=sym,
        )
        self._session_metrics["consensus"] += 1

        # Se consenso for neutro (HOLD) ou sem convicção, encerra ciclo
        if consensus.action not in (SignalDirection.BUY, SignalDirection.SELL):
            return None

        # 5. Gestão Centralizada de Portfólio (Portfolio Manager)
        account_call = self.adapter.get_account_state()
        account = await account_call if asyncio.iscoroutine(account_call) else account_call

        pos_call = self.adapter.get_open_positions()
        open_positions = await pos_call if asyncio.iscoroutine(pos_call) else pos_call

        proposal = self.portfolio_manager.process_consensus_decision(
            decision=consensus,
            strategy_id=emitting_strategy.strategy_id,
            signal=active_signal,
            account_state=account,
            open_positions=open_positions,
        )

        if not proposal:
            logger.info("Proposta de trade inibida pelo Portfolio Manager (cooldown ou correlação)", extra={"symbol": sym})
            return None

        self._session_metrics["proposals"] += 1

        # 6. Avaliação Soberana do Risk Engine (Princípio Inviolável)
        spec_call = self.adapter.get_symbol_info(sym)
        symbol_spec = await spec_call if asyncio.iscoroutine(spec_call) else spec_call

        risk_auth = self.risk_engine.evaluate_proposal(
            proposal=proposal,
            account_state=account,
            open_positions=open_positions,
            symbol_spec=symbol_spec,
        )

        if not risk_auth.approved:
            self._session_metrics["rejected"] += 1
            logger.info(
                "Proposta REJEITADA pelo Risk Engine",
                extra={"symbol": sym, "reason": risk_auth.rejection_reason},
            )
            return None

        self._session_metrics["approved"] += 1

        # 7. Despacho Seguro via OrderExecutor
        result = await self.order_executor.execute_order(
            proposal=proposal,
            risk_auth=risk_auth,
        )

        if result.success and result.order_ticket > 0:
            self._session_metrics["orders"] += 1
            self.state_manager.add_tracked_ticket(result.order_ticket)

            # Registra no mapa interno para reconciliação
            self._internal_positions[result.order_ticket] = Position(
                ticket=result.order_ticket,
                symbol=sym,
                magic=proposal.magic,
                position_type=proposal.action,
                volume=result.volume_executed,
                open_price=result.price_executed,
                stop_loss=risk_auth.stop_loss,
                take_profit=risk_auth.take_profit,
                current_price=result.price_executed,
                open_time=datetime.now(timezone.utc),
            )

        return result

    def _classify_regime_for_symbol(self, symbol: str, bars: List[MarketBar]) -> RegimeClassification:
        """Determina o regime de mercado atual via HMM ou agente quantitativo AG06."""
        if len(bars) >= 50 and not self.hmm_detector.is_fitted:
            try:
                self.hmm_detector.fit(bars)
            except Exception as e:
                logger.warning("Falha ao ajustar HMM dinamicamente", extra={"symbol": symbol, "error": str(e)})

        ag06: QuantitativeAgent = self.agents["AG06"]  # type: ignore
        return ag06.classify_regime(bars, symbol=symbol)

    async def run_reconciliation_cycle(self) -> ReconciliationReport:
        """Executa rotina autônoma periódica de reconciliação de posições."""
        report = await self.reconciler.reconcile(
            adapter=self.adapter,
            internal_registry=self._internal_positions,
        )

        # Atualiza tickets rastreados removendo posições fechadas pelo broker
        pos_call = self.adapter.get_open_positions()
        current_open_positions = await pos_call if asyncio.iscoroutine(pos_call) else pos_call
        current_open_tickets = {p.ticket for p in current_open_positions}

        # Limpa posições fechadas do registro interno
        closed_tickets = [t for t in self._internal_positions if t not in current_open_tickets]
        for t in closed_tickets:
            del self._internal_positions[t]
            self.state_manager.remove_tracked_ticket(t)

        self.state_manager.update_reconciliation_timestamp()
        self._session_metrics["reconciliations"] += 1
        return report

    async def run_simulation_session(self, bars_by_symbol: Dict[str, List[MarketBar]]) -> SessionSummary:
        """
        Executa uma sessão cronológica completa de mercado em modo autônomo (Paper Trading).
        """
        if not self.is_initialized:
            await self.initialize()

        session_id = f"SESSION_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now(timezone.utc).isoformat()

        max_bars = max((len(b_list) for b_list in bars_by_symbol.values()), default=0)

        for i in range(max_bars):
            for sym, bars in bars_by_symbol.items():
                if i < len(bars):
                    bar = bars[i]
                    tick = MarketTick(
                        symbol=sym,
                        time=bar.time,
                        bid=bar.close,
                        ask=round(bar.close + 0.00010, 5),
                        last=bar.close,
                        volume=1.0,
                    )
                    await self.process_tick(tick)
                    await self.process_bar(bar)

            # Reconcilia a cada 30 barras
            if i > 0 and i % 30 == 0:
                await self.run_reconciliation_cycle()

        # Reconciliação final
        await self.run_reconciliation_cycle()
        end_time = datetime.now(timezone.utc).isoformat()

        acc_call = self.adapter.get_account_state()
        final_account = await acc_call if asyncio.iscoroutine(acc_call) else acc_call

        return SessionSummary(
            session_id=session_id,
            start_time_utc=start_time,
            end_time_utc=end_time,
            total_bars_processed=self._session_metrics["bars"],
            signals_generated=self._session_metrics["signals"],
            consensus_deliberations=self._session_metrics["consensus"],
            proposals_submitted=self._session_metrics["proposals"],
            proposals_approved=self._session_metrics["approved"],
            proposals_rejected=self._session_metrics["rejected"],
            orders_executed=self._session_metrics["orders"],
            final_account_equity=round(final_account.equity, 2),
            tracked_positions=list(self.state_manager.current_state.tracked_tickets),
            reconciliation_reports_count=self._session_metrics["reconciliations"],
        )

    async def shutdown(self) -> None:
        """Encerra a operação de forma segura, salva o estado e desconecta."""
        logger.info("Encerrando AutonomousTradingOrchestrator")
        self.is_running = False
        self.state_manager.current_state.system_status = "STOPPED"
        self.state_manager.save_state()

        disc_call = self.adapter.disconnect()
        if asyncio.iscoroutine(disc_call):
            await disc_call

        logger.info("AutonomousTradingOrchestrator encerrado com sucesso")
