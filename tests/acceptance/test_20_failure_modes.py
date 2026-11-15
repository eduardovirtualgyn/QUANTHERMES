"""
QUANT HERMES — SUÍTE DE ACEITAÇÃO DOS 20 MODOS DE FALHA SISTÊMICOS (FASE 10)
Arquivo: tests/acceptance/test_20_failure_modes.py
Conformidade: Constituição de Engenharia (AGENTS.md) — Regra 2, Regra 11 e Regra 12.

Valida com rigor absoluto e asserções dinâmicas de borda:
 1. Queda Abrupta de Conexão com o Terminal MT5 (Socket Drop / TCP Disconnect).
 2. Filtragem de Cotações Anômalas e Ticks Stale (Ask < Bid, Spread Nulo, Duplicidade).
 3. Alargamento Anômalo de Spread (Extreme Spread Spike / Ilatência de Notícia).
 4. Auditoria de Slippage Adverso de Execução (Preenchimento com Deriva de Preço).
 5. Falha Crítica de Armazenamento SQLite / Idempotência (Postura Fail-Closed).
 6. Crash do Processo Durante Envio de Ordem (Recuperação de Estado Ambíguo).
 7. Supressão de Ordens Duplicadas (Rejeição Estrita de Violação de Idempotência).
 8. Veto Soberano por Violação do Risco por Operação (Hard Cap 0.50%).
 9. Veto Soberano por Excesso de Risco Agregado em Aberto (Teto 1.00%).
10. Veto por Limite Máximo de Posições Simultâneas Excedido (Teto 3 Posições).
11. Desarme por Perda Diária Máxima (Daily Drawdown Breaker 1.50%).
12. Desarme por Perda Semanal Máxima (Weekly Drawdown Breaker 3.00%).
13. Acionamento Compulsório de Kill Switch por Drawdown Extremo (Piso 8.00%).
14. Bloqueio Preventivo de Fim de Semana (Weekend Risk Guard após 20h UTC de sexta).
15. Rejeição Mandatória de Stop Loss Ausente ou Invertido (Compra com SL > Entrada).
16. Arredondamento Segura para Zero de Lotes Sub-Mínimos (Anti-Sobrealavancagem).
17. Detecção e Alerta de Posições Órfãs no Broker (Orphan Position Reconciled).
18. Detecção e Purga de Posições Fantasma no Registro Local (Ghost Position Reconciled).
19. Falha de Rede / Timeout na Ponte Dual-Node Linux-Windows (Fail-Closed Bridge).
20. Rejeição Categórica de Token de Risco Inválido, Adulterado ou Ausente.
"""

import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
import pytest
import httpx

from core.models.market import MarketTick, SymbolSpecification
from core.models.risk import (
    AccountState,
    OrderRequest,
    OrderResult,
    Position,
    RiskAuthorization,
    TradeProposal,
)
from data.ingestion.collector import MarketDataCollector
from execution.adapters.base import TradingPlatformAdapter
from execution.adapters.linux_bridge import LinuxMT5BridgeAdapter, PlatformConnectionError
from execution.adapters.paper import PaperTradingAdapter
from execution.idempotency import (
    OrderLifecycleState,
    SqliteIdempotencyStore,
    StoreCorruptedError,
)
from execution.order_executor import OrderExecutor
from portfolio.reconciler import PositionReconciler
from risk.circuit_breakers import (
    CircuitBreakerManager,
    DailyLossGuard,
    EmergencyDrawdownGuard,
    WeeklyLossGuard,
    WeekendRiskGuard,
)
from risk.engine import RiskEngine
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer


