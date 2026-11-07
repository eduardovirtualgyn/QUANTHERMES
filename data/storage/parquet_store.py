"""
QUANT HERMES — Armazenamento Histórico de Dados em Parquet
Módulo: data.storage.parquet_store
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.models.market import MarketBar, MarketTick, TimeFrame


class HistoricalDataStore:
    """
    Repositório colunar em formato Apache Parquet para persistência de dados históricos.
    Oferece:
    1. Armazenamento particionado por ativo e timeframe.
    2. Deduplicação e ordenação estrita por timestamp.
    3. Consultas Ponto-no-Tempo (Point-in-Time) com garantia matemática contra Lookahead Bias.
    """

    def __init__(self, base_dir: str | Path = "data/storage"):
        self.base_dir = Path(base_dir)
        self.bars_dir = self.base_dir / "bars"
        self.ticks_dir = self.base_dir / "ticks"
        self.bars_dir.mkdir(parents=True, exist_ok=True)
        self.ticks_dir.mkdir(parents=True, exist_ok=True)

    def _get_bar_path(self, symbol: str, timeframe: TimeFrame) -> Path:
        sym_dir = self.bars_dir / symbol
        sym_dir.mkdir(parents=True, exist_ok=True)
        return sym_dir / f"{timeframe.value}.parquet"

    def save_bars(self, symbol: str, timeframe: TimeFrame, bars: List[MarketBar]) -> int:
        """Salva ou concatena novas barras ao arquivo Parquet, deduplicando por timestamp."""
        if not bars:
            return 0

        file_path = self._get_bar_path(symbol, timeframe)

        records = [
            {
                "symbol": b.symbol,
                "timeframe": b.timeframe.value,
                "time": b.time,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "tick_volume": b.tick_volume,
                "spread": b.spread,
                "is_closed": b.is_closed,
            }
            for b in bars
        ]
        new_df = pd.DataFrame(records)
        new_df["time"] = pd.to_datetime(new_df["time"], utc=True)

        if file_path.exists():
            existing_df = pd.read_parquet(file_path)
            existing_df["time"] = pd.to_datetime(existing_df["time"], utc=True)
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=["time"], keep="last")
        else:
            combined_df = new_df.drop_duplicates(subset=["time"], keep="last")

        combined_df = combined_df.sort_values(by="time").reset_index(drop=True)
        combined_df.to_parquet(file_path, index=False, engine="pyarrow")
        return len(combined_df)

    def load_bars(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[MarketBar]:
        """Carrega barras filtradas por intervalo de datas."""
        file_path = self._get_bar_path(symbol, timeframe)
        if not file_path.exists():
            return []

        df = pd.read_parquet(file_path)
        df["time"] = pd.to_datetime(df["time"], utc=True)

        if start_time:
            st = pd.Timestamp(start_time).tz_convert("UTC") if start_time.tzinfo else pd.Timestamp(start_time).tz_localize("UTC")
            df = df[df["time"] >= st]
        if end_time:
            et = pd.Timestamp(end_time).tz_convert("UTC") if end_time.tzinfo else pd.Timestamp(end_time).tz_localize("UTC")
            df = df[df["time"] <= et]

        return self._df_to_bars(df)

    def get_bars_as_of(
        self,
        symbol: str,
        timeframe: TimeFrame,
        as_of: datetime,
        count: int = 100,
    ) -> List[MarketBar]:
        """
        Consulta Ponto-no-Tempo (Point-in-Time).
        GARANTIA ANTI-LOOKAHEAD: Retorna exclusivamente barras com timestamp <= as_of.
        Nenhum dado futuro pode vazar para os modelos nesta consulta.
        """
        file_path = self._get_bar_path(symbol, timeframe)
        if not file_path.exists():
            return []

        df = pd.read_parquet(file_path)
        df["time"] = pd.to_datetime(df["time"], utc=True)

        as_of_ts = pd.Timestamp(as_of).tz_convert("UTC") if as_of.tzinfo else pd.Timestamp(as_of).tz_localize("UTC")
        historical_df = df[df["time"] <= as_of_ts]

        if count and len(historical_df) > count:
            historical_df = historical_df.tail(count)

        return self._df_to_bars(historical_df)

    def _df_to_bars(self, df: pd.DataFrame) -> List[MarketBar]:
        bars = []
        for _, row in df.iterrows():
            ts = row["time"].to_pydatetime()
            bars.append(
                MarketBar(
                    symbol=row["symbol"],
                    timeframe=TimeFrame(row["timeframe"]),
                    time=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    tick_volume=int(row["tick_volume"]),
                    spread=int(row["spread"]),
                    is_closed=bool(row["is_closed"]),
                )
            )
        return bars

