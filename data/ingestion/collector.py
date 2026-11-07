"""
QUANT HERMES — Coletor e Validador de Dados de Mercado
Módulo: data.ingestion.collector
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from core.event_bus import EventPriority, PrioritizedEventBus
from core.logger import log
from core.models.market import MarketBar, MarketTick, TimeFrame
from execution.adapters.base import TradingPlatformAdapter

_TIMEFRAME_SECONDS = {
    TimeFrame.M1: 60,
    TimeFrame.M5: 300,
    TimeFrame.M15: 900,
    TimeFrame.H1: 3600,
    TimeFrame.H4: 14400,
    TimeFrame.D1: 86400,
}


class MarketDataCollector:
    """
    Motor de ingestão, sanitização e validação de dados de mercado.
    Garante:
    1. Filtragem estrita de ticks anômalos (Ask < Bid, valores negativos/nulos).
    2. Deduplicação em memória de ticks idênticos.
    3. Detecção de lacunas (gaps) no fluxo temporal de barras OHLCV.
    4. Propagação via EventBus com prioridade de telemetria.
    """

    def __init__(
        self,
        adapter: TradingPlatformAdapter,
        event_bus: Optional[PrioritizedEventBus] = None,
    ):
        self._adapter = adapter
        self._event_bus = event_bus
        self._last_ticks: Dict[str, MarketTick] = {}
        self._last_bar_times: Dict[Tuple[str, TimeFrame], datetime] = {}
        self._detected_gaps: List[Dict[str, Any]] = []

    async def ingest_tick(self, tick: MarketTick) -> bool:
        """
        Valida, filtra e processa um novo tick.
        Retorna True se o tick for válido e inédito, False se for duplicado ou anômalo.
        """
        # 1. Filtro de sanidade
        if tick.bid <= 0.0 or tick.ask <= 0.0 or tick.ask < tick.bid:
            log.warning("Tick rejeitado por preço anômalo", symbol=tick.symbol, bid=tick.bid, ask=tick.ask)
            return False

        # 2. Filtro de duplicidade
        last_tick = self._last_ticks.get(tick.symbol)
        if last_tick and last_tick.time == tick.time and last_tick.bid == tick.bid and last_tick.ask == tick.ask:
            return False  # Tick duplicado descartado silenciosamente

        self._last_ticks[tick.symbol] = tick

        # 3. Publica no EventBus se configurado
        if self._event_bus:
            await self._event_bus.publish(
                event_type=f"market.tick.{tick.symbol}",
                payload=tick,
                priority=EventPriority.TELEMETRY,
                source="market_data_collector",
            )

        return True

    async def ingest_bars(self, bars: List[MarketBar]) -> int:
        """
        Valida e ingere uma lista de barras OHLCV, verificando lacunas temporais.
        Retorna a quantidade de barras válidas processadas.
        """
        if not bars:
            return 0

        valid_count = 0
        for bar in bars:
            key = (bar.symbol, bar.timeframe)
            expected_step = _TIMEFRAME_SECONDS.get(bar.timeframe, 300)

            last_time = self._last_bar_times.get(key)
            if last_time:
                delta_sec = (bar.time - last_time).total_seconds()
                # Se o salto temporal for maior que 1.5x o período esperado, registra um Gap
                if delta_sec > expected_step * 1.5:
                    gap_info = {
                        "symbol": bar.symbol,
                        "timeframe": bar.timeframe.value,
                        "from": last_time.isoformat(),
                        "to": bar.time.isoformat(),
                        "missing_seconds": delta_sec,
                    }
                    self._detected_gaps.append(gap_info)
                    log.warning("Lacuna temporal detectada nas barras", **gap_info)

            self._last_bar_times[key] = bar.time
            valid_count += 1

            if self._event_bus:
                await self._event_bus.publish(
                    event_type=f"market.bar.{bar.symbol}.{bar.timeframe.value}",
                    payload=bar,
                    priority=EventPriority.TELEMETRY,
                    source="market_data_collector",
                )

        return valid_count

    def get_detected_gaps(self) -> List[Dict[str, Any]]:
        """Retorna histórico de lacunas temporais identificadas."""
        return list(self._detected_gaps)