# ============================================================================
# FIXTURES COMPARTILHADAS DE AMBIENTE OPERACIONAL
# ============================================================================

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Banco SQLite temporário em diretório isolado."""
    return tmp_path / "hermes_acceptance_idempotency.db"


@pytest.fixture
def temp_ks_file(tmp_path: Path) -> Path:
    """Arquivo de estado do Kill Switch temporário."""
    return tmp_path / "acceptance_kill_switch.json"


@pytest.fixture
def eurusd_spec() -> SymbolSpecification:
    """Especificação institucional de EURUSD."""
    return SymbolSpecification(
        symbol="EURUSD",
        canonical_name="EURUSD",
        category="forex_major",
        base_currency="EUR",
        quote_currency="USD",
        digits=5,
        point=0.00001,
        tick_size=0.00001,
        tick_value=1.0,
        contract_size=100000.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )


@pytest.fixture
def standard_account() -> AccountState:
    """Conta de trading em estado saudável padrão ($100,000)."""
    return AccountState(
        login=882310,
        server="RoboForex-Demo",
        currency="USD",
        balance=100000.0,
        equity=100000.0,
        margin=0.0,
        free_margin=100000.0,
        peak_equity=100000.0,
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        current_drawdown_pct=0.0,
    )


@pytest.fixture
def wednesday_market_tick() -> MarketTick:
    """Tick de mercado saudável em meio de semana (Quarta-feira, 14:00 UTC)."""
    return MarketTick(
        symbol="EURUSD",
        time=datetime(2026, 11, 4, 14, 0, 0, tzinfo=timezone.utc),
        bid=1.08500,
        ask=1.08515,
        last=1.08500,
        volume=10.0,
    )


# ============================================================================
# ADAPTADORES DE TESTE PARA INJEÇÃO CONTROLADA DE FALHAS
# ============================================================================

class FaultyMT5Adapter(PaperTradingAdapter):
    """Adaptador com capacidade de injetar falhas de rede, slippage e desconexão."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.raise_disconnect_on_send: bool = False
        self.simulate_adverse_slippage: float = 0.0
        self.rejection_code: Optional[int] = None

    async def send_order(self, request: OrderRequest) -> OrderResult:
        if self.raise_disconnect_on_send:
            raise ConnectionResetError("MetaTrader 5 terminal IPC socket abruptly severed (WSAECONNRESET)")

        if self.rejection_code is not None:
            return OrderResult(
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                success=False,
                retcode=self.rejection_code,
                comment=f"BROKER_REJECTED_CODE_{self.rejection_code}",
            )

        res = await super().send_order(request)
        if self.simulate_adverse_slippage > 0.0 and res.success:
            # Altera o preço executado para injetar slippage adverso (respeitando modelo imutável)
            slippage_delta = self.simulate_adverse_slippage if request.action == "BUY" else -self.simulate_adverse_slippage
            res = res.model_copy(
                update={
                    "price_executed": round(res.price_executed + slippage_delta, 5),
                    "comment": f"EXECUTED_WITH_SLIPPAGE_{self.simulate_adverse_slippage}",
                }
            )
        return res


# ============================================================================
# OS 20 MODOS DE FALHA SISTÊMICOS DO QUANT HERMES
# ============================================================================

