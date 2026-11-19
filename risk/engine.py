"""
QUANT HERMES — Motor Soberano de Gestão de Risco (Risk Engine)
Módulo: risk.engine
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from core.logger import get_logger
from core.models.market import MarketTick, SymbolSpecification
from core.models.risk import (
    AccountState,
    Position,
    RiskAuthorization,
    TradeProposal,
)
from risk.circuit_breakers import CircuitBreakerManager
from risk.kill_switch import KillSwitch
from risk.position_sizer import PositionSizer

logger = get_logger("risk.engine")


class RiskEngine:
    """
    Autoridade soberana de risco do QUANT HERMES.
    Princípio Fundamental:
        Nenhum agente, modelo de Machine Learning ou LLM poderá jamais alterar
        seus próprios limites financeiros, afrouxar parâmetros de risco ou despachar
        ordens diretamente para o mercado.

    Apenas o Risk Engine tem competência para emitir 'RiskAuthorization' aprovada.
    """

    def __init__(
        self,
        kill_switch: Optional[KillSwitch] = None,
        circuit_breakers: Optional[CircuitBreakerManager] = None,
        default_risk_percentage: float = 0.25,
        max_risk_percentage_hard_cap: float = 0.50,
        max_aggregate_open_risk_pct: float = 1.00,
        max_open_positions: int = 3,
        max_positions_per_symbol: int = 1,
        max_spread_multiplier: float = 2.0,
        require_stop_loss: bool = True,
        max_margin_usage_pct: float = 20.0,
        stop_out_level_pct: float = 30.0,
    ):
        # Pisos invioláveis (_HARDCODED_FLOOR)
        if max_risk_percentage_hard_cap > 0.50:
            raise ValueError(f"max_risk_percentage_hard_cap ({max_risk_percentage_hard_cap}%) excede o piso inviolável de 0.50%")
        if max_aggregate_open_risk_pct > 1.00:
            raise ValueError(f"max_aggregate_open_risk_pct ({max_aggregate_open_risk_pct}%) excede o piso inviolável de 1.00%")
        if not require_stop_loss:
            raise ValueError("require_stop_loss não pode ser desativado")

        self.kill_switch = kill_switch or KillSwitch()
        self.circuit_breakers = circuit_breakers or CircuitBreakerManager()
        self.default_risk_percentage = default_risk_percentage
        self.max_risk_percentage_hard_cap = max_risk_percentage_hard_cap
        self.max_aggregate_open_risk_pct = max_aggregate_open_risk_pct
        self.max_open_positions = max_open_positions
        self.max_positions_per_symbol = max_positions_per_symbol
        self.max_spread_multiplier = max_spread_multiplier
        self.require_stop_loss = require_stop_loss
        self.max_margin_usage_pct = max_margin_usage_pct
        self.stop_out_level_pct = stop_out_level_pct

    def calculate_current_open_risk_pct(
        self,
        open_positions: List[Position],
        specs: dict[str, SymbolSpecification],
        equity: float,
    ) -> float:
        """
        Calcula o risco financeiro acumulado de todas as posições atualmente em aberto.
        Fórmula: soma( (abs(open_price - sl) / tick_size) * tick_value * volume ) / equity * 100
        """
        if equity <= 0.0 or not open_positions:
            return 0.0

        total_risk_money = 0.0
        for pos in open_positions:
            spec = specs.get(pos.symbol)
            if not spec or spec.tick_size <= 0.0:
                continue

            sl_distance = abs(pos.open_price - pos.stop_loss)
            pos_risk_money = (sl_distance / spec.tick_size) * spec.tick_value * pos.volume
            total_risk_money += pos_risk_money

        return round((total_risk_money / equity) * 100.0, 4)

    def assess_margin(
        self,
        account_state: AccountState,
        margin_required: Optional[float],
        max_margin_usage_pct: Optional[float] = None,
        stop_out_level_pct: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Checagem pré-ordem. margin_required vem de order_calc_margin / order_check.
        Rejeita se a margem livre não cobre a ordem, se o uso projetado passa do teto
        ou se o nível de margem ficaria no stop-out (30% na ProCent) ou abaixo dele.
        """
        if margin_required is None:
            return True, None
        if margin_required < 0.0:
            return False, "MARGIN: margem requerida inválida"

        usage_cap = max_margin_usage_pct if max_margin_usage_pct is not None else self.max_margin_usage_pct
        stop_out = stop_out_level_pct if stop_out_level_pct is not None else self.stop_out_level_pct

        if account_state.free_margin + 1e-9 < margin_required:
            return False, (
                f"MARGIN: margem livre ({account_state.free_margin:.2f}) "
                f"menor que a requerida ({margin_required:.2f})"
            )

        if account_state.equity <= 0.0:
            return False, "MARGIN: equity não positiva"

        projected_margin = account_state.margin + margin_required
        usage_pct = (projected_margin / account_state.equity) * 100.0
        if usage_pct > usage_cap:
            return False, (
                f"MARGIN: uso projetado ({usage_pct:.2f}%) excede o teto configurado ({usage_cap:.2f}%)"
            )

        if projected_margin > 0.0:
            margin_level = (account_state.equity / projected_margin) * 100.0
            if margin_level <= stop_out:
                return False, (
                    f"MARGIN: nível projetado ({margin_level:.2f}%) no stop-out ou abaixo ({stop_out:.2f}%)"
                )
        return True, None

    def evaluate_proposal(
        self,
        proposal: TradeProposal,
        account_state: Optional[AccountState],
        current_tick: Optional[MarketTick],
        normal_spread: Optional[float],
        spec: SymbolSpecification,
        open_positions: List[Position],
        known_specs: Optional[dict[str, SymbolSpecification]] = None,
        margin_required: Optional[float] = None,
        config_min_volume: Optional[float] = None,
    ) -> RiskAuthorization:
        """
        Avaliação soberana da proposta de operação em rigorosa sequência de segurança.
        """
        rejection_kwargs = {
            "decision_id": proposal.decision_id,
            "symbol": proposal.symbol,
            "action": proposal.action,
            "approved": False,
            "authorized_lot": 0.0,
            "stop_loss": proposal.stop_loss,
            "take_profit": proposal.take_profit,
            "risk_amount_money": 0.0,
            "risk_percentage": 0.0,
        }

        # 1. FAIL-SAFE: Verificação de telemetria da conta
        if account_state is None or account_state.equity <= 0.0:
            logger.error("risk_evaluation_rejected_null_account_state", proposal_id=str(proposal.proposal_id))
            return RiskAuthorization(
                **rejection_kwargs,
                rejection_reason="FAIL_SAFE: Estado da conta indisponível ou patrimônio não positivo",
            )

        # 2. KILL SWITCH: Trava de emergência global
        if self.kill_switch.is_active():
            logger.critical("risk_evaluation_rejected_kill_switch_active", reason=self.kill_switch.reason)
            return RiskAuthorization(
                **rejection_kwargs,
                rejection_reason=f"KILL_SWITCH: Sistema em trava de emergência ({self.kill_switch.reason})",
            )

        # 3. CIRCUIT BREAKERS: Perda diária, semanal, drawdown catastrófico, fim de semana
        current_time = current_tick.time if current_tick else None
        breakers_ok, breaker_reason = self.circuit_breakers.check_all(account_state, current_time=current_time)
        if not breakers_ok:
            logger.warning("risk_evaluation_rejected_circuit_breaker", reason=breaker_reason)
            return RiskAuthorization(**rejection_kwargs, rejection_reason=breaker_reason)

        # 4. LIMITES DE QUANTIDADE DE POSIÇÕES ABERTAS
        if len(open_positions) >= self.max_open_positions:
            reason = f"MAX_POSITIONS_LIMIT: Limite total atingido ({len(open_positions)}/{self.max_open_positions})"
            logger.warning("risk_evaluation_rejected_max_positions", reason=reason)
            return RiskAuthorization(**rejection_kwargs, rejection_reason=reason)

        symbol_positions = [p for p in open_positions if p.symbol == proposal.symbol]
        if len(symbol_positions) >= self.max_positions_per_symbol:
            reason = f"SYMBOL_POSITION_LIMIT: Já existe {len(symbol_positions)} posição em {proposal.symbol} (máx {self.max_positions_per_symbol})"
            logger.warning("risk_evaluation_rejected_symbol_position_limit", reason=reason)
            return RiskAuthorization(**rejection_kwargs, rejection_reason=reason)

        # 5. STOP LOSS MANDATÓRIO
        if self.require_stop_loss and proposal.stop_loss <= 0.0:
            reason = "MANDATORY_STOP_LOSS: Proposta sem Stop Loss numérico válido"
            logger.error("risk_evaluation_rejected_missing_stop_loss", reason=reason)
            return RiskAuthorization(**rejection_kwargs, rejection_reason=reason)

        # 6. FILTRO DE SPREAD ANÔMALO
        if current_tick is not None and normal_spread is not None and normal_spread > 0.0:
            if current_tick.spread > normal_spread * self.max_spread_multiplier:
                reason = (
                    f"SPREAD_ANOMALY: Spread atual ({current_tick.spread:.5f}) excede "
                    f"{self.max_spread_multiplier}x a média ({normal_spread:.5f})"
                )
                logger.warning("risk_evaluation_rejected_spread_anomaly", reason=reason)
                return RiskAuthorization(**rejection_kwargs, rejection_reason=reason)

        # 7. RISCO AGREGADO EM ABERTO
        specs_map = known_specs or {proposal.symbol: spec}
        if proposal.symbol not in specs_map:
            specs_map[proposal.symbol] = spec

        current_open_risk_pct = self.calculate_current_open_risk_pct(
            open_positions=open_positions,
            specs=specs_map,
            equity=account_state.equity,
        )

        remaining_risk_budget = self.max_aggregate_open_risk_pct - current_open_risk_pct
        if remaining_risk_budget <= 0.01:
            reason = (
                f"AGGREGATE_RISK_LIMIT: Risco aberto acumulado ({current_open_risk_pct:.2f}%) "
                f"atingiu o teto ({self.max_aggregate_open_risk_pct:.2f}%)"
            )
            logger.warning("risk_evaluation_rejected_aggregate_risk", reason=reason)
            return RiskAuthorization(**rejection_kwargs, rejection_reason=reason)

        # 8. MARGEM PRÉ-TRADE (order_calc_margin / margem livre)
        margin_ok, margin_reason = self.assess_margin(account_state, margin_required)
        if not margin_ok:
            logger.warning("risk_evaluation_rejected_margin", reason=margin_reason)
            return RiskAuthorization(**rejection_kwargs, rejection_reason=margin_reason)

        # 9. DIMENSIONAMENTO DE RISCO E LOTE
        # O risco da proposta é limitado pelo hard cap e pelo orçamento restante
        allocated_risk_pct = min(
            proposal.target_risk_pct,
            self.max_risk_percentage_hard_cap,
            remaining_risk_budget,
        )
        allocated_risk_pct = round(allocated_risk_pct, 4)
        risk_money = account_state.equity * (allocated_risk_pct / 100.0)

        lot = PositionSizer.calculate_lot(
            risk_money=risk_money,
            entry_price=proposal.entry_price,
            stop_loss_price=proposal.stop_loss,
            spec=spec,
            direction=proposal.action,
            config_min_volume=config_min_volume,
        )

        if lot <= 0.0:
            reason = (
                f"POSITION_SIZER: Lote calculado para risco de ${risk_money:.2f} "
                f"é inferior ao volume mínimo permitido ({spec.volume_min})"
            )
            logger.warning("risk_evaluation_rejected_lot_below_min", reason=reason)
            return RiskAuthorization(**rejection_kwargs, rejection_reason=reason)

        # 10. APROVAÇÃO SOBERANA
        logger.info(
            "RISK_AUTHORIZATION_APPROVED",
            symbol=proposal.symbol,
            action=proposal.action,
            lot=lot,
            risk_pct=allocated_risk_pct,
            risk_money=round(risk_money, 2),
        )

        return RiskAuthorization(
            decision_id=proposal.decision_id,
            symbol=proposal.symbol,
            action=proposal.action,
            approved=True,
            authorized_lot=lot,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            risk_amount_money=round(risk_money, 2),
            risk_percentage=allocated_risk_pct,
            max_slippage_points=proposal.max_slippage_points,
            rejection_reason=None,
        )

