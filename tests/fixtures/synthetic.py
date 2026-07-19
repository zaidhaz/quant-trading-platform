"""Deterministic synthetic OHLCV generation for tests — no live network dependency."""

import numpy as np
import pandas as pd


def make_ohlcv(
    n: int = 300,
    start_price: float = 100.0,
    drift: float = 0.0,
    volatility: float = 0.01,
    seed: int = 42,
    start: str = "2024-01-01",
    freq: str = "1h",
) -> pd.DataFrame:
    """Random-walk OHLCV series with an optional per-bar drift (use a positive drift
    for a synthetic uptrend fixture, negative for a downtrend, 0.0 for a chop/range
    fixture)."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=drift, scale=volatility, size=n)
    close = start_price * np.cumprod(1 + returns)

    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1]

    intrabar_noise = rng.normal(loc=0, scale=volatility / 2, size=n)
    high = np.maximum(open_, close) * (1 + np.abs(intrabar_noise))
    low = np.minimum(open_, close) * (1 - np.abs(intrabar_noise))
    volume = rng.uniform(10, 100, size=n)

    index = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
