"""Synthetic OHLCV + funding-rate history generator.

Exists ONLY because this sandbox cannot reach `fapi.binance.com` (see
`research/__init__.py`). Produces *plausible, regime-structured* data — not
an attempt to reproduce actual BTC/ETH price history, which is impossible
without the real feed. Every regime segment (bull/bear/range x high/low
volatility, with a correlated funding-rate bias) is deterministic given the
symbol, so re-running this module always reproduces the same dataset.

Limitation stated once here rather than at every call site: each
(symbol, timeframe) series is generated independently at its own bar
frequency — the 1h and 1m series for the same symbol are NOT resampled from
a shared intrabar path, so they do not agree bar-for-bar the way a real
multi-resolution feed would. That level of self-consistency isn't needed for
what this exercise can actually validate (the analysis methodology), and
building it would spend effort on realism no amount of which makes this
real market history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zlib import crc32

import numpy as np
import pandas as pd

from analytics.performance_metrics import periods_per_year
from core.constants import TIMEFRAME_TO_MINUTES

# Binance USDⓈ-M Futures perpetual listing dates, from general background
# knowledge only — NOT fetched live (the API is unreachable from here) and
# NOT independently verified against an exchange record in this run. Treat
# as an approximate, stated assumption, not a confirmed fact. If the real
# dates differ, re-running the (currently unreachable) real downloader would
# naturally produce the correct range with no code changes needed here.
ASSUMED_LISTING_DATE: dict[str, datetime] = {
    "BTCUSDT": datetime(2019, 9, 8, tzinfo=UTC),
    "ETHUSDT": datetime(2019, 11, 27, tzinfo=UTC),
}

_START_PRICE: dict[str, float] = {"BTCUSDT": 10000.0, "ETHUSDT": 200.0}
_BASE_VOLUME: dict[str, float] = {"BTCUSDT": 2000.0, "ETHUSDT": 15000.0}

_REGIME_KINDS = ("bull", "bear", "range")
_REGIME_KIND_PROBS = (0.35, 0.25, 0.40)
_VOL_LEVELS = ("high", "low")
_VOL_LEVEL_PROBS = (0.35, 0.65)


@dataclass(frozen=True, slots=True)
class RegimeSegment:
    start: pd.Timestamp
    end: pd.Timestamp
    kind: str  # "bull" | "bear" | "range"
    volatility: str  # "high" | "low"
    drift_annual: float
    vol_annual: float
    funding_bias: float  # per-8h-interval funding rate bias for this segment


def _symbol_seed(symbol: str, salt: str = "") -> int:
    return crc32(f"{symbol}:{salt}".encode()) & 0xFFFFFFFF


def build_regime_schedule(
    symbol: str, start: pd.Timestamp, end: pd.Timestamp
) -> list[RegimeSegment]:
    """Deterministic (seeded off `symbol` only, not off time or timeframe) so
    price and funding generation for the same symbol always share the exact
    same regime blocks — required for Phase 4's regime analysis and the
    funding-rate/trend correlation it looks for to be internally consistent."""
    rng = np.random.default_rng(_symbol_seed(symbol, "regime"))
    segments: list[RegimeSegment] = []
    cursor = start
    while cursor < end:
        duration_days = float(rng.uniform(20, 150))
        seg_end = min(cursor + pd.Timedelta(days=duration_days), end)
        kind = str(rng.choice(_REGIME_KINDS, p=_REGIME_KIND_PROBS))
        vol = str(rng.choice(_VOL_LEVELS, p=_VOL_LEVEL_PROBS))
        drift_annual = {
            "bull": float(rng.uniform(0.3, 1.5)),
            "bear": float(rng.uniform(-1.2, -0.2)),
            "range": float(rng.uniform(-0.1, 0.1)),
        }[kind]
        vol_annual = {
            "high": float(rng.uniform(0.8, 1.6)),
            "low": float(rng.uniform(0.3, 0.7)),
        }[vol]
        funding_bias = {
            "bull": float(rng.uniform(0.0003, 0.0015)),
            "bear": float(rng.uniform(-0.0015, -0.0001)),
            "range": float(rng.uniform(-0.0002, 0.0002)),
        }[kind]
        segments.append(
            RegimeSegment(cursor, seg_end, kind, vol, drift_annual, vol_annual, funding_bias)
        )
        cursor = seg_end
    return segments


def _segment_index(schedule: list[RegimeSegment], timestamps: pd.DatetimeIndex) -> np.ndarray:
    seg_starts = np.array([s.start.value for s in schedule])
    idx = np.searchsorted(seg_starts, timestamps.values.astype("int64"), side="right") - 1
    return np.clip(idx, 0, len(schedule) - 1)


def generate_ohlcv(symbol: str, timeframe: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Regime-conditioned geometric random walk at the requested bar frequency,
    with rare fat-tail shocks (flash-crash-like single-bar moves) and
    regime-scaled volume. Deterministic given (symbol, timeframe, start, end).
    """
    bar_minutes = TIMEFRAME_TO_MINUTES[timeframe]
    index = pd.date_range(start, end, freq=f"{bar_minutes}min", tz="UTC", inclusive="left")
    n = len(index)
    if n == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    schedule = build_regime_schedule(symbol, pd.Timestamp(start), pd.Timestamp(end))
    seg_idx = _segment_index(schedule, index)
    drift_annual = np.array([schedule[i].drift_annual for i in seg_idx])
    vol_annual = np.array([schedule[i].vol_annual for i in seg_idx])

    ppy = periods_per_year(timeframe)
    mu = drift_annual / ppy - 0.5 * (vol_annual**2) / ppy  # log-return drift, Ito-corrected
    sigma = vol_annual / np.sqrt(ppy)

    rng = np.random.default_rng(_symbol_seed(symbol, f"ohlcv:{timeframe}"))
    log_returns = rng.normal(mu, sigma)
    shock_mask = rng.random(n) < 0.0005
    if shock_mask.any():
        log_returns[shock_mask] += rng.normal(0.0, sigma[shock_mask] * 8.0)

    start_price = _START_PRICE.get(symbol, 100.0)
    close = start_price * np.exp(np.cumsum(log_returns))
    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1]

    intrabar_scale = sigma * 0.6
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0.0, intrabar_scale)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0.0, intrabar_scale)))

    base_volume = _BASE_VOLUME.get(symbol, 1000.0)
    vol_scale = np.where(vol_annual >= 1.0, 1.6, 1.0)
    volume = base_volume * vol_scale * np.abs(rng.lognormal(mean=0.0, sigma=0.5, size=n))

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )
    df.index.name = "ts"
    df["high"] = df[["open", "high", "close", "low"]].max(axis=1)
    df["low"] = df[["open", "low", "close", "high"]].min(axis=1)
    return df


