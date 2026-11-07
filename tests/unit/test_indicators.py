"""
QUANT HERMES — Testes da Biblioteca Matemática de Indicadores
Arquivo: tests/unit/test_indicators.py
"""
import numpy as np
import pytest
from data.features.indicators import (
    calc_sma,
    calc_ema,
    calc_atr,
    calc_bollinger_bands,
    calc_rsi,
    calc_macd,
    calc_adx,
    calc_zscore,
    calc_donchian,
    detect_swings,
    detect_bos_choch,
)


@pytest.fixture
def sample_ohlcv():
    np.random.seed(42)
    n = 100
    base_price = 100.0
    returns = np.random.normal(0.001, 0.01, n)
    close = base_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    open_p = (high + low) / 2.0
    return open_p, high, low, close


class TestIndicators:
    """Testes de integridade matemática e numérica dos indicadores."""

    def test_calc_sma_and_ema(self, sample_ohlcv):
        _, _, _, close = sample_ohlcv
        sma20 = calc_sma(close, 20)
        ema20 = calc_ema(close, 20)

        assert len(sma20) == len(close)
        assert len(ema20) == len(close)
        assert np.isnan(sma20[:19]).all()
        assert not np.isnan(sma20[19:]).any()
        assert not np.isnan(ema20).any()
        # Médias devem ser comparáveis aos preços
        assert 80.0 < sma20[-1] < 120.0

    def test_calc_atr(self, sample_ohlcv):
        _, high, low, close = sample_ohlcv
        atr14 = calc_atr(high, low, close, 14)
        assert len(atr14) == len(close)
        # ATR deve ser estritamente positivo após o período
        valid_atr = atr14[13:]
        assert (valid_atr > 0).all()

    def test_calc_bollinger_bands(self, sample_ohlcv):
        _, _, _, close = sample_ohlcv
        upper, middle, lower = calc_bollinger_bands(close, 20, 2.0)
        valid_idx = slice(19, None)
        assert (upper[valid_idx] >= middle[valid_idx]).all()
        assert (middle[valid_idx] >= lower[valid_idx]).all()

    def test_calc_rsi(self, sample_ohlcv):
        _, _, _, close = sample_ohlcv
        rsi = calc_rsi(close, 14)
        assert len(rsi) == len(close)
        # RSI deve estar estritamente entre 0 e 100
        assert (rsi >= 0.0).all() and (rsi <= 100.0).all()

    def test_calc_macd(self, sample_ohlcv):
        _, _, _, close = sample_ohlcv
        macd, signal, hist = calc_macd(close, 12, 26, 9)
        assert len(macd) == len(close)
        assert len(signal) == len(close)
        assert len(hist) == len(close)
        # Histograma deve ser macd - signal
        np.testing.assert_allclose(hist, macd - signal, rtol=1e-5)

    def test_calc_adx(self, sample_ohlcv):
        _, high, low, close = sample_ohlcv
        adx, plus_di, minus_di = calc_adx(high, low, close, 14)
        assert len(adx) == len(close)
        assert (adx >= 0.0).all() and (adx <= 100.0).all()

    def test_calc_zscore(self, sample_ohlcv):
        _, _, _, close = sample_ohlcv
        zscore = calc_zscore(close, 20)
        assert len(zscore) == len(close)
        # Z-scores típicos ficam entre -4 e +4
        assert (zscore > -6.0).all() and (zscore < 6.0).all()

    def test_calc_donchian(self, sample_ohlcv):
        _, high, low, _ = sample_ohlcv
        upper, middle, lower = calc_donchian(high, low, 20)
        valid = slice(19, None)
        assert (upper[valid] >= lower[valid]).all()
        np.testing.assert_allclose(middle[valid], (upper[valid] + lower[valid]) / 2.0)

    def test_detect_swings_deterministic(self):
        # Série simples em V invertido: 10, 12, 15, 20, 15, 12, 10
        high = np.array([10.0, 12.0, 14.0, 20.0, 14.0, 12.0, 10.0])
        low = np.array([8.0, 10.0, 12.0, 18.0, 12.0, 10.0, 8.0])

        is_sh, is_sl = detect_swings(high, low, left_bars=2, right_bars=2)
        # O pico de High está no índice 3 (20.0)
        assert is_sh[3] is True or is_sh[3] == 1
        assert not is_sh[0:3].any()
        assert not is_sh[4:].any()

    def test_detect_bos_choch_deterministic(self):
        # Cria padrão claro com topo rompido
        # Barras: 0..5 formam topo em 15.0 na barra 2; depois barra 8 rompe 15.0 fechando em 16.0
        high = np.array([10.0, 12.0, 15.0, 12.0, 10.0, 11.0, 12.0, 14.0, 17.0, 18.0])
        low = np.array([8.0, 9.0, 11.0, 9.0, 8.0, 9.0, 10.0, 12.0, 15.0, 16.0])
        close = np.array([9.0, 11.0, 14.0, 11.0, 9.0, 10.0, 11.0, 13.0, 16.5, 17.5])

        events = detect_bos_choch(high, low, close, left_bars=2, right_bars=2)
        assert len(events) >= 1
        # Evento deve ser de rompimento de alta (CHOCH_BULLISH ou BOS_BULLISH)
        assert "BULLISH" in events[0]["type"]
        assert events[0]["broken_level"] == 15.0
