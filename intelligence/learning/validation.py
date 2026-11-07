"""
QUANT HERMES — VALIDAÇÃO PURGADA E COM EMBARGO WALK-FORWARD
Módulo: intelligence.learning.validation

Implementa validação cruzada estrita para séries financeiras baseada nos protocolos de
Marcos López de Prado (Advances in Financial Machine Learning):
1. Purging: Eliminação de sobreposição temporal entre janelas de previsão e teste.
2. Embargo: Margem de segurança pós-teste para mitigar autocorrelação serial.
3. Portão Constitucional de Qualidade Out-of-Sample (OOS).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from core.logger import get_logger
from core.models.market import MarketBar
from intelligence.learning.classifier import QuantitativeMLClassifier

logger = get_logger("purged_validation")


@dataclass(frozen=True)
class ValidationFoldResult:
    """Resultado detalhado de um fold da validação purgada."""
    fold_idx: int
    train_indices: Tuple[int, int]
    test_indices: Tuple[int, int]
    purged_count: int
    embargoed_count: int
    accuracy: float
    profit_factor: float
    win_rate: float
    total_trades: int
    gross_profit: float
    gross_loss: float
    max_drawdown: float


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


class PurgedWalkForwardValidator:
    """
    Validador temporal Walk-Forward com Purging e Embargo.
    Avalia a verdadeira capacidade preditiva fora da amostra e barra modelos
    que apresentem overfitting ou vazamento de dados.
    """

    def __init__(
        self,
        n_splits: int = 4,
        forward_horizon: int = 5,
        embargo_pct: float = 0.02,
        min_oos_profit_factor: float = 1.30,
        min_oos_win_rate: float = 0.50,
        max_oos_drawdown: float = 0.08,
        min_oos_trades: int = 15,
    ) -> None:
        self.n_splits = n_splits
        self.forward_horizon = forward_horizon
        self.embargo_pct = embargo_pct
        self.min_oos_profit_factor = min_oos_profit_factor
        self.min_oos_win_rate = min_oos_win_rate
        self.max_oos_drawdown = max_oos_drawdown
        self.min_oos_trades = min_oos_trades

    def generate_purged_splits(
        self,
        n_samples: int,
    ) -> List[Tuple[np.ndarray, np.ndarray, int, int]]:
        """
        Gera índices de treino e teste respeitando Purging e Embargo.
        Retorna lista de (train_indices, test_indices, purged_count, embargo_count).
        """
        if n_samples < 80:
            raise ValueError(f"Amostras insuficientes para validação purgada: {n_samples} (mínimo 80)")

        # Tamanho de cada fold de teste
        test_size = n_samples // (self.n_splits + 1)
        embargo_size = max(1, int(n_samples * self.embargo_pct))
        splits = []

        for split_idx in range(self.n_splits):
            test_start = (split_idx + 1) * test_size
            test_end = min(n_samples, test_start + test_size)

            test_indices = np.arange(test_start, test_end)

            # Purging: remove do treino as amostras que avançam para dentro do teste
            # Ou seja, qualquer barra de treino t cujo t + forward_horizon >= test_start
            train_early_end = max(0, test_start - self.forward_horizon)
            train_early = np.arange(0, train_early_end)

            # Embargo pós-teste: barras após test_end só entram no treino após embargo_size
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

    def validate(
        self,
        bars: List[MarketBar],
        classifier_factory: Optional[Any] = None,
    ) -> ValidationReport:
        """
        Executa a validação purgada completa e gera o relatório com portão constitucional.
        """
        if len(bars) < 120:
            raise ValueError(f"Mínimo de 120 barras requerido para validação purgada completa, recebido {len(bars)}")

        # Cria classificador base temporário para extrair features e labels consistentes
        temp_clf = QuantitativeMLClassifier(forward_bars=self.forward_horizon)
        features, valid_indices = temp_clf.extract_features(bars)
        labels = temp_clf.create_labels(bars, valid_indices)

        # Corta a margem do target forward
        valid_len = len(valid_indices) - self.forward_horizon
        X = features[:valid_len]
        y = labels[:valid_len]
        bar_subset = bars[valid_indices[0] : valid_indices[valid_len]]

        splits = self.generate_purged_splits(len(X))
        fold_results: List[ValidationFoldResult] = []

        all_profits: List[float] = []
        all_losses: List[float] = []
        all_returns: List[float] = []

        for fold_idx, (train_idx, test_idx, purged_count, embargo_count) in enumerate(splits):
            if len(train_idx) < 30 or len(test_idx) < 10:
                continue

            X_train, y_train = X[train_idx], y[train_idx]
            X_test, y_test = X[test_idx], y[test_idx]

            # Verifica balanceamento mínimo
            if len(np.unique(y_train)) < 2:
                continue

            # Treina classificador exclusivo do fold usando XGBoost / LightGBM com n_jobs=1
            clf = QuantitativeMLClassifier(
                engine="xgboost",
                forward_bars=self.forward_horizon,
                random_state=42 + fold_idx,
            )
            # Ajusta modelo com features escaladas contíguas em C
            clf.scaler.fit(X_train)
            X_train_scaled = np.ascontiguousarray(clf.scaler.transform(X_train), dtype=np.float32)
            y_train_arr = np.ascontiguousarray(y_train, dtype=np.int32)
            base_model = clf._init_base_estimator()
            base_model.fit(X_train_scaled, y_train_arr)
            clf.model = base_model
            clf.is_fitted = True

            # Avaliação Out-of-Sample
            X_test_scaled = np.ascontiguousarray(clf.scaler.transform(X_test), dtype=np.float32)
            preds = clf.model.predict(X_test_scaled)
            accuracy = float(np.mean(preds == y_test))

            # Simulação econômica dos trades do fold OOS
            gross_profit = 0.0
            gross_loss = 0.0
            trade_count = 0
            equity_curve = [10000.0]
            current_eq = 10000.0

            for i, p in enumerate(preds):
                if p == 1:  # HOLD / sem trade
                    continue

                actual_label = y_test[i]
                trade_count += 1

                # Trade acerta se p == actual_label
                if p == actual_label:
                    pnl = 20.0  # R:R positivo padrão
                    gross_profit += pnl
                    current_eq += pnl
                    all_profits.append(pnl)
                    all_returns.append(0.002)
                else:
                    pnl = -10.0
                    gross_loss += abs(pnl)
                    current_eq += pnl
                    all_losses.append(abs(pnl))
                    all_returns.append(-0.001)

                equity_curve.append(current_eq)

            # Drawdown do fold
            peak = 10000.0
            max_dd = 0.0
            for eq in equity_curve:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd

            pf = (gross_profit / gross_loss) if gross_loss > 0 else (2.0 if gross_profit > 0 else 1.0)
            win_rate = (len(all_profits) / trade_count) if trade_count > 0 else 0.0

            fold_results.append(
                ValidationFoldResult(
                    fold_idx=fold_idx,
                    train_indices=(int(train_idx[0]), int(train_idx[-1])),
                    test_indices=(int(test_idx[0]), int(test_idx[-1])),
                    purged_count=purged_count,
                    embargoed_count=embargo_count,
                    accuracy=round(accuracy, 4),
                    profit_factor=round(pf, 3),
                    win_rate=round(win_rate, 4),
                    total_trades=trade_count,
                    gross_profit=round(gross_profit, 2),
                    gross_loss=round(gross_loss, 2),
                    max_drawdown=round(max_dd, 4),
                )
            )

        # Consolidado
        total_gross_profit = sum(all_profits)
        total_gross_loss = sum(all_losses)
        total_trades = len(all_profits) + len(all_losses)

        mean_pf = (
            (total_gross_profit / total_gross_loss)
            if total_gross_loss > 0
            else (2.5 if total_gross_profit > 0 else 1.0)
        )
        mean_win_rate = (len(all_profits) / total_trades) if total_trades > 0 else 0.0

        if len(all_returns) >= 5 and np.std(all_returns) > 1e-9:
            mean_sharpe = float(np.mean(all_returns) / np.std(all_returns) * np.sqrt(252 * 24))
        else:
            mean_sharpe = 1.0

        worst_dd = max((f.max_drawdown for f in fold_results), default=0.0)

        # Avaliação Constitucional
        rejections: List[str] = []
        if mean_pf < self.min_oos_profit_factor:
            rejections.append(
                f"Profit Factor OOS ({mean_pf:.2f}) abaixo do piso constitucional de {self.min_oos_profit_factor:.2f}"
            )
        if mean_win_rate < self.min_oos_win_rate:
            rejections.append(
                f"Win Rate OOS ({mean_win_rate:.1%}) abaixo do piso constitucional de {self.min_oos_win_rate:.1%}"
            )
        if worst_dd > self.max_oos_drawdown:
            rejections.append(
                f"Drawdown Máximo OOS ({worst_dd:.1%}) excedeu o teto constitucional de {self.max_oos_drawdown:.1%}"
            )
        if total_trades < self.min_oos_trades:
            rejections.append(
                f"Amostra total de trades OOS ({total_trades}) inferior ao mínimo de significância ({self.min_oos_trades})"
            )

        is_approved = len(rejections) == 0

        logger.info(
            "Validação Purgada Walk-Forward concluída",
            extra={
                "approved": is_approved,
                "profit_factor": round(mean_pf, 2),
                "win_rate": round(mean_win_rate, 4),
                "worst_dd": round(worst_dd, 4),
                "total_oos_trades": total_trades,
            },
        )

        return ValidationReport(
            is_approved_for_production=is_approved,
            rejection_reasons=rejections,
            total_folds=len(fold_results),
            mean_profit_factor=round(mean_pf, 3),
            mean_win_rate=round(mean_win_rate, 4),
            mean_sharpe=round(mean_sharpe, 2),
            max_drawdown_observed=round(worst_dd, 4),
            total_oos_trades=total_trades,
            fold_results=fold_results,
        )
