"""
QUANT HERMES — Biblioteca Matemática de Indicadores e Engenharia de Features
Módulo: data.features.indicators
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


def calc_sma(series: np.ndarray | pd.Series, period: int) -> np.ndarray:
    """Média Móvel Simples (SMA)."""
    s = pd.Series(series) if not isinstance(series, pd.Series) else series
    return s.rolling(window=period, min_periods=period).mean().to_numpy()


def calc_ema(series: np.ndarray | pd.Series, period: int) -> np.ndarray:
    """Média Móvel Exponencial (EMA)."""
    s = pd.Series(series) if not isinstance(series, pd.Series) else series
    return s.ewm(span=period, adjust=False).mean().to_numpy()


def calc_atr(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """Average True Range (ATR) usando suavização exponencial de Wilder."""
    h = pd.Series(high)
    l = pd.Series(low)
    c = pd.Series(close)

    prev_close = c.shift(1)
    tr1 = h - l
    tr2 = (h - prev_close).abs()
    tr3 = (l - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return atr.to_numpy()


def calc_bollinger_bands(
    close: np.ndarray | pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bandas de Bollinger: Retorna (Upper, Middle, Lower)."""
    c = pd.Series(close)
    middle = c.rolling(window=period, min_periods=period).mean()
    std = c.rolling(window=period, min_periods=period).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    return upper.to_numpy(), middle.to_numpy(), lower.to_numpy()


def calc_rsi(close: np.ndarray | pd.Series, period: int = 14) -> np.ndarray:
    """Índice de Força Relativa (RSI) com suavização Wilder."""
    c = pd.Series(close)
    delta = c.diff()

    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    # Previne divisão por zero
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # Onde avg_loss é 0 e avg_gain > 0, RSI = 100; onde ambos são 0, RSI = 50
    rsi = rsi.fillna(50.0)
    return rsi.to_numpy()


def calc_macd(
    close: np.ndarray | pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD: Retorna (macd_line, signal_line, histogram)."""
    c = pd.Series(close)
    ema_fast = c.ewm(span=fast_period, adjust=False).mean()
    ema_slow = c.ewm(span=slow_period, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.to_numpy(), signal_line.to_numpy(), histogram.to_numpy()


def calc_adx(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 14,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Average Directional Index (ADX): Retorna (adx, plus_di, minus_di)."""
    h = pd.Series(high)
    l = pd.Series(low)
    c = pd.Series(close)

    prev_high = h.shift(1)
    prev_low = l.shift(1)
    prev_close = c.shift(1)

    up_move = h - prev_high
    down_move = prev_low - l

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = h - l
    tr2 = (h - prev_close).abs()
    tr3 = (l - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    plus_di = 100.0 * (pd.Series(plus_dm).ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr)
    minus_di = 100.0 * (pd.Series(minus_dm).ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().fillna(0.0)

    return adx.to_numpy(), plus_di.fillna(0.0).to_numpy(), minus_di.fillna(0.0).to_numpy()


def calc_zscore(series: np.ndarray | pd.Series, period: int = 20) -> np.ndarray:
    """Z-Score estatístico: desvio padronizado em relação à média móvel."""
    s = pd.Series(series)
    mean = s.rolling(window=period, min_periods=period).mean()
    std = s.rolling(window=period, min_periods=period).std()
    zscore = (s - mean) / std.replace(0.0, np.nan)
    return zscore.fillna(0.0).to_numpy()


def calc_donchian(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    period: int = 20,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Canais Donchian: Retorna (Upper, Middle, Lower)."""
    h = pd.Series(high)
    l = pd.Series(low)
    upper = h.rolling(window=period, min_periods=period).max()
    lower = l.rolling(window=period, min_periods=period).min()
    middle = (upper + lower) / 2.0
    return upper.to_numpy(), middle.to_numpy(), lower.to_numpy()


def detect_swings(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    left_bars: int = 3,
    right_bars: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Identificação determinística de Swing Highs e Swing Lows fractais.
    Retorna boolean arrays: (is_swing_high, is_swing_low).
    Um Swing High na barra i é estritamente maior que as 'left_bars' anteriores
    e as 'right_bars' posteriores.
    """
    h = np.asarray(high)
    l = np.asarray(low)
    n = len(h)

    is_swing_high = np.zeros(n, dtype=bool)
    is_swing_low = np.zeros(n, dtype=bool)

    for i in range(left_bars, n - right_bars):
        # Checa Swing High
        val_h = h[i]
        if all(val_h > h[i - left_bars : i]) and all(val_h >= h[i + 1 : i + 1 + right_bars]):
            is_swing_high[i] = True

        # Checa Swing Low
        val_l = l[i]
        if all(val_l < l[i - left_bars : i]) and all(val_l <= l[i + 1 : i + 1 + right_bars]):
            is_swing_low[i] = True

    return is_swing_high, is_swing_low


def detect_bos_choch(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    left_bars: int = 3,
    right_bars: int = 3,
) -> List[Dict[str, any]]:
    """
    Identificação determinística e objetiva de Break of Structure (BOS) e Change of Character (CHoCH).
    Regras estritas (sem subjetividade de SMC):
    - Tendência inicial é determinada pela sequência de swings:
      * Higher High (HH) + Higher Low (HL) = BULLISH
      * Lower Low (LL) + Lower High (LH) = BEARISH
    - BOS: Rompimento com candle fechando além do último swing no sentido da tendência vigente.
    - CHoCH: Rompimento com candle fechando além do último swing estrutural no sentido oposto,
      sinalizando potencial reversão.
    """
    h = np.asarray(high)
    l = np.asarray(low)
    c = np.asarray(close)
    n = len(c)

    is_sh, is_sl = detect_swings(h, l, left_bars, right_bars)

    events = []
    current_trend = 0  # +1 Bullish, -1 Bearish, 0 Indefinido
    last_swing_high_price: Optional[float] = None
    last_swing_high_idx: Optional[int] = None
    last_swing_low_price: Optional[float] = None
    last_swing_low_idx: Optional[int] = None

    for i in range(n):
        # Se um novo swing confirmou no passado (em i - right_bars)
        confirm_idx = i - right_bars
        if confirm_idx >= 0:
            if is_sh[confirm_idx]:
                last_swing_high_price = h[confirm_idx]
                last_swing_high_idx = confirm_idx
            if is_sl[confirm_idx]:
                last_swing_low_price = l[confirm_idx]
                last_swing_low_idx = confirm_idx

        # Avalia rompimento pelo preço de fechamento (Close)
        if last_swing_high_price is not None and c[i] > last_swing_high_price:
            if current_trend == 1:
                event_type = "BOS_BULLISH"
            else:
                event_type = "CHOCH_BULLISH"
                current_trend = 1

            events.append({
                "bar_index": i,
                "type": event_type,
                "broken_level": last_swing_high_price,
                "broken_swing_index": last_swing_high_idx,
                "close_price": c[i],
            })
            # Invalida swing rompido
            last_swing_high_price = None

        elif last_swing_low_price is not None and c[i] < last_swing_low_price:
            if current_trend == -1:
                event_type = "BOS_BEARISH"
            else:
                event_type = "CHOCH_BEARISH"
                current_trend = -1

            events.append({
                "bar_index": i,
                "type": event_type,
                "broken_level": last_swing_low_price,
                "broken_swing_index": last_swing_low_idx,
                "close_price": c[i],
            })
            # Invalida swing rompido
            last_swing_low_price = None

    return events

