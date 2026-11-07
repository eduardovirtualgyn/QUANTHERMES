"""
QUANT HERMES — CLASSIFICADOR SUPERVISIONADO DE MACHINE LEARNING
Módulo: intelligence.learning.classifier

Implementa modelo supervisionado para previsão probabilística de direção de mercado
utilizando LightGBM e XGBoost com calibração de probabilidades.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple
import numpy as np

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler

from core.logger import get_logger
from core.models.agent import SignalDirection
from core.models.market import MarketBar
from data.features.indicators import (
    calc_adx,
    calc_atr,
    calc_bollinger_bands,
    calc_ema,
    calc_macd,
    calc_rsi,
    calc_zscore,
)

logger = get_logger("ml_classifier")


@dataclass(frozen=True)
class DirectionPrediction:
    """Predição direcional emitida pelo modelo supervisionado."""
    direction: SignalDirection
    confidence: float
    probabilities: Dict[str, float]
    features: Dict[str, float]


class QuantitativeMLClassifier:
    """
    Classificador de Machine Learning para sinalização direcional e mensuração de edge estatístico.
    Suporta engines LightGBM e XGBoost com calibração isotônica/sigmóide de probabilidades.
    """

    FEATURE_NAMES = [
        "rsi_14",
        "macd_hist",
        "ema_dist_20",
        "ema_dist_50",
        "adx_14",
        "bb_width",
        "zscore_20",
        "returns_1",
        "returns_5",
        "atr_normalized",
    ]

    def __init__(
        self,
        engine: Literal["lightgbm", "xgboost"] = "lightgbm",
        forward_bars: int = 5,
        atr_multiplier: float = 1.0,
        min_probability_threshold: float = 0.55,
        random_state: int = 42,
    ) -> None:
        self.engine = engine
        self.forward_bars = forward_bars
        self.atr_multiplier = atr_multiplier
        self.min_probability_threshold = min_probability_threshold
        self.random_state = random_state

        self.model: Optional[Any] = None
        self.scaler: StandardScaler = StandardScaler()
        self.is_fitted: bool = False

    def extract_features(self, bars: List[MarketBar]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calcula as 10 features técnicas padronizadas a partir das barras OHLCV.
        Retorna (features_matrix, valid_indices).
        """
        if len(bars) < 60:
            raise ValueError(f"Mínimo de 60 barras requerido para extração de features, recebido {len(bars)}")

        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)

        # 1. RSI 14
        rsi = calc_rsi(closes, period=14)

        # 2. MACD
        _, _, macd_hist = calc_macd(closes, fast_period=12, slow_period=26, signal_period=9)

        # 3 & 4. Distâncias das EMAs 20 e 50 normalizadas pelo ATR
        atr = calc_atr(highs, lows, closes, period=14)
        safe_atr = np.where(atr > 1e-9, atr, 1e-4)

        ema_20 = calc_ema(closes, period=20)
        ema_50 = calc_ema(closes, period=50)
        ema_dist_20 = (closes - ema_20) / safe_atr
        ema_dist_50 = (closes - ema_50) / safe_atr

        # 5. ADX 14
        adx, _, _ = calc_adx(highs, lows, closes, period=14)

        # 6. Bollinger Band Width
        _, bb_upper, bb_lower = calc_bollinger_bands(closes, period=20, num_std=2.0)
        bb_width = (bb_upper - bb_lower) / np.maximum(closes, 1e-9)

        # 7. Z-Score 20
        zscore = calc_zscore(closes, period=20)

        # 8 & 9. Retornos de 1 e 5 barras
        returns_1 = np.zeros(len(closes))
        returns_1[1:] = (closes[1:] - closes[:-1]) / np.maximum(closes[:-1], 1e-9)

        returns_5 = np.zeros(len(closes))
        returns_5[5:] = (closes[5:] - closes[:-5]) / np.maximum(closes[:-5], 1e-9)

        # 10. ATR Normalizado (Volatilidade percentual)
        atr_norm = safe_atr / np.maximum(closes, 1e-9)

        features = np.column_stack([
            np.nan_to_num(rsi, nan=50.0),
            np.nan_to_num(macd_hist, nan=0.0),
            np.nan_to_num(ema_dist_20, nan=0.0),
            np.nan_to_num(ema_dist_50, nan=0.0),
            np.nan_to_num(adx, nan=15.0),
            np.nan_to_num(bb_width, nan=0.01),
            np.nan_to_num(zscore, nan=0.0),
            np.nan_to_num(returns_1, nan=0.0),
            np.nan_to_num(returns_5, nan=0.0),
            np.nan_to_num(atr_norm, nan=0.001),
        ])

        warmup = 55
        return features[warmup:], np.arange(warmup, len(bars))

    def create_labels(self, bars: List[MarketBar], valid_indices: np.ndarray) -> np.ndarray:
        """
        Gera rótulos supervisionados via Triple-Barrier / Forward Returns:
        - Classe 2 (BUY): Retorno futuro em H barras >= +k * ATR
        - Classe 0 (SELL): Retorno futuro em H barras <= -k * ATR
        - Classe 1 (HOLD): Retorno futuro dentro da faixa neutra (ruído)
        """
        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)
        atr = calc_atr(highs, lows, closes, period=14)

        labels = []
        n_bars = len(bars)

        for idx in valid_indices:
            if idx + self.forward_bars >= n_bars:
                labels.append(1)  # HOLD por padrão no final da série
                continue

            current_close = closes[idx]
            future_close = closes[idx + self.forward_bars]
            target_distance = self.atr_multiplier * atr[idx]

            delta = future_close - current_close
            if delta >= target_distance:
                labels.append(2)  # BUY
            elif delta <= -target_distance:
                labels.append(0)  # SELL
            else:
                labels.append(1)  # HOLD

        return np.array(labels, dtype=int)

    def fit(self, bars: List[MarketBar]) -> QuantitativeMLClassifier:
        """
        Treina o classificador supervisionado com as barras históricas
        e calibra as probabilidades resultantes.
        """
        if len(bars) < 100:
            raise ValueError(f"Mínimo de 100 barras requerido para treino supervisionado, recebido {len(bars)}")

        features, valid_indices = self.extract_features(bars)
        labels = self.create_labels(bars, valid_indices)

        # Corta a cauda que não tem forward bars completos
        trim_len = len(valid_indices) - self.forward_bars
        if trim_len <= 10:
            raise ValueError("Amostras válidas insuficientes após trim dos forward targets")

        X = features[:trim_len]
        y = labels[:trim_len]

        # Verifica se temos ao menos 2 classes representadas
        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            raise ValueError(f"Dados contêm apenas uma classe ({unique_classes}), impossível treinar classificador")

        X_scaled = np.ascontiguousarray(self.scaler.fit_transform(X), dtype=np.float32)
        y = np.ascontiguousarray(y, dtype=np.int32)

        base_estimator = self._init_base_estimator()

        # Calibra probabilidades usando CalibratedClassifierCV
        cv_splits = min(3, int(np.min(np.bincount(y))))
        try:
            if cv_splits >= 2:
                self.model = CalibratedClassifierCV(
                    estimator=base_estimator,
                    method="sigmoid",
                    cv=cv_splits,
                )
                self.model.fit(X_scaled, y)
            else:
                base_estimator.fit(X_scaled, y)
                self.model = base_estimator
        except Exception as e:
            logger.warning(
                "Falha com engine primária, acionando fallback para XGBoost",
                extra={"primary_engine": self.engine, "error": str(e)},
            )
            # Fallback seguro para XGBoost ou GradientBoostingClassifier
            fallback_estimator = xgb.XGBClassifier(
                n_estimators=60,
                max_depth=3,
                learning_rate=0.03,
                n_jobs=1,
                random_state=self.random_state,
                eval_metric="mlogloss",
            ) if HAS_XGBOOST else base_estimator
            fallback_estimator.fit(X_scaled, y)
            self.model = fallback_estimator

        self.is_fitted = True
        logger.info(
            "QuantitativeMLClassifier treinado com sucesso",
            extra={"samples": len(X), "classes": [int(c) for c in np.unique(y)], "engine": self.engine},
        )
        return self

    def _init_base_estimator(self) -> Any:
        """Instancia o algoritmo de gradient boosting configurado com n_jobs=1."""
        if self.engine == "lightgbm" and HAS_LIGHTGBM:
            return lgb.LGBMClassifier(
                n_estimators=60,
                max_depth=3,
                learning_rate=0.03,
                num_leaves=7,
                min_child_samples=5,
                subsample=0.8,
                colsample_bytree=0.8,
                n_jobs=1,
                random_state=self.random_state,
                verbose=-1,
            )
        elif self.engine == "xgboost" and HAS_XGBOOST:
            return xgb.XGBClassifier(
                n_estimators=60,
                max_depth=3,
                learning_rate=0.03,
                subsample=0.8,
                colsample_bytree=0.8,
                n_jobs=1,
                random_state=self.random_state,
                eval_metric="mlogloss",
            )
        elif HAS_XGBOOST:
            return xgb.XGBClassifier(
                n_estimators=60,
                max_depth=3,
                learning_rate=0.03,
                n_jobs=1,
                random_state=self.random_state,
                eval_metric="mlogloss",
            )
        else:
            from sklearn.ensemble import GradientBoostingClassifier
            return GradientBoostingClassifier(
                n_estimators=60,
                max_depth=3,
                learning_rate=0.03,
                random_state=self.random_state,
            )

    def predict(self, bars: List[MarketBar]) -> DirectionPrediction:
        """
        Gera predição direcional com base na barra mais recente.
        """
        if not self.is_fitted or self.model is None:
            raise RuntimeError("Tentativa de inferência em QuantitativeMLClassifier não treinado")

        features, _ = self.extract_features(bars)
        latest_feature = features[-1:]
        scaled_feature = self.scaler.transform(latest_feature)

        # Predição de probabilidades
        proba = self.model.predict_proba(scaled_feature)[0]
        classes = self.model.classes_

        # Mapeia classes (0=SELL, 1=HOLD, 2=BUY)
        prob_map: Dict[int, float] = {0: 0.0, 1: 0.0, 2: 0.0}
        for cls, p in zip(classes, proba):
            prob_map[int(cls)] = float(p)

        prob_sell = prob_map.get(0, 0.0)
        prob_hold = prob_map.get(1, 0.0)
        prob_buy = prob_map.get(2, 0.0)

        # Determina direção baseada no limiar de confiança
        direction = SignalDirection.HOLD
        confidence = prob_hold

        if prob_buy >= self.min_probability_threshold and prob_buy > prob_sell:
            direction = SignalDirection.BUY
            confidence = prob_buy
        elif prob_sell >= self.min_probability_threshold and prob_sell > prob_buy:
            direction = SignalDirection.SELL
            confidence = prob_sell

        features_dict = {
            name: round(float(val), 5)
            for name, val in zip(self.FEATURE_NAMES, latest_feature[0])
        }

        return DirectionPrediction(
            direction=direction,
            confidence=round(confidence, 4),
            probabilities={
                "BUY": round(prob_buy, 4),
                "SELL": round(prob_sell, 4),
                "HOLD": round(prob_hold, 4),
            },
            features=features_dict,
        )
