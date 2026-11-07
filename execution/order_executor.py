"""
QUANT HERMES — EXECUTOR SOBERANO DE ORDENS
Módulo: execution.order_executor

Responsabilidade:
- Garantir a separação inviolável entre autorização de risco e despacho físico de ordens.
- Bloquear incondicionalmente qualquer solicitação sem RiskAuthorization aprovada.
- Aplicar idempotência estrita para prevenção de ordens duplicadas.
- Rastrear e auditar todas as tentativas de execução.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Set
from uuid import UUID, uuid4

from core.logger import get_logger
from core.models.risk import OrderRequest, OrderResult, RiskAuthorization, TradeProposal
from execution.adapters.base import TradingPlatformAdapter

logger = get_logger("order_executor")


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
    ) -> None:
        self.adapter = adapter
        self.idempotency_window_seconds = idempotency_window_seconds
        self._processed_idempotency_keys: Dict[str, float] = {}
        self._execution_history: list[OrderResult] = []

    async def execute_order(
        self,
        proposal: TradeProposal,
        risk_auth: RiskAuthorization,
    ) -> OrderResult:
        """
        Executa a ordem no broker/simulador após validação formal e estrita da autorização de risco.
        Dispara PermissionError caso receba autorização negada ou incoerente.
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

        # 3. Idempotência Anti-Duplicação
        now_ts = datetime.now(timezone.utc).timestamp()
        idempotency_key = f"{proposal.symbol}_{proposal.action}_{risk_auth.auth_id}"

        # Limpa chaves expiradas
        self._cleanup_expired_idempotency_keys(now_ts)

        if idempotency_key in self._processed_idempotency_keys:
            logger.warning(
                "Execução bloqueada por idempotência: ordem idêntica enviada recentemente",
                extra={"idempotency_key": idempotency_key, "symbol": proposal.symbol},
            )
            return OrderResult(
                request_id=uuid4(),
                idempotency_key=idempotency_key,
                success=False,
                retcode=10027,  # MT5 RET_TRADE_DISABLED ou duplicate
                comment="DUPLICATE_ORDER_BLOCKED_BY_IDEMPOTENCY",
            )

        # 4. Construção da Solicitação Formal de Ordem (OrderRequest)
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
            "Despachando ordem autorizada para a plataforma",
            extra={
                "symbol": order_req.symbol,
                "action": order_req.action,
                "volume": order_req.volume,
                "sl": order_req.stop_loss,
                "tp": order_req.take_profit,
                "auth_id": str(risk_auth.auth_id),
            },
        )

        # 5. Envio físico ao Adapter (trata assíncrono ou síncrono)
        send_call = self.adapter.send_order(order_req)
        if asyncio.iscoroutine(send_call):
            result = await send_call
        else:
            result = send_call

        # Registra chave de idempotência se a tentativa foi concluída
        self._processed_idempotency_keys[idempotency_key] = now_ts
        self._execution_history.append(result)

        if result.success:
            logger.info(
                "Ordem EXECUTADA COM SUCESSO na plataforma",
                extra={
                    "order_ticket": result.order_ticket,
                    "volume": result.volume_executed,
                    "price": result.price_executed,
                    "symbol": order_req.symbol,
                },
            )
        else:
            logger.error(
                "Falha na execução da ordem pela plataforma",
                extra={
                    "retcode": result.retcode,
                    "comment": result.comment,
                    "symbol": order_req.symbol,
                },
            )

        return result

    def _cleanup_expired_idempotency_keys(self, current_ts: float) -> None:
        """Remove chaves de idempotência mais antigas que a janela configurada."""
        expired = [
            k for k, ts in self._processed_idempotency_keys.items()
            if current_ts - ts > self.idempotency_window_seconds
        ]
        for k in expired:
            del self._processed_idempotency_keys[k]

    def get_execution_history(self) -> list[OrderResult]:
        """Retorna histórico de ordens executadas."""
        return list(self._execution_history)
