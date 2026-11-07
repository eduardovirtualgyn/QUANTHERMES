"""
QUANT HERMES — Calibrador Probabilístico de Platt (Sigmoid Scaling)
Módulo: intelligence.calibration.platt_scaler
"""
from __future__ import annotations

import math
from typing import List, Optional
import numpy as np


class PlattScaler:
    """
    Calibrador de probabilidade a posteriori baseado no método de Platt (Platt Scaling).
    Transforma pontuações compostas e margens não calibradas [-1.0, +1.0]
    em probabilidades estatisticamente calibradas P(Sucesso | Score) no intervalo [0.0, 1.0].
    
    Fórmula:
        P = 1 / (1 + exp(-(A * |score| + B)))
    """

    def __init__(self, param_a: float = 3.20, param_b: float = -0.50):
        self.param_a = param_a
        self.param_b = param_b

    def calibrate(self, composite_score: float) -> float:
        """
        Retorna a probabilidade calibrada de sucesso da tese a partir do score composto absoluto.
        Garante limites numéricos estritos [0.0, 1.0].
        """
        abs_score = abs(float(composite_score))
        exponent = -(self.param_a * abs_score + self.param_b)
        
        # Evita overflow numérico no cálculo da exponencial
        exponent = max(-50.0, min(50.0, exponent))
        prob = 1.0 / (1.0 + math.exp(exponent))
        return round(float(prob), 4)

    def fit(self, scores: List[float], outcomes: List[int]) -> None:
        """
        Ajusta os parâmetros A e B via regressão logística com penalidade Ridge
        a partir do histórico de scores e resultados reais (1 = Win, 0 = Loss).
        """
        if len(scores) < 20 or len(scores) != len(outcomes):
            return

        x = np.abs(np.array(scores)).reshape(-1, 1)
        y = np.array(outcomes)

        # Regressão logística simples via Gradiente Descendente
        a = self.param_a
        b = self.param_b
        lr = 0.05

        for _ in range(100):
            z = a * x.ravel() + b
            z_clipped = np.clip(z, -30.0, 30.0)
            preds = 1.0 / (1.0 + np.exp(-z_clipped))
            errors = preds - y

            grad_a = np.mean(errors * x.ravel()) + 0.01 * a
            grad_b = np.mean(errors)

            a -= lr * grad_a
            b -= lr * grad_b

        # Mantém A estritamente positivo para garantir monotonicidade crescente
        self.param_a = max(0.5, float(a))
        self.param_b = float(b)
