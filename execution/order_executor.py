"""
QUANT HERMES — EXECUTOR SOBERANO DE ORDENS COM IDEMPOTÊNCIA PERSISTENTE
Módulo: execution.order_executor

Responsabilidade:
- Garantir a separação inviolável entre autorização de risco e despacho físico de ordens.
- Bloquear incondicionalmente qualquer solicitação sem RiskAuthorization aprovada.
- Aplicar idempotência persistente (SqliteIdempotencyStore) contra duplicidade em crashes e reinicializações.
- Tratar resultados ambíguos de execução via máquina de estados durável (RECONCILIATION_REQUIRED).
- Recuperar e reconciliar operações interrompidas após reinicialização do sistema.
- Rastrear e auditar todas as tentativas de execução em banco de dados SQLite WAL.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from core.logger import get_logger
from core.models.risk import OrderRequest, OrderResult, Position, RiskAuthorization, TradeProposal
from execution.adapters.base import TradingPlatformAdapter
from execution.idempotency import (
    IdempotencyViolationError,
    OrderLifecycleState,
    SqliteIdempotencyStore,
    StoreCorruptedError,
)
from execution.symbols import SymbolMapper

logger = get_logger("execution.order_executor")


class OrderExecutor:
    """
    Componente desacoplado de execução física de ordens.
    Implementa o Princípio Fundamental da Constituição:
    'SOMENTE o Risk Engine, mediante autorização estrita, pode enviar ordens ao Execution Engine.'
    """

    def __init__(
        self,
        adapter: TradingPlatformAdapter,
        idempotency_window_seconds: int = 60,
        store: Optional[SqliteIdempotencyStore] = None,
        symbol_mapper: Optional[SymbolMapper] = None,
    ) -> None:
        self.adapter = adapter
        self.symbol_mapper = symbol_mapper or SymbolMapper()
        self.idempotency_window_seconds = idempotency_window_seconds
        self.store = store or SqliteIdempotencyStore(
            retention_window_seconds=max(86400, idempotency_window_seconds)
        )
        self._execution_history: List[OrderResult] = []

    async def execute_order(
        self,
        proposal: TradeProposal,
        risk_auth: RiskAuthorization,
    ) -> OrderResult:
        """
        Executa a ordem no broker/simulador após validação formal e estrita da autorização de risco.
        Aplica o protocolo transacional de idempotência persistente:
        1. Validação constitucional de risco (Fail-Closed).
        2. Geração da identidade idempotente estável.
        3. Registro durável no SQLite WAL em estado SUBMITTING (antes do socket).
        4. Despacho físico ao broker via Adapter.
        5. Atualização atômica do estado pós-execução (FILLED, PARTIALLY_FILLED, REJECTED, ou RECONCILIATION_REQUIRED).
        """
        # 1. Barreira Constitucional Inviolável: Validação de Aprovação do Risk Engine
        if not risk_auth.approved:
            logger.critical(
                "VIOLAÇÃO DE SEGURANÇA: Tentativa de envio de ordem rejeitada pelo Risk Engine!",
                extra={
                    "proposal_id": str(proposal.proposal_id),
                    "auth_id": str(risk_auth.auth_id),
                    "rejection_reason": risk_auth.rejection_reason,
                },
            )
            raise PermissionError(
                f"Constitutional Violation: Cannot execute unapproved risk authorization: {risk_auth.rejection_reason}"
            )

        if risk_auth.authorized_lot <= 0.0:
            logger.critical(
                "VIOLAÇÃO DE SEGURANÇA: Autorização aprovada com lote nulo ou negativo!",
                extra={"authorized_lot": risk_auth.authorized_lot},
            )
            raise PermissionError(
                f"Constitutional Violation: Approved lot size must be strictly positive, got {risk_auth.authorized_lot}"
            )

        # 2. Validação de Coerência entre Proposta e Autorização
        if proposal.symbol != risk_auth.symbol:
            raise ValueError(
                f"Incoerência de ativo: Proposta ({proposal.symbol}) != Autorização ({risk_auth.symbol})"
            )
        if proposal.action != risk_auth.action:
            raise ValueError(
                f"Incoerência de direção: Proposta ({proposal.action}) != Autorização ({risk_auth.action})"
            )

        # 3. Geração da Identidade Idempotente Estável
        idempotency_key = SqliteIdempotencyStore.generate_idempotency_key(
            symbol=proposal.symbol,
            action=proposal.action,
            strategy_id=proposal.strategy_id,
            decision_id=proposal.decision_id,
            auth_id=risk_auth.auth_id,
        )

        # 4. Registro Transacional Durável no SQLite WAL (Antes de qualquer envio físico ao socket)
        try:
            is_registered = self.store.register_intent_pre_submission(
                intent_id=proposal.proposal_id,
                idempotency_key=idempotency_key,
                decision_id=proposal.decision_id,
                auth_id=risk_auth.auth_id,
                strategy_id=proposal.strategy_id,
                symbol=proposal.symbol,
                action=proposal.action,
                requested_lot=risk_auth.authorized_lot,
                authorized_lot=risk_auth.authorized_lot,
                entry_price=proposal.entry_price,
                stop_loss=risk_auth.stop_loss,
                take_profit=risk_auth.take_profit,
                magic=proposal.magic,
            )
        except Exception as e:
            logger.critical(
                "FALHA NO ARMAZENAMENTO PERSISTENTE (FAIL-CLOSED): Abortando envio de ordem",
                extra={"idempotency_key": idempotency_key, "error": str(e)},
            )
            return OrderResult(
                request_id=uuid4(),
                idempotency_key=idempotency_key,
                success=False,
                retcode=10028,
                comment=f"PERSISTENCE_FAILURE_FAIL_CLOSED: {str(e)}",
            )

        if not is_registered:
            logger.warning(
                "Execução bloqueada por idempotência persistente: ordem idêntica já registrada no banco",
                extra={"idempotency_key": idempotency_key, "symbol": proposal.symbol},
            )
            return OrderResult(
                request_id=uuid4(),
                idempotency_key=idempotency_key,
                success=False,
                retcode=10027,  # RET_TRADE_DISABLED ou duplicate
                comment="DUPLICATE_ORDER_BLOCKED_BY_IDEMPOTENCY",
            )

        # 5. Construção da Solicitação Formal de Ordem (OrderRequest)
        order_req = OrderRequest(
            auth_id=risk_auth.auth_id,
            symbol=risk_auth.symbol,
            action=risk_auth.action,
            volume=risk_auth.authorized_lot,
            price=proposal.entry_price,
            stop_loss=risk_auth.stop_loss,
            take_profit=risk_auth.take_profit,
            slippage_points=risk_auth.max_slippage_points,
            magic=proposal.magic,
            comment=f"H_{proposal.strategy_id[:10]}",
            idempotency_key=idempotency_key,
        )

        logger.info(
            "Despachando ordem autorizada e persistida para a plataforma",
            extra={
                "symbol": order_req.symbol,
                "action": order_req.action,
                "volume": order_req.volume,
                "sl": order_req.stop_loss,
                "tp": order_req.take_profit,
                "auth_id": str(risk_auth.auth_id),
                "idempotency_key": idempotency_key,
            },
        )

        # 6. Envio físico ao Adapter com Tratamento Estrito de Ambiguidade
        try:
            send_call = self.adapter.send_order(order_req)
            if asyncio.iscoroutine(send_call):
                result = await send_call
            else:
                result = send_call
        except Exception as e:
            # FALHA NO SOCKET, TIMEOUT OU EXCEÇÃO NÃO TRATADA
            err_details = f"{type(e).__name__}: {str(e)}"
            logger.critical(
                "FALHA CRÍTICA DE COMUNICAÇÃO NO ENVIO DE ORDEM: Resultado ambíguo, acionando RECONCILIATION_REQUIRED",
                extra={"idempotency_key": idempotency_key, "error": err_details},
            )
            self.store.transition_state(
                idempotency_key=idempotency_key,
                to_state=OrderLifecycleState.RECONCILIATION_REQUIRED,
                reason=f"COMMUNICATION_FAILURE_OR_TIMEOUT: {err_details}",
                last_error=err_details,
            )
            ambiguous_res = OrderResult(
                request_id=order_req.request_id,
                idempotency_key=idempotency_key,
                success=False,
                retcode=10024,
                comment=f"AMBIGUOUS_EXECUTION_RECONCILIATION_REQUIRED: {err_details}",
            )
            self._execution_history.append(ambiguous_res)
            return ambiguous_res

        # 7. Atualização do Estado Pós-Execução na Máquina de Estados
        if result.success and result.order_ticket > 0:
            # Distinção entre execução parcial e total
            if 0.0 < result.volume_executed < risk_auth.authorized_lot:
                target_state = OrderLifecycleState.PARTIALLY_FILLED
                reason = "BROKER_ORDER_PARTIALLY_FILLED"
            else:
                target_state = OrderLifecycleState.FILLED
                reason = "BROKER_ORDER_FULLY_FILLED"

            self.store.transition_state(
                idempotency_key=idempotency_key,
                to_state=target_state,
                reason=reason,
                order_ticket=result.order_ticket,
                deal_ticket=result.deal_ticket,
                volume_executed=result.volume_executed,
                price_executed=result.price_executed,
                retcode=result.retcode,
                broker_comment=result.comment,
            )
            logger.info(
                "Ordem EXECUTADA COM SUCESSO na plataforma e atualizada no store persistente",
                extra={
                    "order_ticket": result.order_ticket,
                    "volume": result.volume_executed,
                    "price": result.price_executed,
                    "symbol": order_req.symbol,
                    "state": target_state.value,
                },
            )
        else:
            self.store.transition_state(
                idempotency_key=idempotency_key,
                to_state=OrderLifecycleState.REJECTED,
                reason=f"BROKER_REJECTION: {result.comment}",
                order_ticket=result.order_ticket,
                retcode=result.retcode,
                broker_comment=result.comment,
                last_error=result.comment,
            )
            logger.error(
                "Falha na execução da ordem pela plataforma e marcada como REJECTED",
                extra={
                    "retcode": result.retcode,
                    "comment": result.comment,
                    "symbol": order_req.symbol,
                },
            )

        self._execution_history.append(result)
        return result

    async def recover_unresolved_orders(self) -> List[Dict[str, Any]]:
        """
        Procedimento de recuperação pós-reinicialização (Crash Recovery Protocol).
        1. Localiza todas as ordens não resolvidas no banco SQLite.
        2. Consulta posições abertas no broker via adapter.
        3. Reconcilia tickets e atualiza o estado de forma auditável.
        """
        unresolved = self.store.get_unresolved_intents()
        if not unresolved:
            logger.info("Nenhuma ordem pendente ou ambígua encontrada no store persistente")
            return []

        logger.warning(
            "RECUPERAÇÃO PÓS-CRASH: Encontradas ordens não resolvidas no store",
            extra={"count": len(unresolved)},
        )

        open_positions = await self.adapter.get_open_positions()

        def _match_position(magic: int, symbol: str):
            logical = self.symbol_mapper.to_logical(symbol)
            for position in open_positions:
                if int(position.magic) != int(magic):
                    continue
                if self.symbol_mapper.same_instrument(position.symbol, logical):
                    return position
            return None

        reconciled_results: List[Dict[str, Any]] = []

        for intent in unresolved:
            key = intent["idempotency_key"]
            magic = intent["magic"]
            sym = intent["symbol"].upper()
            state = intent["state"]

            logger.info(
                "Reconciliando intenção recuperada",
                extra={"idempotency_key": key, "state": state, "symbol": sym, "magic": magic},
            )

            # Magic + símbolo lógico, mesmo quando o broker publica sufixo.
            matched_pos = _match_position(magic, sym)

            if matched_pos is not None:
                # A ordem foi efetivamente aberta no broker antes do crash!
                logger.warning(
                    "SUCESSO NA RECONCILIAÇÃO: Ordem encontrada no broker!",
                    extra={
                        "idempotency_key": key,
                        "broker_ticket": matched_pos.ticket,
                        "volume": matched_pos.volume,
                    },
                )
                self.store.transition_state(
                    idempotency_key=key,
                    to_state=OrderLifecycleState.FILLED,
                    reason="RECONCILED_WITH_BROKER_OPEN_POSITION_ON_STARTUP",
                    order_ticket=matched_pos.ticket,
                    volume_executed=matched_pos.volume,
                    price_executed=matched_pos.open_price,
                )
                reconciled_results.append({
                    "idempotency_key": key,
                    "status": "RECONCILED_FILLED",
                    "ticket": matched_pos.ticket,
                })
            else:
                # Ordem não encontrada nas posições ativas.
                # Marcação segura como RECONCILIATION_REQUIRED para bloquear reenvio cego
                if state != OrderLifecycleState.RECONCILIATION_REQUIRED.value:
                    self.store.transition_state(
                        idempotency_key=key,
                        to_state=OrderLifecycleState.RECONCILIATION_REQUIRED,
                        reason="UNRESOLVED_INTENT_NOT_FOUND_IN_BROKER_POSITIONS",
                    )
                reconciled_results.append({
                    "idempotency_key": key,
                    "status": "MARKED_RECONCILIATION_REQUIRED",
                    "ticket": 0,
                })

        return reconciled_results

    def get_execution_history(self) -> List[OrderResult]:
        """Retorna histórico de ordens executadas nesta sessão em memória."""
        return list(self._execution_history)