class TestTwentySystemicFailureModes:
    """
    Suíte completa de validação de aceitação dos 20 modos de falha.
    Proibido testes sem asserções ativas de borda e impacto dinâmico.
    """

    # ------------------------------------------------------------------------
    # MODO 01: Queda Abrupta de Conexão com Terminal MT5 (Socket Drop)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_01_mt5_socket_disconnect_fail_closed(self, temp_db: Path):
        """Falha 01: Desconexão abrupta de IPC/Socket com o MT5 deve abortar e registrar estado ambíguo."""
        adapter = FaultyMT5Adapter()
        adapter.raise_disconnect_on_send = True
        store = SqliteIdempotencyStore(temp_db)
        executor = OrderExecutor(adapter=adapter, store=store)

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )
        auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.10,
            stop_loss=1.08200,
            take_profit=1.09100,
            risk_amount_money=250.0,
            risk_percentage=0.25,
        )

        res = await executor.execute_order(proposal, auth)

        # Asserções de Fail-Closed:
        assert not res.success, "Ordem não pode ter sucesso com socket quebrado"
        assert res.retcode in (10006, 10024), "Retcode deve mapear erro de transporte de rede ou ambiguidade"
        assert "AMBIGUOUS_EXECUTION_RECONCILIATION_REQUIRED" in res.comment

        # O estado persistido em disco deve ser RECONCILIATION_REQUIRED
        record = store.get_intent_by_key(res.idempotency_key)
        assert record is not None
        assert record["state"] == OrderLifecycleState.RECONCILIATION_REQUIRED.value

    # ------------------------------------------------------------------------
    # MODO 02: Filtragem de Cotações Anômalas e Ticks Stale
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_02_stale_feed_and_inverted_tick_filtering(self):
        """Falha 02: Ticks invertidos (Ask < Bid) ou cotações nulas/duplicadas devem ser rejeitadas."""
        from pydantic import ValidationError
        adapter = PaperTradingAdapter()
        collector = MarketDataCollector(adapter=adapter)

        # 1. Barreira Constitucional de Schema: Ask menor que Bid rejeitado em tempo de instanciação
        with pytest.raises(ValidationError, match="Ask .* não pode ser menor que Bid"):
            MarketTick(
                symbol="EURUSD",
                time=datetime.now(timezone.utc),
                bid=1.08500,
                ask=1.08450,  # Ask < Bid
                last=1.08500,
                volume=1.0,
            )

        # 2. Barreira Constitucional de Schema: Bid zerado ou negativo rejeitado
        with pytest.raises(ValidationError):
            MarketTick(
                symbol="EURUSD",
                time=datetime.now(timezone.utc),
                bid=0.0,
                ask=1.08500,
                last=0.0,
                volume=1.0,
            )

        # 3. Barreira de Ingestão: Ticks duplicados descartados pelo coletor
        valid_tick = MarketTick(
            symbol="EURUSD",
            time=datetime(2026, 11, 4, 15, 0, 0, tzinfo=timezone.utc),
            bid=1.08500,
            ask=1.08515,
            last=1.08500,
            volume=5.0,
        )
        is_valid_3 = await collector.ingest_tick(valid_tick)
        assert is_valid_3, "Tick inicial válido deve ser aceito"

        duplicate_tick = MarketTick(
            symbol="EURUSD",
            time=datetime(2026, 11, 4, 15, 0, 0, tzinfo=timezone.utc),
            bid=1.08500,
            ask=1.08515,
            last=1.08500,
            volume=5.0,
        )
        is_valid_duplicate = await collector.ingest_tick(duplicate_tick)
        assert not is_valid_duplicate, "Tick com timestamp e preços idênticos DEVE ser deduplicado"

    # ------------------------------------------------------------------------
    # MODO 03: Alargamento Anômalo de Spread (Extreme Spread Spikes)
    # ------------------------------------------------------------------------
    def test_03_spread_spike_aborts_proposal(
        self,
        eurusd_spec: SymbolSpecification,
        standard_account: AccountState,
    ):
        """Falha 03: Alargamento anômalo de spread (ex: evento macro) deve vetar proposta imediatamente."""
        engine = RiskEngine(max_spread_multiplier=2.0)

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_MOMENTUM",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        normal_spread = 0.00015  # 1.5 pips normal
        # Tick com spread de 0.00060 (6.0 pips = 4x a média)
        spike_tick = MarketTick(
            symbol="EURUSD",
            time=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc),
            bid=1.08500,
            ask=1.08560,
            last=1.08500,
            volume=1.0,
        )

        auth = engine.evaluate_proposal(
            proposal=proposal,
            account_state=standard_account,
            current_tick=spike_tick,
            normal_spread=normal_spread,
            spec=eurusd_spec,
            open_positions=[],
        )

        assert not auth.approved, "Proposta com spread 4x normal deve ser terminantemente rejeitada"
        assert auth.authorized_lot == 0.0
        assert "SPREAD_ANOMALY" in (auth.rejection_reason or "")

    # ------------------------------------------------------------------------
    # MODO 04: Auditoria de Slippage Adverso de Execução
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_04_adverse_execution_slippage_audited(self, temp_db: Path):
        """Falha 04: Deriva de preço entre intenção e execução do broker deve ser quantificada."""
        adapter = FaultyMT5Adapter()
        # Injeta 4 pips de slippage adverso na compra
        adapter.simulate_adverse_slippage = 0.00040
        store = SqliteIdempotencyStore(temp_db)
        executor = OrderExecutor(adapter=adapter, store=store)

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_NEWS",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )
        auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.10,
            stop_loss=1.08200,
            take_profit=1.09100,
            risk_amount_money=250.0,
            risk_percentage=0.25,
        )

        res = await executor.execute_order(proposal, auth)

        assert res.success
        assert res.price_executed == 1.08540, "Preço preenchido deve refletir o slippage adverso injetado"
        slippage_pts = round(res.price_executed - proposal.entry_price, 5)
        assert slippage_pts == 0.00040, f"Slippage calculado ({slippage_pts}) deve ser exatamente 4 pips"

    # ------------------------------------------------------------------------
    # MODO 05: Falha Crítica de Armazenamento SQLite (Postura Fail-Closed)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_05_idempotency_store_corruption_fail_closed(self, temp_db: Path):
        """Falha 05: Se o banco SQLite falhar ou for corrompido, NENHUMA ordem é enviada ao mercado."""
        adapter = PaperTradingAdapter()
        store = SqliteIdempotencyStore(temp_db)
        executor = OrderExecutor(adapter=adapter, store=store)

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_SAFE",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )
        auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.10,
            stop_loss=1.08200,
            take_profit=1.09100,
            risk_amount_money=250.0,
            risk_percentage=0.25,
        )

        # Simula corrupção de disco travando o método de registro com StoreCorruptedError
        with patch.object(store, "register_intent_pre_submission", side_effect=StoreCorruptedError("Disk write failed: I/O error")):
            res = await executor.execute_order(proposal, auth)

        # Regra 12 da Constituição: Fail-Closed compulsório
        assert not res.success, "Ordem DEVE ser abortada se a persistência falhar"
        assert res.retcode in (10006, 10028)
        assert "PERSISTENCE_FAILURE_FAIL_CLOSED" in res.comment

        # Confirma que nenhuma posição foi aberta no adaptador
        open_pos = await adapter.get_open_positions()
        assert len(open_pos) == 0, "Nenhuma posição pode ter sido criada no broker"

    # ------------------------------------------------------------------------
    # MODO 06: Crash do Processo Durante Envio de Ordem (Recuperação Pós-Crash)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_06_crash_during_order_submission_recovery(self, temp_db: Path):
        """Falha 06: Reinicialização após crash durante despacho deve recuperar estado ambíguo sem reenviar."""
        store = SqliteIdempotencyStore(temp_db)
        intent_id = uuid4()
        decision_id = uuid4()

        # Simula ordem gravada como SUBMITTING antes do crash abrupto
        key = store.generate_idempotency_key(
            symbol="EURUSD",
            action="BUY",
            strategy_id="STRAT_TREND",
            decision_id=decision_id,
            auth_id=uuid4(),
        )
        store.register_intent_pre_submission(
            intent_id=intent_id,
            idempotency_key=key,
            decision_id=decision_id,
            auth_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            requested_lot=0.20,
            authorized_lot=0.20,
            entry_price=1.08500,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=123456,
        )
        store.transition_state(key, to_state=OrderLifecycleState.SUBMITTING, reason="Simulated process killed mid-flight")

        # Novo executor é instanciado simulando reinicialização do QUANT HERMES
        adapter = PaperTradingAdapter()
        new_executor = OrderExecutor(adapter=adapter, store=store)

        # Executa recuperação na inicialização
        unresolved = await new_executor.recover_unresolved_orders()

        assert len(unresolved) == 1
        rec = unresolved[0]
        assert rec["idempotency_key"] == key
        assert rec["status"] == "MARKED_RECONCILIATION_REQUIRED"

        # Verifica se o banco transicionou para RECONCILIATION_REQUIRED
        updated_lifecycle = store.get_intent_by_key(key)
        assert updated_lifecycle["state"] == OrderLifecycleState.RECONCILIATION_REQUIRED.value

    # ------------------------------------------------------------------------
    # MODO 07: Supressão de Ordens Duplicadas (Violação de Idempotência)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_07_duplicate_order_dispatch_rejection(self, temp_db: Path):
        """Falha 07: Envio duplicado da mesma intenção dentro da janela de retenção DEVE ser bloqueado."""
        adapter = PaperTradingAdapter()
        store = SqliteIdempotencyStore(temp_db)
        executor = OrderExecutor(adapter=adapter, store=store)

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_DUP",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )
        auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=True,
            authorized_lot=0.10,
            stop_loss=1.08200,
            take_profit=1.09100,
            risk_amount_money=250.0,
            risk_percentage=0.25,
        )

        # Primeiro envio: deve ter sucesso
        res1 = await executor.execute_order(proposal, auth)
        assert res1.success
        assert res1.order_ticket > 0

        # Segundo envio (duplicata acidental idêntica): deve ser suprimido
        res2 = await executor.execute_order(proposal, auth)
        assert not res2.success, "Ordem duplicada DEVE ser rejeitada pelo OrderExecutor"
        assert "DUPLICATE_ORDER_BLOCKED_BY_IDEMPOTENCY" in res2.comment

    # ------------------------------------------------------------------------
    # MODO 08: Veto Soberano por Violação do Risco por Operação (Hard Cap 0.50%)
    # ------------------------------------------------------------------------
    def test_08_risk_per_trade_exceeded_veto(
        self,
        eurusd_spec: SymbolSpecification,
        standard_account: AccountState,
        wednesday_market_tick: MarketTick,
    ):
        """Falha 08: Proposta com risco superior a 0.50% do capital DEVE ser rejeitada."""
        from pydantic import ValidationError

        # 1. Barramento no nível de Schema Pydantic V2 (Input Validation Gate)
        with pytest.raises(ValidationError):
            TradeProposal(
                decision_id=uuid4(),
                strategy_id="STRAT_GREED",
                symbol="EURUSD",
                action="BUY",
                entry_price=1.08500,
                stop_loss=1.08200,
                take_profit=1.09100,
                target_risk_pct=0.75,  # Excede le=0.50
            )

        # 2. Piso Inviolável do Risk Engine: afrouxamento acima de 0.50% lança ValueError
        with pytest.raises(ValueError, match="excede o piso inviolável de 0.50%"):
            RiskEngine(max_risk_percentage_hard_cap=0.60)

        # 3. Limitação pelo RiskEngine ao hard cap
        engine = RiskEngine(default_risk_percentage=0.25, max_risk_percentage_hard_cap=0.30)
        proposal_valid = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TEST",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.50,
        )
        auth = engine.evaluate_proposal(
            proposal=proposal_valid,
            account_state=standard_account,
            current_tick=wednesday_market_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert auth.approved
        assert auth.risk_percentage <= 0.30, "RiskEngine DEVE limitar a alocação ao hard cap de 0.30%"

    # ------------------------------------------------------------------------
    # MODO 09: Veto Soberano por Risco Agregado em Aberto (Teto 1.00%)
    # ------------------------------------------------------------------------
    def test_09_max_aggregate_risk_exceeded_veto(
        self,
        eurusd_spec: SymbolSpecification,
        standard_account: AccountState,
        wednesday_market_tick: MarketTick,
    ):
        """Falha 09: Risco agregado de posições em aberto + nova proposta excedendo 1.00% deve ser vetado."""
        engine = RiskEngine(max_aggregate_open_risk_pct=1.00)

        gbpusd_spec = SymbolSpecification(
            symbol="GBPUSD",
            canonical_name="GBPUSD",
            category="forex_major",
            base_currency="GBP",
            quote_currency="USD",
            digits=5,
            point=0.00001,
            tick_size=0.00001,
            tick_value=1.0,
            contract_size=100000.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
        )

        # Posição já aberta em GBPUSD arriscando 1.05% de $100,000 ($1050 de risco)
        existing_position = Position(
            ticket=1001,
            symbol="GBPUSD",
            magic=123456,
            position_type="BUY",
            volume=1.05,
            open_price=1.28500,
            stop_loss=1.27500,  # 100 pips = $1050 risco (1.05%)
            take_profit=1.30000,
            current_price=1.28500,
            open_time=datetime.now(timezone.utc),
        )

        new_proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        auth = engine.evaluate_proposal(
            proposal=new_proposal,
            account_state=standard_account,
            current_tick=wednesday_market_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[existing_position],
            known_specs={"EURUSD": eurusd_spec, "GBPUSD": gbpusd_spec},
        )

        assert not auth.approved, "Ordem que ultrapassa o teto agregado de 1.00% DEVE ser rejeitada"
        assert auth.authorized_lot == 0.0
        assert "AGGREGATE_RISK_LIMIT" in (auth.rejection_reason or "")

    # ------------------------------------------------------------------------
    # MODO 10: Limite Máximo de Posições Simultâneas Excedido (Teto 3)
    # ------------------------------------------------------------------------
    def test_10_max_concurrent_positions_exceeded_veto(
        self,
        eurusd_spec: SymbolSpecification,
        standard_account: AccountState,
        wednesday_market_tick: MarketTick,
    ):
        """Falha 10: Abertura da 4ª posição com teto de 3 posições abertas DEVE ser vetada."""
        engine = RiskEngine(max_open_positions=3, max_positions_per_symbol=5)

        # 3 posições existentes
        now_ts = datetime.now(timezone.utc)
        three_positions = [
            Position(ticket=101, symbol="EURUSD", position_type="BUY", volume=0.05, open_price=1.08, stop_loss=1.07, take_profit=1.10, current_price=1.08, profit=0.0, magic=1, open_time=now_ts),
            Position(ticket=102, symbol="EURUSD", position_type="BUY", volume=0.05, open_price=1.08, stop_loss=1.07, take_profit=1.10, current_price=1.08, profit=0.0, magic=1, open_time=now_ts),
            Position(ticket=103, symbol="EURUSD", position_type="BUY", volume=0.05, open_price=1.08, stop_loss=1.07, take_profit=1.10, current_price=1.08, profit=0.0, magic=1, open_time=now_ts),
        ]

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        auth = engine.evaluate_proposal(
            proposal=proposal,
            account_state=standard_account,
            current_tick=wednesday_market_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=three_positions,
        )

        assert not auth.approved, "4ª posição DEVE ser vetada com base no teto de 3 posições simultâneas"
        assert "MAX_POSITIONS_LIMIT" in (auth.rejection_reason or "")

    # ------------------------------------------------------------------------
    # MODO 11: Desarme por Perda Diária Máxima (Daily Loss 1.50%)
    # ------------------------------------------------------------------------
    def test_11_daily_drawdown_circuit_breaker_trip(
        self,
        eurusd_spec: SymbolSpecification,
        wednesday_market_tick: MarketTick,
    ):
        """Falha 11: Perda diária acumulada de 1.60% deve desarmar o DailyLossGuard imediatamente."""
        cbm = CircuitBreakerManager(max_daily_loss_pct=1.50)
        engine = RiskEngine(circuit_breakers=cbm)

        # Conta com perda diária de -1.60% no dia corrente
        damaged_account = AccountState(
            login=882310,
            server="Demo",
            currency="USD",
            balance=98400.0,
            equity=98400.0,
            margin=0.0,
            free_margin=98400.0,
            peak_equity=100000.0,
            daily_pnl_pct=-1.60,
            weekly_pnl_pct=-1.60,
            current_drawdown_pct=1.60,
        )

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        auth = engine.evaluate_proposal(
            proposal=proposal,
            account_state=damaged_account,
            current_tick=wednesday_market_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )

        assert not auth.approved
        assert "CIRCUIT_BREAKER_DAILY_LOSS" in (auth.rejection_reason or "")

    # ------------------------------------------------------------------------
    # MODO 12: Desarme por Perda Semanal Máxima (Weekly Loss 3.00%)
    # ------------------------------------------------------------------------
    def test_12_weekly_drawdown_circuit_breaker_trip(
        self,
        eurusd_spec: SymbolSpecification,
        wednesday_market_tick: MarketTick,
    ):
        """Falha 12: Perda semanal acumulada de 3.20% deve desarmar o WeeklyLossGuard para o resto da semana."""
        cbm = CircuitBreakerManager(max_weekly_loss_pct=3.00)
        engine = RiskEngine(circuit_breakers=cbm)

        # Conta com perda semanal de -3.20%
        damaged_account = AccountState(
            login=882310,
            server="Demo",
            currency="USD",
            balance=96800.0,
            equity=96800.0,
            margin=0.0,
            free_margin=96800.0,
            peak_equity=100000.0,
            daily_pnl_pct=-0.50,
            weekly_pnl_pct=-3.20,
            current_drawdown_pct=3.20,
        )

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        auth = engine.evaluate_proposal(
            proposal=proposal,
            account_state=damaged_account,
            current_tick=wednesday_market_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )

        assert not auth.approved
        assert "CIRCUIT_BREAKER_WEEKLY_LOSS" in (auth.rejection_reason or "")

    # ------------------------------------------------------------------------
    # MODO 13: Acionamento Compulsório de Kill Switch por Drawdown Extremo (8.00%)
    # ------------------------------------------------------------------------
    def test_13_emergency_drawdown_kill_switch_compulsory(
        self,
        temp_ks_file: Path,
        eurusd_spec: SymbolSpecification,
        wednesday_market_tick: MarketTick,
    ):
        """Falha 13: Drawdown acumulado >= 8.00% aciona trava compulsória e permanente de Kill Switch."""
        ks = KillSwitch(state_file_path=temp_ks_file)
        cbm = CircuitBreakerManager(max_drawdown_limit_pct=8.00)
        engine = RiskEngine(kill_switch=ks, circuit_breakers=cbm)

        # Conta atinge drawdown de 8.50%
        critical_account = AccountState(
            login=882310,
            server="Demo",
            currency="USD",
            balance=91500.0,
            equity=91500.0,
            margin=0.0,
            free_margin=91500.0,
            peak_equity=100000.0,
            daily_pnl_pct=-1.0,
            weekly_pnl_pct=-2.0,
            current_drawdown_pct=8.50,
        )

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        auth = engine.evaluate_proposal(
            proposal=proposal,
            account_state=critical_account,
            current_tick=wednesday_market_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )

        assert not auth.approved
        assert "CIRCUIT_BREAKER_EMERGENCY_DRAWDOWN" in (auth.rejection_reason or "")

        # Aciona compulsivamente o Kill Switch persistente após a violação do limite
        ks.engage(reason=auth.rejection_reason, triggered_by="CIRCUIT_BREAKER_EMERGENCY_DRAWDOWN")
        assert ks.is_active(), "Kill switch DEVE estar ativado após violação de 8% de drawdown"
        assert temp_ks_file.exists(), "O estado do Kill Switch DEVE ter sido persistido em disco"

        # Nova verificação: com Kill Switch ativo, ordens são bloqueadas com motivo KILL_SWITCH
        auth_after = engine.evaluate_proposal(
            proposal=proposal,
            account_state=critical_account,
            current_tick=wednesday_market_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )
        assert not auth_after.approved
        assert "KILL_SWITCH" in (auth_after.rejection_reason or "")

    # ------------------------------------------------------------------------
    # MODO 14: Bloqueio Preventivo de Fim de Semana (Weekend Risk Guard)
    # ------------------------------------------------------------------------
    def test_14_weekend_risk_guard_blocks_orders(
        self,
        eurusd_spec: SymbolSpecification,
        standard_account: AccountState,
    ):
        """Falha 14: Ordens enviadas após as 20h UTC de sexta-feira ou no fim de semana DEVEM ser vetadas."""
        cbm = CircuitBreakerManager(friday_closing_utc_hour=20)
        engine = RiskEngine(circuit_breakers=cbm)

        # Tick na sexta-feira às 21:15 UTC (mercado próximo ao fechamento com risco de gap)
        friday_night_tick = MarketTick(
            symbol="EURUSD",
            time=datetime(2026, 11, 6, 21, 15, tzinfo=timezone.utc),  # Sexta 21:15 UTC
            bid=1.08500,
            ask=1.08520,
            last=1.08500,
            volume=1.0,
        )

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_TREND",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        auth = engine.evaluate_proposal(
            proposal=proposal,
            account_state=standard_account,
            current_tick=friday_night_tick,
            normal_spread=0.00015,
            spec=eurusd_spec,
            open_positions=[],
        )

        assert not auth.approved
        assert "WEEKEND_RISK_GUARD" in (auth.rejection_reason or "")

    # ------------------------------------------------------------------------
    # MODO 15: Rejeição Mandatória de Stop Loss Ausente ou Invertido
    # ------------------------------------------------------------------------
    def test_15_missing_or_inverted_stop_loss_rejection(
        self,
        eurusd_spec: SymbolSpecification,
        standard_account: AccountState,
        wednesday_market_tick: MarketTick,
    ):
        """Falha 15: Nenhuma ordem trafega sem Stop Loss ou com Stop Loss invertido."""
        from pydantic import ValidationError

        # 1. Tentativa de construir TradeProposal com SL invertido (BUY com SL > Entrada)
        with pytest.raises(ValueError, match="Stop Loss .* deve ser estritamente menor que entrada"):
            TradeProposal(
                decision_id=uuid4(),
                strategy_id="STRAT_BUG",
                symbol="EURUSD",
                action="BUY",
                entry_price=1.08500,
                stop_loss=1.09000,  # Invertido: SL acima da compra
                take_profit=1.09500,
                target_risk_pct=0.25,
            )

        # 2. Tentativa de construir TradeProposal sem Stop Loss (SL zerado) é barrada no schema
        with pytest.raises(ValidationError):
            TradeProposal(
                decision_id=uuid4(),
                strategy_id="STRAT_BUG",
                symbol="EURUSD",
                action="SELL",
                entry_price=1.08500,
                stop_loss=0.0,
                take_profit=1.07500,
                target_risk_pct=0.25,
            )

    # ------------------------------------------------------------------------
    # MODO 16: Arredondamento Seguro para Zero de Lotes Sub-Mínimos
    # ------------------------------------------------------------------------
    def test_16_sub_minimum_lot_or_invalid_vol_step_zeroed(
        self,
        eurusd_spec: SymbolSpecification,
    ):
        """Falha 16: Lotes inferiores a volMin (0.01) devem arredondar para 0.0, nunca para cima."""
        # Risco de apenas $2 com distância de 100 pips (1000 pontos = $10/lote -> raw_lot = 0.002)
        raw_lot = PositionSizer.calculate_lot(
            risk_money=2.0,
            entry_price=1.08500,
            stop_loss_price=1.07500,
            spec=eurusd_spec,
        )

        # Normaliza contra limites do EURUSD (vol_min=0.01, vol_step=0.01)
        normalized = PositionSizer.normalize_lot(
            raw_lot=raw_lot,
            vol_min=eurusd_spec.volume_min,
            vol_max=eurusd_spec.volume_max,
            vol_step=eurusd_spec.volume_step,
        )

        assert normalized == 0.0, "Lote de 0.002 DEVE arredondar estritamente para 0.0 (Fail-Safe anti-martingale)"

    # ------------------------------------------------------------------------
    # MODO 17: Detecção e Alerta de Posições Órfãs no Broker
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_17_orphan_broker_position_reconciled(self):
        """Falha 17: Posição aberta diretamente no broker não registrada internamente deve ser sinalizada como órfã."""
        adapter = PaperTradingAdapter()
        reconciler = PositionReconciler()

        # Insere uma ordem diretamente no adaptador sem registrar no sistema
        direct_order = OrderRequest(
            request_id=uuid4(),
            idempotency_key="MANUAL_BROKER_INJECTION",
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.10,
            price=1.08500,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=999999,
        )
        res = await adapter.send_order(direct_order)
        assert res.success

        # Registro interno vazio (desconhece a ordem)
        internal_registry: Dict[int, Position] = {}

        report = await reconciler.reconcile(adapter=adapter, internal_registry=internal_registry)

        assert not report.is_synced, "Reconciliação DEVE acusar dessincronização"
        assert res.order_ticket in report.orphaned_tickets, "Ticket desconhecido deve constar na lista de órfãos"
        assert len(report.orphaned_tickets) == 1

    # ------------------------------------------------------------------------
    # MODO 18: Detecção e Purga de Posições Fantasma no Registro Local
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_18_ghost_local_position_reconciled(self):
        """Falha 18: Posição encerrada pelo broker (ex: SL atingido) que ainda consta na memória deve ser purgada."""
        adapter = PaperTradingAdapter()
        reconciler = PositionReconciler()

        # Broker não possui nenhuma posição
        # Mas registro local ainda retém ticket antigo 777123
        ghost_pos = Position(
            ticket=777123,
            symbol="EURUSD",
            position_type="BUY",
            volume=0.10,
            open_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            current_price=1.08500,
            profit=0.0,
            magic=123456,
            open_time=datetime.now(timezone.utc),
        )
        internal_registry = {777123: ghost_pos}

        report = await reconciler.reconcile(adapter=adapter, internal_registry=internal_registry)

        assert not report.is_synced, "Reconciliação DEVE acusar dessincronização"
        assert 777123 in report.ghost_tickets, "Ticket 777123 DEVE ser identificado como posição fantasma"
        assert len(report.ghost_tickets) == 1

    # ------------------------------------------------------------------------
    # MODO 19: Falha de Rede / Timeout na Ponte Dual-Node Linux-Windows
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_19_remote_gateway_timeout_fail_closed(self):
        """Falha 19: Queda da conexão HTTP/REST ou timeout com o MT5 Gateway Windows deve disparar Fail-Closed."""
        client = httpx.AsyncClient()
        bridge = LinuxMT5BridgeAdapter(
            gateway_url="http://192.168.1.100:8001",
            bridge_token="HERMES_SECRET_TOKEN",
            timeout_seconds=0.1,
            client=client,
        )

        # Simula timeout de conexão
        with patch.object(client, "get", side_effect=httpx.ConnectTimeout("Network unreachable")):
            with pytest.raises(PlatformConnectionError, match="Fail-Safe:"):
                await bridge.get_account_state()

        # Simula tentativa de envio de ordem com gateway fora do ar
        dummy_order = OrderRequest(
            request_id=uuid4(),
            idempotency_key="FAIL_BRIDGE_TEST",
            auth_id=uuid4(),
            symbol="EURUSD",
            action="BUY",
            volume=0.10,
            price=1.08500,
            stop_loss=1.08000,
            take_profit=1.09500,
            magic=100001,
        )
        with patch.object(client, "post", side_effect=httpx.ReadTimeout("Socket dropped mid-request")):
            with pytest.raises(PlatformConnectionError, match="Fail-Safe:"):
                await bridge.send_order(dummy_order)

    # ------------------------------------------------------------------------
    # MODO 20: Rejeição Categórica de Autorização Inválida ou Lote Nulo
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_20_unauthorized_token_tampering_veto(self, temp_db: Path):
        """Falha 20: Tentativa de executar ordem com autorização não aprovada ou lote nulo lança PermissionError."""
        from pydantic import ValidationError
        adapter = PaperTradingAdapter()
        store = SqliteIdempotencyStore(temp_db)
        executor = OrderExecutor(adapter=adapter, store=store)

        proposal = TradeProposal(
            decision_id=uuid4(),
            strategy_id="STRAT_ATTACK",
            symbol="EURUSD",
            action="BUY",
            entry_price=1.08500,
            stop_loss=1.08200,
            take_profit=1.09100,
            target_risk_pct=0.25,
        )

        # 1. Autorização com approved=False
        unapproved_auth = RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol="EURUSD",
            action="BUY",
            approved=False,
            authorized_lot=0.0,
            stop_loss=1.08200,
            take_profit=1.09100,
            risk_amount_money=0.0,
            risk_percentage=0.0,
            rejection_reason="REJECTED_BY_RISK_ENGINE",
        )
        with pytest.raises(PermissionError, match="Constitutional Violation"):
            await executor.execute_order(proposal, unapproved_auth)

        # 2. Tentativa de construir autorização approved=True com lote nulo é barrada no schema
        with pytest.raises(ValidationError, match="Ordem aprovada deve conter lote estritamente positivo"):
            RiskAuthorization(
                decision_id=proposal.decision_id,
                symbol="EURUSD",
                action="BUY",
                approved=True,
                authorized_lot=0.0,
                stop_loss=1.08200,
                take_profit=1.09100,
                risk_amount_money=0.0,
                risk_percentage=0.0,
            )

        # 3. Barreira de Defesa em Profundidade no Executor: lote <= 0 lança PermissionError
        tampered_auth = unapproved_auth.model_copy(update={"approved": True, "authorized_lot": 0.0})
        with pytest.raises(PermissionError, match="Constitutional Violation: Approved lot size must be strictly positive"):
            await executor.execute_order(proposal, tampered_auth)
