"""
QUANT HERMES — Dimensionador Matemático de Lotes (Position Sizer)
Módulo: risk.position_sizer
"""
from __future__ import annotations

import math
from typing import Optional
from core.models.market import SymbolSpecification


class PositionSizer:
    """
    Dimensionador matemático de lotes de alta precisão.
    Garante:
    1. Cálculo do lote com base no risco monetário exato e distância para o Stop Loss.
    2. Respeito estrito às especificações da corretora (volMin, volMax, volStep).
    3. Arredondamento estritamente para baixo (Floor) no passo de volume (volStep),
       eliminando o risco de sobrealavancagem acidental.
    4. Postura Fail-Safe: retorna 0.0 caso o lote seja inferior ao mínimo permitido.
    """

    @staticmethod
    def normalize_lot(raw_lot: float, vol_min: float, vol_max: float, vol_step: float) -> float:
        """
        Normaliza o lote bruto para os limites do símbolo.
        Arredonda estritamente para baixo respeitando o passo de volume (volStep).
        """
        if raw_lot <= 0.0 or vol_step <= 0.0:
            return 0.0

        # Arredonda estritamente para baixo no passo do volume com epsilon numérico
        lot = math.floor(raw_lot / vol_step + 1e-9) * vol_step

        if lot < vol_min:
            return 0.0
        if lot > vol_max:
            lot = vol_max

        # Determina o número de casas decimais com base no volStep
        digits = max(0, min(8, int(round(-math.log10(vol_step)))))
        return round(lot, digits)

    @staticmethod
    def calculate_lot(
        risk_money: float,
        entry_price: float,
        stop_loss_price: float,
        spec: SymbolSpecification,
        commission_per_lot: float = 0.0,
    ) -> float:
        """
        Calcula o lote a partir do capital em risco e da distância para o Stop Loss.

        Fórmula:
            loss_per_lot = (sl_distance / tick_size) * tick_value + commission_per_lot
            raw_lot = risk_money / loss_per_lot
        """
        if risk_money <= 0.0:
            return 0.0

        sl_distance = abs(entry_price - stop_loss_price)
        if sl_distance <= 0.0 or spec.tick_size <= 0.0 or spec.tick_value <= 0.0:
            return 0.0

        # Perda financeira calculada para 1 lote padrão
        loss_per_lot = (sl_distance / spec.tick_size) * spec.tick_value
        if commission_per_lot > 0.0:
            loss_per_lot += commission_per_lot

        if loss_per_lot <= 0.0:
            return 0.0

        raw_lot = risk_money / loss_per_lot
        return PositionSizer.normalize_lot(
            raw_lot=raw_lot,
            vol_min=spec.volume_min,
            vol_max=spec.volume_max,
            vol_step=spec.volume_step,
        )

