"""Local columnar storage for historical market data.

Chosen over round-tripping through Postgres for the research engine's read pattern:
the same symbol/timeframe range gets read repeatedly across many backtest and
optimization runs, and Parquet-on-disk with pandas is dramatically faster for that
than a DB round trip, with no infra dependency (no running Postgres needed just to
backtest). Postgres remains the system of record for research *outputs* (signals,
backtest results, journal) — see docs/ARCHITECTURE.md Revision 2.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.types import Symbol


class ParquetStore:
    """Partitioned by dataset/exchange/symbol[/timeframe]. One Parquet file per leaf."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, dataset: str, symbol: Symbol, timeframe: str | None) -> Path:
        parts = [dataset, symbol.exchange, symbol.native()]
        if timeframe is not None:
            parts.append(f"{timeframe}.parquet")
        else:
            parts[-1] = f"{parts[-1]}.parquet"
        return self.root.joinpath(*parts)

    def read(
        self, dataset: str, symbol: Symbol, timeframe: str | None = None
    ) -> pd.DataFrame | None:
        path = self._path(dataset, symbol, timeframe)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def write(
        self, dataset: str, symbol: Symbol, df: pd.DataFrame, timeframe: str | None = None
    ) -> None:
        """Merge `df` into whatever is already stored: concat, dedup on index, sort."""
        if df.empty:
            return
        path = self._path(dataset, symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = self.read(dataset, symbol, timeframe)
        combined = pd.concat([existing, df]) if existing is not None else df
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        combined.to_parquet(path)

    def date_range(
        self, dataset: str, symbol: Symbol, timeframe: str | None = None
    ) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        df = self.read(dataset, symbol, timeframe)
        if df is None or df.empty:
            return None
        return df.index.min(), df.index.max()
