"""
QUANT HERMES — Modelos de Risco, Contas e Execução
Módulo: core.models.risk
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from typing_extensions import Self
from uuid import UUID, uuid4
from pydantic import Field, model_validator
from core.models.base import HermesBaseModel, utc_now


class AccountState(HermesBaseModel):
    """Estado financeiro da conta de trading emitido pelo broker."""

    login: int = Field(..., gt=0, description="Número de login da conta MT5")
    server: str = Field(..., description="Nome do servidor da corretora")
    currency: str = Field(default="USD", description="Moeda base da conta")
    balance: float = Field(..., ge=0.0, description="Saldo financeiro fechado")
    equity: float = Field(..., ge=0.0, description="Patrimônio líquido em tempo real")
    margin: float = Field(default=0.0, ge=0.0, description="Margem utilizada")
    free_margin: float = Field(..., description="Margem livre disponível")
    margin_level: float = Field(default=0.0, ge=0.0, description="Nível de margem percentual")
    leverage: int = Field(default=100, gt=0, description="Alavancagem da conta")
    daily_pnl_pct: float = Field(default=0.0, description="Resultado percentual do dia atual")
    weekly_pnl_pct: float = Field(default=0.0, description="Resultado percentual da semana")
    peak_equity: float = Field(..., ge=0.0, description="Pico histórico de equity")
    current_drawdown_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Drawdown percentual atual")
    timestamp: datetime = Field(default_factory=utc_now, description="Timestamp da telemetria")


class Position(HermesBaseModel):
    """Posição aberta no terminal MT5."""

    ticket: int = Field(..., gt=0, description="Ticket exclusivo da posição no MT5")
    symbol: str = Field(..., description="Instrumento da posição")
    magic: int = Field(..., description="Magic Number identificador da estratégia/agente")
    position_type: Literal["BUY", "SELL"] = Field(..., description="Tipo da posição")
    volume: float = Field(..., gt=0.0, description="Volume em lotes")
    open_price: float = Field(..., gt=0.0, description="Preço de abertura")
    stop_loss: float = Field(..., gt=0.0, description="Nível de Stop Loss")
    take_profit: float = Field(default=0.0, ge=0.0, description="Nível de Take Profit")
    current_price: float = Field(..., gt=0.0, description="Preço de mercado atual")
    profit: float = Field(default=0.0, description="Lucro/prejuízo flutuante na moeda da conta")
    swap: float = Field(default=0.0, description="Swap acumulado")
    comment: str = Field(default="", description="Comentário da posição")
    open_time: datetime = Field(..., description="Data/hora de abertura")


class RiskAuthorization(HermesBaseModel):
    """Autorização soberana e irrevogável emitida pelo Risk Engine."""

    auth_id: UUID = Field(default_factory=uuid4, description="ID exclusivo de autorização")
    decision_id: UUID = Field(..., description="ID da decisão de consenso correspondente")
    timestamp: datetime = Field(default_factory=utc_now)
    symbol: str = Field(..., description="Instrumento")
    action: Literal["BUY", "SELL"] = Field(..., description="Direção autorizada")
    approved: bool = Field(..., description="Status de aprovação soberana do Risk Engine")
    authorized_lot: float = Field(default=0.0, ge=0.0, description="Volume normalizado aprovado")
    stop_loss: float = Field(..., gt=0.0, description="Stop Loss numérico obrigatório")
    take_profit: float = Field(default=0.0, ge=0.0, description="Take Profit numérico")
    risk_amount_money: float = Field(default=0.0, ge=0.0, description="Valor monetário em risco na operação")
    risk_percentage: float = Field(default=0.0, ge=0.0, le=0.50, description="Percentual de risco (máx 0.50%)")
    max_slippage_points: int = Field(default=30, ge=1, description="Desvio máximo aceitável em pontos")
    rejection_reason: str | None = Field(default=None, description="Motivo caso a operação seja rejeitada")

    @model_validator(mode="after")
    def validate_approval_consistency(self) -> Self:
        if self.approved:
            if self.authorized_lot <= 0.0:
                raise ValueError("Ordem aprovada deve conter lote estritamente positivo")
            if self.stop_loss <= 0.0:
                raise ValueError("Ordem aprovada DEVE conter Stop Loss numérico maior que zero")
            if self.rejection_reason is not None:
                raise ValueError(f"Ordem aprovada não pode conter rejection_reason: '{self.rejection_reason}'")
        return self


class OrderRequest(HermesBaseModel):
    """Solicitação formal de envio de ordem para o Execution Engine."""

    request_id: UUID = Field(default_factory=uuid4, description="ID único da solicitação")
    auth_id: UUID = Field(..., description="ID da autorização do Risk Engine vinculada")
    symbol: str = Field(..., description="Símbolo oficial do broker")
    action: Literal["BUY", "SELL"] = Field(..., description="Direção da ordem")
    volume: float = Field(..., gt=0.0, description="Lote aprovado a negociar")
    price: float = Field(..., gt=0.0, description="Preço de referência para execução")
    stop_loss: float = Field(..., gt=0.0, description="Preço exato do Stop Loss")
    take_profit: float = Field(default=0.0, ge=0.0, description="Preço do Take Profit")
    slippage_points: int = Field(default=30, ge=0, description="Desvio tolerado de preço")
    magic: int = Field(..., gt=0, description="Magic Number identificador")
    comment: str = Field(default="HERMES_AUTO", description="Comentário rastreável")
    filling_mode: Literal["FOK", "IOC", "RETURN"] = Field(default="IOC")
    idempotency_key: str = Field(..., description="Chave de idempotência anti-duplicação")
    timestamp: datetime = Field(default_factory=utc_now)


class TradeProposal(HermesBaseModel):
    """Proposta de operação estruturada pelo Portfolio Manager para avaliação soberana do Risk Engine."""

    proposal_id: UUID = Field(default_factory=uuid4, description="ID exclusivo da proposta")
    decision_id: UUID = Field(..., description="ID da decisão de consenso vinculada")
    strategy_id: str = Field(..., description="Identificador da estratégia (ex: STRAT_MOMENTUM_XAUUSD)")
    symbol: str = Field(..., description="Instrumento financeiro (ex: EURUSD, XAUUSD)")
    action: Literal["BUY", "SELL"] = Field(..., description="Direção da operação proposta")
    entry_price: float = Field(..., gt=0.0, description="Preço de referência para entrada")
    stop_loss: float = Field(..., gt=0.0, description="Preço mandatório do Stop Loss")
    take_profit: float = Field(default=0.0, ge=0.0, description="Preço do Take Profit")
    target_risk_pct: float = Field(default=0.25, gt=0.0, le=0.50, description="Risco percentual pretendido (máx 0.50%)")
    max_slippage_points: int = Field(default=30, ge=1, description="Tolerância de slippage em pontos")
    magic: int = Field(default=100001, gt=0, description="Magic Number identificador")
    comment: str = Field(default="HERMES_PROP", description="Comentário rastreável")
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_proposal_coherence(self) -> Self:
        if self.action == "BUY" and self.stop_loss >= self.entry_price:
            raise ValueError(
                f"Proposta BUY inválida: Stop Loss ({self.stop_loss}) deve ser estritamente menor que entrada ({self.entry_price})"
            )
        if self.action == "SELL" and self.stop_loss <= self.entry_price:
            raise ValueError(
                f"Proposta SELL inválida: Stop Loss ({self.stop_loss}) deve ser estritamente maior que entrada ({self.entry_price})"
            )
        return self


class OrderResult(HermesBaseModel):
    """Resultado da execução de ordem retornado pelo terminal ou corretora."""

    request_id: UUID = Field(..., description="ID da solicitação correspondente")
    idempotency_key: str = Field(..., description="Chave de idempotência da solicitação")
    success: bool = Field(..., description="Status de execução com sucesso")
    retcode: int = Field(..., description="Código de retorno da corretora (ex: 10009 para OK)")
    order_ticket: int = Field(default=0, ge=0, description="Ticket da ordem gerada")
    deal_ticket: int = Field(default=0, ge=0, description="Ticket do negócio (deal) gerado")
    volume_executed: float = Field(default=0.0, ge=0.0, description="Lote efetivamente preenchido")
    price_executed: float = Field(default=0.0, ge=0.0, description="Preço médio de preenchimento")
    comment: str = Field(default="", description="Mensagem de retorno do broker")
    timestamp: datetime = Field(default_factory=utc_now)
