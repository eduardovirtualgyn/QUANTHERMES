"""
QUANT HERMES — AG07: ADVERSARIAL RESEARCH AGENT
Módulo: intelligence.agents.ag07_adversarial
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import numpy as np

from core.logger import get_logger
from core.models.agent import AgentSignal, SignalDirection
from core.models.base import utc_now
from core.models.market import MarketBar, MarketTick, TimeFrame
from data.features.indicators import calc_atr, calc_rsi
from intelligence.agents.base import BaseIntelligenceAgent

logger = get_logger("intelligence.agents.ag07_adversarial")


@dataclass
class AdversarialDebateResult:
    """Resultado da investigação dialética Bull vs Bear do AG07."""
    symbol: str
    bull_arguments: List[str] = field(default_factory=list)
    bear_arguments: List[str] = field(default_factory=list)
    detected_traps: List[str] = field(default_factory=list)
    risk_penalty_factor: float = 0.0  # Penalidade de 0.0 a 0.40 sobre o score de consenso
    veto_flag: bool = False  # Veto total se armadilha crítica for confirmada
    timestamp: datetime = field(default_factory=utc_now)


class AdversarialResearchAgent(BaseIntelligenceAgent):
    """
    AG07 — ADVERSARIAL RESEARCH
    Responsabilidade:
    - Investigação dialética implacável (Advogado do Diabo): confronta a tese compradora e vendedora.
    - Detecção de armadilhas de liquidez (Bull Traps / Bear Traps).
    - Identificação de divergências de exaustão e falsos rompimentos.
    - Cálculo de fator de penalidade de risco (Risk Penalty Factor) aplicado ao Consenso.
    - Em conformidade com ADR-002: funciona via heurísticas quantitativas determinísticas
      desacopladas do loop de baixa latência, suportando enriquecimento assíncrono por LLM.
    """

    def __init__(
        self,
        agent_id: str = "AG07_ADVERSARIAL",
        quality_factor: float = 0.88,
        enable_llm_calls: bool = False,
    ):
        super().__init__(
            agent_id=agent_id,
            name="Adversarial Research Agent",
            quality_factor=quality_factor,
        )
        self.enable_llm_calls = enable_llm_calls

    def debate(
        self,
        candidate_direction: SignalDirection,
        bars: List[MarketBar],
        symbol: str,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> AdversarialDebateResult:
        """
        Executa a investigação adversária contra a direção proposta.
        """
        bull_args = []
        bear_args = []
        traps = []
        penalty = 0.0
        veto = False

        if len(bars) < 30:
            return AdversarialDebateResult(
                symbol=symbol,
                risk_penalty_factor=0.10,
            )

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        rsi = calc_rsi(closes, 14)

        c = closes[-1]
        curr_rsi = rsi[-1]

        # 1. Investigação de Bull Trap (Risco ao Comprador)
        # Preço fazendo novas máximas, mas RSI fazendo topos descendentes (Divergência Baixista)
        if candidate_direction == SignalDirection.BUY:
            bull_args.append("Preço mantém estrutura de curto prazo positiva")
            # Checa divergência de topo recente
            recent_high_idx = np.argmax(highs[-10:]) + (len(highs) - 10)
            if curr_rsi >= 70.0:
                bear_args.append("RSI em sobrecompra extrema (> 70) vulnerável a realização")
                penalty += 0.10

            # Checa pavio superior de rejeição na última barra
            last_bar = bars[-1]
            total_range = max(last_bar.high - last_bar.low, 0.0001)
            upper_wick = last_bar.high - max(last_bar.open, last_bar.close)
            if upper_wick / total_range >= 0.50:
                traps.append("BULL_TRAP_UPPER_WICK_REJECTION")
                bear_args.append("Último candle exibiu forte rejeição compradora (pavio superior > 50%)")
                penalty += 0.20

            # Checa divergência simples nos últimos 15 candles
            if closes[-1] > closes[-15] and rsi[-1] < rsi[-15] - 5.0:
                traps.append("BEARISH_RSI_DIVERGENCE")
                bear_args.append("Divergência de baixa no RSI: preço subiu mas momentum desacelerou")
                penalty += 0.15

        # 2. Investigação de Bear Trap (Risco ao Vendedor)
        elif candidate_direction == SignalDirection.SELL:
            bear_args.append("Preço mantém estrutura de curto prazo negativa")
            if curr_rsi <= 30.0:
                bull_args.append("RSI em sobrevenda extrema (< 30) sujeito a repique técnico")
                penalty += 0.10

            # Pavio inferior de rejeição na última barra
            last_bar = bars[-1]
            total_range = max(last_bar.high - last_bar.low, 0.0001)
            lower_wick = min(last_bar.open, last_bar.close) - last_bar.low
            if lower_wick / total_range >= 0.50:
                traps.append("BEAR_TRAP_LOWER_WICK_REJECTION")
                bull_args.append("Último candle exibiu forte absorção de compras (pavio inferior > 50%)")
                penalty += 0.20

            # Divergência altista no RSI
            if closes[-1] < closes[-15] and rsi[-1] > rsi[-15] + 5.0:
                traps.append("BULLISH_RSI_DIVERGENCE")
                bull_args.append("Divergência de alta no RSI: preço caiu mas exaustão vendedora é visível")
                penalty += 0.15

        # Limita a penalidade máxima a 0.40 (40% de desconto no score de consenso)
        risk_penalty = round(min(0.40, penalty), 2)
        if risk_penalty >= 0.35:
            logger.warning("adversarial_severe_risk_flagged", symbol=symbol, traps=traps, penalty=risk_penalty)

        return AdversarialDebateResult(
            symbol=symbol,
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            detected_traps=traps,
            risk_penalty_factor=risk_penalty,
            veto_flag=veto,
        )

    def analyze(
        self,
        bars_multi_tf: Dict[TimeFrame, List[MarketBar]],
        symbol: str,
        current_tick: Optional[MarketTick] = None,
        macro_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentSignal]:
        # AG07 é fundamentalmente um auditor adversarial do consenso.
        # Emite sinal autônomo apenas quando detecta reversão violenta de armadilha
        tf = TimeFrame.M15 if TimeFrame.M15 in bars_multi_tf else TimeFrame.M5
        bars = bars_multi_tf.get(tf)
        if not bars or len(bars) < 30:
            return None

        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        atr = calc_atr(highs, lows, closes, 14)
        curr_atr = atr[-1]
        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Avalia potenciais armadilhas contra compradores ou vendedores
        buy_debate = self.debate(SignalDirection.BUY, bars, symbol, macro_context)
        sell_debate = self.debate(SignalDirection.SELL, bars, symbol, macro_context)

        c = closes[-1]
        entry = current_tick.ask if current_tick and current_tick.ask > 0 else c
        stop_dist = max(curr_atr * 1.5, 0.00015)

        # Se houver armadilha comprovada de compradores (BULL_TRAP), recomenda VENDA contra os comprados
        if "BULL_TRAP_UPPER_WICK_REJECTION" in buy_debate.detected_traps and buy_debate.risk_penalty_factor >= 0.20:
            entry_sell = current_tick.bid if current_tick and current_tick.bid > 0 else c
            stop_loss = round(entry_sell + stop_dist, 5)
            take_profit = round(entry_sell - (stop_dist * 2.0), 5)
            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.SELL,
                confidence=0.78,
                entry=entry_sell,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(entry_sell + (stop_dist * 1.2), 5),
                rationale={
                    "adversarial_thesis": "FADE_BULL_TRAP",
                    "traps": buy_debate.detected_traps,
                    "bear_arguments": buy_debate.bear_arguments,
                },
            )

        # Se houver armadilha comprovada de vendedores (BEAR_TRAP), recomenda COMPRA contra os vendidos
        if "BEAR_TRAP_LOWER_WICK_REJECTION" in sell_debate.detected_traps and sell_debate.risk_penalty_factor >= 0.20:
            stop_loss = round(entry - stop_dist, 5)
            take_profit = round(entry + (stop_dist * 2.0), 5)
            return self.build_signal(
                symbol=symbol,
                timeframe=tf,
                direction=SignalDirection.BUY,
                confidence=0.78,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                invalidation_level=round(entry - (stop_dist * 1.2), 5),
                rationale={
                    "adversarial_thesis": "FADE_BEAR_TRAP",
                    "traps": sell_debate.detected_traps,
                    "bull_arguments": sell_debate.bull_arguments,
                },
            )

        return None
