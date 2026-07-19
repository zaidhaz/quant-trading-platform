"""OHLCV sanity validation — the gate every path into the backtest engine goes
through (`DataFeed.from_candles`, and therefore `DataFeed.load()` too).

This exists to make the engine fail loudly and immediately on malformed data
instead of letting it propagate into silently misleading results: a duplicate or
out-of-order timestamp corrupts anything that does label-based slicing
(`optimization.walk_forward`'s window slicing, `analytics.monthly_returns`'s
resampling) or assumes elapsed time tracks bar count (holding-time calculations);
a NaN or non-positive price poisons every indicator computed from it and can
silently short-circuit signal generation for the rest of a run (every strategy
hook that touches `InsufficientDataError` would just quietly stop firing, not
raise); a high < low or an open/close outside [low, high] is not a real candle and
downstream code (stop/take-profit resolution, slippage clamping) assumes it is.

Deliberately *not* checked here: gaps (missing bars). That's the domain of
`market_data.historical.dataset.HistoricalDataset.ensure_range()`, which is strict
by default but has an explicit, intentional `allow_gaps=True` escape hatch for
callers who know what they're doing (e.g. funding-rate enrichment data). Gating
gaps here too would break that intentional path.
"""

from __future__ import annotations

import pandas as pd

from core.exceptions import ValidationError

_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
_PRICE_TOLERANCE = 1e-9  # float slop allowance for the open/close-within-range check


def validate_candles(df: pd.DataFrame, *, context: str = "candles") -> None:
    """Raises ValidationError on the first problem found. No-op on an empty
    DataFrame (nothing to validate; an empty feed is a separate, valid state)."""
    if df.empty:
        return

    missing_columns = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ValidationError(f"{context}: missing required column(s) {missing_columns}")

    if not df.index.is_unique:
        dupes = df.index[df.index.duplicated()].unique()
        raise ValidationError(f"{context}: duplicate timestamp(s) in index, e.g. {list(dupes[:3])}")
    if not df.index.is_monotonic_increasing:
        raise ValidationError(f"{context}: timestamps are not in increasing order")

    prices = df[["open", "high", "low", "close"]]
    if prices.isna().any().any():
        bad_cols = prices.columns[prices.isna().any()].tolist()
        raise ValidationError(f"{context}: NaN price value(s) in column(s) {bad_cols}")
    if df["volume"].isna().any():
        raise ValidationError(f"{context}: NaN volume value(s)")

    if (prices <= 0).any().any():
        bad_cols = prices.columns[(prices <= 0).any()].tolist()
        raise ValidationError(f"{context}: non-positive price value(s) in column(s) {bad_cols}")
    if (df["volume"] < 0).any():
        raise ValidationError(f"{context}: negative volume value(s)")

    if (df["high"] < df["low"]).any():
        raise ValidationError(f"{context}: high < low on at least one bar")

    out_of_range = (df["open"] < df["low"] - _PRICE_TOLERANCE) | (
        df["open"] > df["high"] + _PRICE_TOLERANCE
    )
    if out_of_range.any():
        raise ValidationError(f"{context}: open price outside [low, high] on at least one bar")

    out_of_range = (df["close"] < df["low"] - _PRICE_TOLERANCE) | (
        df["close"] > df["high"] + _PRICE_TOLERANCE
    )
    if out_of_range.any():
        raise ValidationError(f"{context}: close price outside [low, high] on at least one bar")
