"""
QUANT HERMES — VALIDAÇÃO PURGADA POR TIMESTAMPS E ECONOMIA REALISTA (FASE 6.1)
Módulo: intelligence.learning.validation

Implementa:
1. EIXO B — Purga temporal estrita por timestamps reais (López de Prado, 2018):
   - Elimina qualquer sobreposição entre o horizonte de previsão do treino e o intervalo do teste.
   - Aplica embargo pós-teste proporcional ao tempo decorrido, e não a índices ordinais.
   - Trata fins de semana, feriados e quebras de liquidez sem vazamento de informação (anti-lookahead).
2. EIXO C — Avaliação econômica com custos reais de mercado:
   - Elimina completamente retornos fictícios de +20/-10.
   - Modela spread dinâmico, comissão por lote, slippage e valor de tick/contrato.
   - Simula execução com Stop Loss e Take Profit dinâmicos baseados no ATR do mercado.
   - Calcula métricas completas: Sharpe Anualizado, Sortino, Profit Factor, CVaR e Sensibilidade a Custos.
3. Auditoria de integridade de dados temporais e consistência OHLCV.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple
import numpy as np

from core.logger import get_logger
from core.models.market import MarketBar, SymbolSpecification

logger = get_logger("purged_validation")


@dataclass(frozen=True)
class DataIntegrityReport:
    """Relatório de auditoria de qualidade e integridade cronológica dos dados de mercado."""
    is_valid: bool
    total_bars: int
    symbol: str
    timeframe: str
    duplicate_timestamps_count: int
    out_of_order_count: int
    invalid_ohlc_count: int
    detected_gaps_count: int
    zero_volume_count: int
    details: List[str]


@dataclass(frozen=True)
class ValidationFoldResult:
    """Resultado detalhado de um fold da validação purgada com economia realista."""
    fold_idx: int
    train_start_time: str
    train_end_time: str
    test_start_time: str
    test_end_time: str
    purged_bars_count: int
    embargoed_bars_count: int
    accuracy: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_profit: float
    gross_loss: float
    total_costs_paid: float
    net_profit: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    cost_sensitivity_pf_2x: float


@dataclass(frozen=True)
class ValidationReport:
    """Relatório consolidado de validação out-of-sample com veredito constitucional."""
    is_approved_for_production: bool
    rejection_reasons: List[str]
    total_folds: int
    mean_profit_factor: float
    mean_win_rate: float
    mean_sharpe: float
    max_drawdown_observed: float
    total_oos_trades: int
    fold_results: List[ValidationFoldResult]
    mean_sortino: float = 0.0
    total_net_pnl: float = 0.0
    total_transaction_costs: float = 0.0
    cost_sensitivity_pf_2x_mean: float = 1.0
    n_trials: int = 1
    bonferroni_alpha: float = 0.05
    deflated_sharpe_probability: float = 0.0
    expectancy_r: float = 0.0
    multiple_testing_passed: bool = False


def audit_market_data_integrity(
    bars: List[MarketBar],
    symbol: str = "UNKNOWN",
    expected_interval_minutes: int = 15,
) -> DataIntegrityReport:
    """
    Audita exaustivamente a série temporal de barras para identificar:
    - Inconsistências de High/Low/Open/Close.
    - Quebras na ordenação cronológica estrita.
    - Timestamps duplicados.
    - Lacunas temporais atípicas (gaps).
    """
    if not bars:
        return DataIntegrityReport(
            is_valid=False,
            total_bars=0,
            symbol=symbol,
            timeframe="UNKNOWN",
            duplicate_timestamps_count=0,
            out_of_order_count=0,
            invalid_ohlc_count=0,
            detected_gaps_count=0,
            zero_volume_count=0,
            details=["Lista de barras vazia"],
        )

    timeframe_str = bars[0].timeframe.value if hasattr(bars[0].timeframe, "value") else str(bars[0].timeframe)
    details: List[str] = []
    seen_timestamps = set()
    dup_count = 0
    ooo_count = 0
    invalid_ohlc = 0
    gap_count = 0
    zero_vol_count = 0

    max_expected_delta = timedelta(minutes=expected_interval_minutes * 4)  # Permite fins de semana

    for i, bar in enumerate(bars):
        # 1. Duplicidade de timestamp
        t = bar.time
        if t in seen_timestamps:
            dup_count += 1
            details.append(f"Timestamp duplicado na barra {i}: {t}")
        seen_timestamps.add(t)

        # 2. Ordem cronológica
        if i > 0:
            prev_t = bars[i - 1].time
            if t <= prev_t:
                ooo_count += 1
                details.append(f"Ordem cronológica violada na barra {i}: {t} <= {prev_t}")
            elif (t - prev_t) > max_expected_delta:
                gap_count += 1

        # 3. Coerência OHLC
        if bar.high < bar.low:
            invalid_ohlc += 1
            details.append(f"Barra {i} com High ({bar.high}) < Low ({bar.low})")
        if bar.open > bar.high or bar.open < bar.low:
            invalid_ohlc += 1
            details.append(f"Barra {i} com Open ({bar.open}) fora do range [{bar.low}, {bar.high}]")
        if bar.close > bar.high or bar.close < bar.low:
            invalid_ohlc += 1
            details.append(f"Barra {i} com Close ({bar.close}) fora do range [{bar.low}, {bar.high}]")

        # 4. Volume
        if bar.tick_volume <= 0:
            zero_vol_count += 1

    is_valid = (dup_count == 0 and ooo_count == 0 and invalid_ohlc == 0)

    return DataIntegrityReport(
        is_valid=is_valid,
        total_bars=len(bars),
        symbol=symbol,
        timeframe=timeframe_str,
        duplicate_timestamps_count=dup_count,
        out_of_order_count=ooo_count,
        invalid_ohlc_count=invalid_ohlc,
        detected_gaps_count=gap_count,
        zero_volume_count=zero_vol_count,
        details=details[:20],  # Limita log
    )


class PurgedWalkForwardValidator:
    """
    Validador temporal Walk-Forward com Purging por Timestamps Reais e Economia Realista.
    """

    def __init__(
        self,
        n_splits: int = 4,
        forward_horizon: int = 5,
        embargo_pct: float = 0.02,
        min_oos_profit_factor: float = 1.30,
        min_oos_win_rate: float = 0.50,
        max_oos_drawdown: float = 0.08,
        min_oos_trades: int = 10,
        # Parâmetros Econômicos Realistas
        spread_points: float = 0.00015,    # 1.5 pips em Forex; ProCent não cobra comissão
        commission_per_lot: float = 0.0,
        slippage_points: float = 0.00005,  # 0.5 pips de slippage médio
        default_lot_size: float = 0.10,
    ) -> None:
        self.n_splits = n_splits
        self.forward_horizon = forward_horizon
        self.embargo_pct = embargo_pct
        self.min_oos_profit_factor = min_oos_profit_factor
        self.min_oos_win_rate = min_oos_win_rate
        self.max_oos_drawdown = max_oos_drawdown
        self.min_oos_trades = min_oos_trades
        self.spread_points = spread_points
        self.commission_per_lot = commission_per_lot
        self.slippage_points = slippage_points
        self.default_lot_size = default_lot_size

    def generate_purged_splits(
        self,
        n_samples: int,
    ) -> List[Tuple[np.ndarray, np.ndarray, int, int]]:
        """
        Gera índices de treino e teste respeitando Purging e Embargo por índice ordinal.
        Mantido para compatibilidade retroativa com testes legados.
        """
        if n_samples < 80:
            raise ValueError(f"Amostras insuficientes para validação purgada: {n_samples} (mínimo 80)")

        test_size = n_samples // (self.n_splits + 1)
        embargo_size = max(1, int(n_samples * self.embargo_pct))
        splits = []

        for split_idx in range(self.n_splits):
            test_start = (split_idx + 1) * test_size
            test_end = min(n_samples, test_start + test_size)
            test_indices = np.arange(test_start, test_end)

            train_early_end = max(0, test_start - self.forward_horizon)
            train_early = np.arange(0, train_early_end)

            train_late_start = test_end + embargo_size
            if train_late_start < n_samples:
                train_late = np.arange(train_late_start, n_samples)
                train_indices = np.concatenate([train_early, train_late])
            else:
                train_indices = train_early

            purged_count = self.forward_horizon
            embargo_count = embargo_size
            splits.append((train_indices, test_indices, purged_count, embargo_count))

        return splits

    def generate_purged_splits_by_timestamp(
        self,
        bars: List[MarketBar],
    ) -> List[Tuple[np.ndarray, np.ndarray, int, int]]:
        """
        Gera splits de treino e teste utilizando os intervalos temporais contínuos reais (Eixo B).
        Garante que nenhuma observação de treino cujo horizonte forward_horizon invada
        o tempo inicial do teste faça parte do conjunto de treino.
        """
        n_samples = len(bars)
        if n_samples < 80:
            raise ValueError(f"Amostras insuficientes para validação purgada: {n_samples} (mínimo 80)")

        # Extrai timestamps
        timestamps = [b.time for b in bars]
        total_time_span = timestamps[-1] - timestamps[0]
        embargo_timedelta = total_time_span * self.embargo_pct

        test_size = n_samples // (self.n_splits + 1)
        splits = []

        for split_idx in range(self.n_splits):
            test_start_idx = (split_idx + 1) * test_size
            test_end_idx = min(n_samples, test_start_idx + test_size)
            test_indices = np.arange(test_start_idx, test_end_idx)

            test_start_time = timestamps[test_start_idx]
            test_end_time = timestamps[test_end_idx - 1]

            # 1. Treino Prévio (Early Train) com Purga Temporal Contínua:
            # Qualquer barra i cujo t_outcome (i + forward_horizon) >= test_start_time é PURGADA!
            train_early = []
            purged_count = 0
            for i in range(test_start_idx):
                outcome_idx = min(n_samples - 1, i + self.forward_horizon)
                outcome_time = timestamps[outcome_idx]
                if outcome_time < test_start_time:
                    train_early.append(i)
                else:
                    purged_count += 1

            # 2. Treino Posterior (Late Train) com Embargo Temporal:
            # Barras após o teste só entram após test_end_time + embargo_timedelta
            train_late = []
            embargo_count = 0
            embargo_cutoff = test_end_time + embargo_timedelta
            for i in range(test_end_idx, n_samples):
                if timestamps[i] > embargo_cutoff:
                    train_late.append(i)
                else:
                    embargo_count += 1

            train_indices = np.array(train_early + train_late, dtype=int)
            splits.append((train_indices, test_indices, purged_count, embargo_count))

        return splits

    def validate(
        self,
        bars: List[MarketBar],
        spec: Optional[SymbolSpecification] = None,
        strategies: Optional[list] = None,
    ) -> ValidationReport:
        """
        Avalia cada estratégia fora da amostra, com spread, slippage e swap.
        O modelo de ML não decide o veredito: ganhos fictícios de alvo/stop
        quando o rótulo coincide com a previsão foram removidos.
        """
        if len(bars) < 120:
            raise ValueError(f"Mínimo de 120 barras requerido para validação purgada completa, recebido {len(bars)}")
        from intelligence.learning.strategy_walkforward import evaluate_strategies_oos

        return evaluate_strategies_oos(self, bars, spec, strategies)