def generate_funding(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """8-hourly funding rate, correlated with the same regime schedule used for
    price (see `build_regime_schedule`) plus independent noise, clipped to a
    realistic Binance-like range."""
    index = pd.date_range(start, end, freq="8h", tz="UTC", inclusive="left")
    n = len(index)
    if n == 0:
        return pd.DataFrame(columns=["funding_rate", "mark_price"])

    schedule = build_regime_schedule(symbol, pd.Timestamp(start), pd.Timestamp(end))
    seg_idx = _segment_index(schedule, index)
    bias = np.array([schedule[i].funding_bias for i in seg_idx])

    rng = np.random.default_rng(_symbol_seed(symbol, "funding"))
    noise = rng.normal(0.0, 0.0002, n)
    funding_rate = np.clip(bias + noise, -0.0075, 0.0075)

    df = pd.DataFrame({"funding_rate": funding_rate, "mark_price": np.nan}, index=index)
    df.index.name = "ts"
    return df


def dataset_summary(symbol: str, timeframe: str, df: pd.DataFrame) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": len(df),
        "start": df.index.min().isoformat() if not df.empty else None,
        "end": df.index.max().isoformat() if not df.empty else None,
        "assumed_listing_date": ASSUMED_LISTING_DATE.get(symbol),
        "source": "SYNTHETIC — see research/__init__.py",
    }
