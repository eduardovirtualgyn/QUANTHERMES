"""
QUANT HERMES — Monitor de Correlação e Concentração de Exposição
Módulo: portfolio.correlation
"""
from __future__ import annotations

from typing import List, Optional, Tuple
from core.logger import get_logger
from core.models.risk import Position

logger = get_logger("portfolio.correlation")

# Matriz empírica inicial de correlação interativos (Forex e Metais)
_DEFAULT_CORRELATIONS: dict[Tuple[str, str], float] = {
    ("EURUSD", "GBPUSD"): 0.82,
    ("EURUSD", "USDJPY"): -0.45,
    ("EURUSD", "XAUUSD"): 0.65,
    ("GBPUSD", "USDJPY"): -0.40,
    ("GBPUSD", "XAUUSD"): 0.55,
    ("USDJPY", "XAUUSD"): -0.35,
}

# Mapeamento de direção da moeda USD por símbolo e ação
# Permite detectar concentração oculta no Dólar
_USD_DIRECTION_MAP: dict[Tuple[str, str], str] = {
    ("EURUSD", "BUY"): "SHORT_USD",
    ("EURUSD", "SELL"): "LONG_USD",
    ("GBPUSD", "BUY"): "SHORT_USD",
    ("GBPUSD", "SELL"): "LONG_USD",
    ("XAUUSD", "BUY"): "SHORT_USD",
    ("XAUUSD", "SELL"): "LONG_USD",
    ("USDJPY", "BUY"): "LONG_USD",
    ("USDJPY", "SELL"): "SHORT_USD",
}


class CorrelationMonitor:
    """
    Monitor de correlação e exposição cambial do portfólio.
    Garante:
    1. Bloqueio de posições altamente correlacionadas (> max_correlation_threshold).
    2. Controle de concentração direcional na moeda USD (máximo de pares correlacionados).
    3. Proteção contra risco de cauda por contágio de ativos com exposição idêntica.
    """

    def __init__(
        self,
        max_correlation_threshold: float = 0.70,
        max_correlated_pairs_open: int = 2,
        correlation_matrix: Optional[dict[Tuple[str, str], float]] = None,
    ):
        self.max_correlation_threshold = max_correlation_threshold
        self.max_correlated_pairs_open = max_correlated_pairs_open
        self._matrix = correlation_matrix or _DEFAULT_CORRELATIONS.copy()

    def get_correlation(self, symbol_a: str, symbol_b: str) -> float:
        """Retorna o coeficiente de correlação de Pearson entre dois ativos (-1.0 a +1.0)."""
        sym_a = symbol_a.upper()
        sym_b = symbol_b.upper()
        if sym_a == sym_b:
            return 1.0

        if (sym_a, sym_b) in self._matrix:
            return self._matrix[(sym_a, sym_b)]
        if (sym_b, sym_a) in self._matrix:
            return self._matrix[(sym_b, sym_a)]

        return 0.0

    def update_correlation(self, symbol_a: str, symbol_b: str, value: float) -> None:
        """Atualiza dinamicamente o coeficiente de correlação estimado por modelos quantitativos."""
        clamped_val = max(-1.0, min(1.0, value))
        self._matrix[(symbol_a.upper(), symbol_b.upper())] = round(clamped_val, 4)

    def check_correlation_limit(
        self,
        proposed_symbol: str,
        proposed_action: str,
        open_positions: List[Position],
    ) -> Tuple[bool, Optional[str]]:
        """
        Avalia se a nova operação proposta viola os limites de correlação com as posições abertas.
        """
        if not open_positions:
            return True, None

        correlated_count = 0
        correlated_symbols = []

        proposed_usd_dir = _USD_DIRECTION_MAP.get((proposed_symbol.upper(), proposed_action.upper()))

        for pos in open_positions:
            # Não compara com posições no mesmo ativo (já bloqueado pelo RiskEngine)
            if pos.symbol.upper() == proposed_symbol.upper():
                continue

            corr = self.get_correlation(proposed_symbol, pos.symbol)

            # Caso 1: Correlação direta positiva elevada na mesma direção
            # Ex: BUY EURUSD e BUY GBPUSD (ambos BUY com correlação 0.82)
            if corr >= self.max_correlation_threshold and proposed_action == pos.position_type:
                correlated_count += 1
                correlated_symbols.append(f"{pos.symbol} (corr={corr:+.2f})")

            # Caso 2: Correlação inversa negativa elevada em direções opostas
            # Ex: BUY EURUSD e SELL USDJPY
            elif corr <= -self.max_correlation_threshold and proposed_action != pos.position_type:
                correlated_count += 1
                correlated_symbols.append(f"{pos.symbol} (corr={corr:+.2f})")

            # Caso 3: Concentração pura de USD no mesmo vetor
            pos_usd_dir = _USD_DIRECTION_MAP.get((pos.symbol.upper(), pos.position_type.upper()))
            if (
                proposed_usd_dir is not None
                and pos_usd_dir is not None
                and proposed_usd_dir == pos_usd_dir
                and abs(corr) >= 0.50
            ):
                if f"{pos.symbol}" not in str(correlated_symbols):
                    correlated_count += 1
                    correlated_symbols.append(f"{pos.symbol} [{pos_usd_dir}]")

        if correlated_count >= self.max_correlated_pairs_open:
            reason = (
                f"CORRELATION_LIMIT_EXCEEDED: Operação em {proposed_symbol} {proposed_action} "
                f"excederia o limite de {self.max_correlated_pairs_open} pares correlacionados. "
                f"Pares conflitantes: {', '.join(correlated_symbols)}"
            )
            logger.warning("correlation_check_failed", reason=reason)
            return False, reason

        return True, None
