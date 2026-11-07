"""
QUANT HERMES — DETECTOR DE REGIMES VIA HIDDEN MARKOV MODEL (HMM)
Módulo: intelligence.regime.hmm_detector

Implementa detecção estocástica de regimes de mercado não supervisionada utilizando
Gaussian Hidden Markov Models (hmmlearn.hmm.GaussianHMM).

Estados modelados:
1. TREND_BULL_STRONG (Tendência de Alta)
2. TREND_BEAR_STRONG (Tendência de Baixa)
3. RANGING_LOW_VOL (Mercado Lateral / Baixa Volatilidade)
4. EXPANSION_HIGH_VOL (Expansão de Volatilidade / Rompimento)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

from core.logger import get_logger
from core.models.market import MarketBar
from core.models.regime import MarketRegimeType, RegimeClassification
from data.features.indicators import calc_adx, calc_atr

logger = get_logger("hmm_regime_detector")


class HMMRegimeDetector:
    """
    Detector de regimes baseado em Cadeias Ocultas de Markov (Gaussian HMM).
    Identifica dinamicamente mudanças estruturais de volatilidade e direção
    calculando probabilidades posteriores e incerteza via Entropia de Shannon.
    """

    def __init__(
        self,
        n_components: int = 4,
        n_iter: int = 150,
        random_state: int = 42,
        uncertainty_entropy_threshold: float = 0.85,
    ) -> None:
        self.n_components = n_components
        self.n_iter = n_iter
        self.random_state = random_state
        self.uncertainty_entropy_threshold = uncertainty_entropy_threshold

        self.model: Optional[GaussianHMM] = None
        self.scaler: StandardScaler = StandardScaler()
        self.state_to_regime: Dict[int, MarketRegimeType] = {}
        self.is_fitted: bool = False

    def extract_features(self, bars: List[MarketBar]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extrai matriz de features quantitativas a partir das barras OHLCV:
        1. Log-retornos
        2. Volatilidade realizada (janela de 20 barras)
        3. ATR ratio (ATR(14) / média(ATR(14)[-20:]))
        4. ADX (força da tendência)

        Retorna (features, valid_indices).
        """
        if len(bars) < 35:
            raise ValueError(f"Barras insuficientes para extração de features HMM: {len(bars)} (mínimo 35)")

        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)

        # 1. Log-retornos
        log_ret = np.zeros(len(closes))
        log_ret[1:] = np.log(closes[1:] / np.maximum(closes[:-1], 1e-9))

        # 2. Volatilidade realizada móvel (desvio padrão de retornos)
        realized_vol = np.zeros(len(closes))
        for i in range(20, len(closes)):
            realized_vol[i] = np.std(log_ret[i - 20 : i])
        if len(closes) > 20:
            realized_vol[:20] = realized_vol[20]

        # 3. ATR e ATR Ratio
        atr = calc_atr(highs, lows, closes, period=14)
        atr_ratio = np.ones(len(closes))
        for i in range(20, len(closes)):
            mean_atr = np.mean(atr[i - 20 : i])
            if mean_atr > 0 and not np.isnan(mean_atr):
                atr_ratio[i] = atr[i] / mean_atr
            else:
                atr_ratio[i] = 1.0

        # 4. ADX
        adx, _, _ = calc_adx(highs, lows, closes, period=14)
        # Substitui NaNs iniciais
        adx_clean = np.nan_to_num(adx, nan=15.0)

        # Combina features
        features = np.column_stack([log_ret, realized_vol, atr_ratio, adx_clean])
        # Despreza as primeiras 25 barras de aquecimento
        warmup = 25
        valid_features = features[warmup:]
        return valid_features, np.arange(warmup, len(bars))

    def fit(self, bars: List[MarketBar]) -> HMMRegimeDetector:
        """
        Ajusta o GaussianHMM aos dados históricos e mapeia os estados latentes
        para os regimes de mercado de forma interpretável.
        """
        if len(bars) < 50:
            raise ValueError(f"Mínimo de 50 barras requerido para treinar HMM, recebido {len(bars)}")

        features, _ = self.extract_features(bars)
        norm_features = self.scaler.fit_transform(features)

        self.model = GaussianHMM(
            n_components=self.n_components,
            covariance_type="full",
            n_iter=self.n_iter,
            random_state=self.random_state,
        )

        try:
            self.model.fit(norm_features)
            self._map_latent_states_to_regimes(features, norm_features)
            self.is_fitted = True
            logger.info("HMMRegimeDetector ajustado com sucesso", extra={"n_states": self.n_components})
        except Exception as e:
            logger.error("Falha ao convergir GaussianHMM", extra={"error": str(e)})
            self.is_fitted = False
            raise

        return self

    def _map_latent_states_to_regimes(self, raw_features: np.ndarray, norm_features: np.ndarray) -> None:
        """
        Mapeia os estados latentes do HMM (0 a 3) para os enums de mercado
        baseando-se nas médias observadas de volatilidade e retorno em cada estado.
        """
        if self.model is None:
            return

        state_predictions = self.model.predict(norm_features)

        state_stats: List[Dict[str, Any]] = []
        for state in range(self.n_components):
            mask = state_predictions == state
            if np.sum(mask) == 0:
                # Estado vazio: preenche com valores neutros
                state_stats.append({
                    "state": state,
                    "mean_ret": 0.0,
                    "volatility": 0.001,
                    "mean_adx": 15.0,
                    "count": 0,
                })
                continue

            state_features = raw_features[mask]
            mean_ret = float(np.mean(state_features[:, 0]))
            vol = float(np.mean(state_features[:, 1]))
            mean_adx = float(np.mean(state_features[:, 3]))

            state_stats.append({
                "state": state,
                "mean_ret": mean_ret,
                "volatility": vol,
                "mean_adx": mean_adx,
                "count": int(np.sum(mask)),
            })

        # 1. O estado com maior volatilidade é EXPANSION_HIGH_VOL
        state_stats_by_vol = sorted(state_stats, key=lambda s: s["volatility"], reverse=True)
        high_vol_state = state_stats_by_vol[0]["state"]
        self.state_to_regime[high_vol_state] = MarketRegimeType.EXPANSION_HIGH_VOL

        remaining = [s for s in state_stats if s["state"] != high_vol_state]

        # 2. Dos restantes, o de menor volatilidade ou menor ADX é RANGING_LOW_VOL
        state_stats_by_range = sorted(remaining, key=lambda s: (s["volatility"], s["mean_adx"]))
        range_state = state_stats_by_range[0]["state"]
        self.state_to_regime[range_state] = MarketRegimeType.RANGING_LOW_VOL

        trend_candidates = [s for s in remaining if s["state"] != range_state]

        # 3. Dos restantes (tendência), o de maior retorno é BULL e o de menor é BEAR
        if len(trend_candidates) >= 2:
            sorted_by_ret = sorted(trend_candidates, key=lambda s: s["mean_ret"])
            bear_state = sorted_by_ret[0]["state"]
            bull_state = sorted_by_ret[-1]["state"]
            self.state_to_regime[bear_state] = MarketRegimeType.TREND_BEAR_STRONG
            self.state_to_regime[bull_state] = MarketRegimeType.TREND_BULL_STRONG
        elif len(trend_candidates) == 1:
            only_state = trend_candidates[0]["state"]
            if trend_candidates[0]["mean_ret"] >= 0:
                self.state_to_regime[only_state] = MarketRegimeType.TREND_BULL_STRONG
            else:
                self.state_to_regime[only_state] = MarketRegimeType.TREND_BEAR_STRONG

    def predict_regime(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: str = "M15",
    ) -> RegimeClassification:
        """
        Classifica o regime atual a partir da barra mais recente calculando:
        - Distribuição de probabilidades posteriores via predict_proba
        - Entropia de Shannon normalizada
        - Verificação de incerteza estocástica
        """
        # Se modelo não estiver treinado ou houver poucas barras, usa fallback gracioso
        if not self.is_fitted or self.model is None or len(bars) < 35:
            return self._heuristic_fallback(bars, symbol, timeframe)

        try:
            features, _ = self.extract_features(bars)
            norm_features = self.scaler.transform(features)

            # Predição de probabilidades de todos os passos
            posteriors = self.model.predict_proba(norm_features)
            latest_posteriors = posteriors[-1]  # Distribuição do passo mais recente

            # Mapeia probabilidades para os enums de regime
            prob_dict: Dict[str, float] = {
                MarketRegimeType.TREND_BULL_STRONG.value: 0.05,
                MarketRegimeType.TREND_BEAR_STRONG.value: 0.05,
                MarketRegimeType.RANGING_LOW_VOL.value: 0.05,
                MarketRegimeType.EXPANSION_HIGH_VOL.value: 0.05,
                MarketRegimeType.UNCERTAIN_TRANSITION.value: 0.05,
            }

            for state_idx, prob in enumerate(latest_posteriors):
                regime = self.state_to_regime.get(state_idx, MarketRegimeType.UNCERTAIN_TRANSITION)
                prob_dict[regime.value] = round(float(prob), 4)

            # Normaliza para garantir soma exata de 1.0
            total_p = sum(prob_dict.values())
            prob_dict = {k: round(v / total_p, 4) for k, v in prob_dict.items()}

            # Entropia de Shannon normalizada: H = -sum(p * log(p)) / log(K)
            p_values = np.array(list(prob_dict.values()))
            valid_p = p_values[p_values > 1e-9]
            entropy = -np.sum(valid_p * np.log(valid_p))
            normalized_entropy = round(float(entropy / np.log(len(prob_dict))), 4)

            # Regime com maior probabilidade
            best_regime_str = max(prob_dict, key=prob_dict.get)  # type: ignore
            active_regime = MarketRegimeType(best_regime_str)
            confidence = prob_dict[best_regime_str]
            is_uncertain = normalized_entropy >= self.uncertainty_entropy_threshold

            return RegimeClassification(
                symbol=symbol,
                timeframe=timeframe,
                active_regime=active_regime,
                probabilities=prob_dict,
                confidence=confidence,
                entropy=normalized_entropy,
                is_uncertain=is_uncertain,
            )

        except Exception as e:
            logger.warning(
                "Falha na inferência do HMM, acionando fallback heurístico",
                extra={"error": str(e), "symbol": symbol},
            )
            return self._heuristic_fallback(bars, symbol, timeframe)

    def _heuristic_fallback(
        self,
        bars: List[MarketBar],
        symbol: str,
        timeframe: str,
    ) -> RegimeClassification:
        """
        Classificador heurístico determinístico fail-safe caso o HMM não esteja disponível.
        """
        if len(bars) < 20:
            return RegimeClassification(
                symbol=symbol,
                timeframe=timeframe,
                active_regime=MarketRegimeType.UNCERTAIN_TRANSITION,
                probabilities={r.value: 0.20 for r in MarketRegimeType},
                confidence=0.20,
                entropy=1.0,
                is_uncertain=True,
            )

        closes = np.array([b.close for b in bars], dtype=float)
        highs = np.array([b.high for b in bars], dtype=float)
        lows = np.array([b.low for b in bars], dtype=float)

        adx, pdi, mdi = calc_adx(highs, lows, closes, 14)
        curr_adx = adx[-1] if not np.isnan(adx[-1]) else 15.0

        atr = calc_atr(highs, lows, closes, 14)
        atr_ratio = (atr[-1] / np.mean(atr[-20:])) if len(atr) >= 20 and np.mean(atr[-20:]) > 0 else 1.0

        if curr_adx >= 25.0 and pdi[-1] > mdi[-1]:
            active_regime = MarketRegimeType.TREND_BULL_STRONG
            conf = 0.65
        elif curr_adx >= 25.0 and mdi[-1] > pdi[-1]:
            active_regime = MarketRegimeType.TREND_BEAR_STRONG
            conf = 0.65
        elif curr_adx < 20.0 and atr_ratio <= 1.1:
            active_regime = MarketRegimeType.RANGING_LOW_VOL
            conf = 0.60
        elif atr_ratio >= 1.4:
            active_regime = MarketRegimeType.EXPANSION_HIGH_VOL
            conf = 0.60
        else:
            active_regime = MarketRegimeType.UNCERTAIN_TRANSITION
            conf = 0.40

        prob_dict = {r.value: 0.10 for r in MarketRegimeType}
        prob_dict[active_regime.value] = conf
        # Normaliza
        total = sum(prob_dict.values())
        prob_dict = {k: round(v / total, 4) for k, v in prob_dict.items()}

        return RegimeClassification(
            symbol=symbol,
            timeframe=timeframe,
            active_regime=active_regime,
            probabilities=prob_dict,
            confidence=conf,
            entropy=0.50,
            is_uncertain=active_regime == MarketRegimeType.UNCERTAIN_TRANSITION,
        )

