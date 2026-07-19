"""Swing points, liquidity pools (equal highs/lows), sweep-and-reclaim, and the
Break-of-Structure / Change-of-Character state machine.

Every function here is pure (`DataFrame -> Series/DataFrame`) and causal: the
value at row `i` depends only on rows `<= i`. That makes each one directly
unit-testable against hand-built DataFrames, and safe to run once over a
whole historical series the same way `features/feature_engine.py` runs its
built-in indicators (see that module's docstring on why a full-series
vectorized/loop pass is not look-ahead bias).

See docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md §§1.2-1.3, 2.1-2.3 for
the research justification and exact math each function implements.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def swing_highs(df: pd.DataFrame, fractal_width: int = 2) -> pd.Series:
    """True at bar k if high[k] is the max of the `fractal_width` bars on each
    side (a standard fractal/pivot high). Only *knowable* `fractal_width` bars
    later, at k + fractal_width -- callers must respect that confirmation lag,
    never read this at face value for the current bar."""
    high = df["high"]
    window = 2 * fractal_width + 1
    centered_max = high.rolling(window, center=True, min_periods=window).max()
    is_swing = (high == centered_max) & centered_max.notna()
    return is_swing.fillna(False)


def swing_lows(df: pd.DataFrame, fractal_width: int = 2) -> pd.Series:
    low = df["low"]
    window = 2 * fractal_width + 1
    centered_min = low.rolling(window, center=True, min_periods=window).min()
    is_swing = (low == centered_min) & centered_min.notna()
    return is_swing.fillna(False)


def compute_structure(df: pd.DataFrame, fractal_width: int = 2) -> pd.DataFrame:
    """Break of Structure (BoS, continuation) / Change of Character (ChoCH,
    first countertrend break) -- see docs §1.3, §2.3. One forward pass:
    tracks the most recently confirmed swing high/low and a running
    `direction`; a break beyond the tracked level *in* `direction` is BoS, a
    break *against* it is ChoCH and flips `direction`. The very first break
    ever observed only bootstraps `direction` (there is no "prevailing
    structure" yet for it to agree or disagree with), so it fires neither
    flag -- this matches the definition, it is not an omission.

    Columns: `direction` (1.0 up / -1.0 down / 0.0 undetermined), `bos_up`,
    `bos_down`, `choch_up`, `choch_down` (0.0/1.0), `last_swing_high`,
    `last_swing_low` (float, NaN until one exists).
    """
    sh = swing_highs(df, fractal_width)
    sl = swing_lows(df, fractal_width)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    n = len(df)

    direction = np.zeros(n)
    bos_up = np.zeros(n)
    bos_down = np.zeros(n)
    choch_up = np.zeros(n)
    choch_down = np.zeros(n)
    last_swing_high = np.full(n, np.nan)
    last_swing_low = np.full(n, np.nan)

    cur_high: float | None = None
    cur_low: float | None = None
    high_broken = True  # nothing to break yet
    low_broken = True
    cur_direction = 0.0

    for i in range(n):
        k = i - fractal_width
        if k >= 0:
            if bool(sh.iat[k]):
                cur_high = float(high[k])
                high_broken = False
            if bool(sl.iat[k]):
                cur_low = float(low[k])
                low_broken = False

        if cur_high is not None and not high_broken and close[i] > cur_high:
            high_broken = True
            if cur_direction == 0.0:
                cur_direction = 1.0
            elif cur_direction == 1.0:
                bos_up[i] = 1.0
            else:
                choch_up[i] = 1.0
                cur_direction = 1.0

        if cur_low is not None and not low_broken and close[i] < cur_low:
            low_broken = True
            if cur_direction == 0.0:
                cur_direction = -1.0
            elif cur_direction == -1.0:
                bos_down[i] = 1.0
            else:
                choch_down[i] = 1.0
                cur_direction = -1.0

        direction[i] = cur_direction
        if cur_high is not None:
            last_swing_high[i] = cur_high
        if cur_low is not None:
            last_swing_low[i] = cur_low

    return pd.DataFrame(
        {
            "direction": direction,
            "bos_up": bos_up,
            "bos_down": bos_down,
            "choch_up": choch_up,
            "choch_down": choch_down,
            "last_swing_high": last_swing_high,
            "last_swing_low": last_swing_low,
        },
        index=df.index,
    )


def _cluster_prices(prices: list[float], tolerance: float) -> list[tuple[float, int]]:
    """Single-linkage clustering of nearby prices: sort, then chain-merge any
    price within `tolerance` of the previous one in the same cluster. Returns
    (cluster_mean, touch_count) pairs."""
    if not prices:
        return []
    ordered = sorted(prices)
    clusters: list[list[float]] = [[ordered[0]]]
    for price in ordered[1:]:
        if price - clusters[-1][-1] <= tolerance:
            clusters[-1].append(price)
        else:
            clusters.append([price])
    return [(sum(c) / len(c), len(c)) for c in clusters]


def _nearest_qualifying_cluster(
    prices: list[float], tolerance: float, min_touches: int, reference: float, side: str
) -> tuple[float | None, int]:
    clusters = _cluster_prices(prices, tolerance)
    candidates = [
        (level, count)
        for level, count in clusters
        if count >= min_touches
        and ((side == "below" and level < reference) or (side == "above" and level > reference))
    ]
    if not candidates:
        return None, 0
    level, count = min(candidates, key=lambda lc: abs(lc[0] - reference))
    return level, count


def compute_liquidity_pools(
    df: pd.DataFrame,
    atr: pd.Series,
    fractal_width: int = 2,
    tolerance_atr_mult: float = 0.15,
    min_touches: int = 2,
    pool_lookback_bars: int = 100,
) -> pd.DataFrame:
    """Nearest support/resistance liquidity pool as of each bar -- see docs
    §1.2, §2.2. A pool is a cluster of `>= min_touches` confirmed swing
    highs/lows within `tolerance_atr_mult * ATR` of each other, formed within
    the trailing `pool_lookback_bars`. "Nearest" = closest cluster to that
    bar's close on the qualifying side (below close for support, above for
    resistance) -- the most locally relevant resting-liquidity level.

    Columns: `support_level`, `support_touches`, `resistance_level`,
    `resistance_touches` (NaN / 0 where no qualifying pool exists yet).
    """
    sh = swing_highs(df, fractal_width)
    sl = swing_lows(df, fractal_width)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    atr_arr = atr.to_numpy()
    n = len(df)

    support_level = np.full(n, np.nan)
    support_touches = np.zeros(n)
    resistance_level = np.full(n, np.nan)
    resistance_touches = np.zeros(n)

    confirmed_highs: list[tuple[int, float]] = []
    confirmed_lows: list[tuple[int, float]] = []

    for i in range(n):
        k = i - fractal_width
        if k >= 0:
            if bool(sh.iat[k]):
                confirmed_highs.append((k, float(high[k])))
            if bool(sl.iat[k]):
                confirmed_lows.append((k, float(low[k])))

        cutoff = i - pool_lookback_bars
        if confirmed_highs and confirmed_highs[0][0] < cutoff:
            confirmed_highs = [(idx, p) for idx, p in confirmed_highs if idx >= cutoff]
        if confirmed_lows and confirmed_lows[0][0] < cutoff:
            confirmed_lows = [(idx, p) for idx, p in confirmed_lows if idx >= cutoff]

        tol = tolerance_atr_mult * atr_arr[i]
        if np.isnan(tol) or tol <= 0:
            continue

        r_level, r_touches = _nearest_qualifying_cluster(
            [p for _, p in confirmed_highs], tol, min_touches, close[i], "above"
        )
        if r_level is not None:
            resistance_level[i] = r_level
            resistance_touches[i] = r_touches

        s_level, s_touches = _nearest_qualifying_cluster(
            [p for _, p in confirmed_lows], tol, min_touches, close[i], "below"
        )
        if s_level is not None:
            support_level[i] = s_level
            support_touches[i] = s_touches

    return pd.DataFrame(
        {
            "support_level": support_level,
            "support_touches": support_touches,
            "resistance_level": resistance_level,
            "resistance_touches": resistance_touches,
        },
        index=df.index,
    )


def compute_sweeps(
    df: pd.DataFrame,
    atr: pd.Series,
    pools: pd.DataFrame,
    sweep_margin_atr_mult: float = 0.1,
    reclaim_window_bars: int = 3,
) -> pd.DataFrame:
    """Sweep-and-reclaim events -- see docs §1.1, §2.1. Fires on the bar the
    reclaim is *first* confirmed (no look-ahead: by that bar both the sweep
    and the reclaim have already happened). The pool level used is anchored
    at `i - reclaim_window_bars`, i.e. the pool must already exist before the
    earliest bar the sweep could have started on -- deliberately excludes the
    degenerate case where the "pool" is partly made of the sweep itself.

    Columns: `sweep_low_active`, `sweep_low_extreme`, `sweep_low_bars_ago`,
    `sweep_low_pool_touches` and the symmetric `sweep_high_*` columns.
    `*_active` is 0.0/1.0; `*_extreme` is the swept bar's low/high (used for
    hypothesis-invalidation stop placement, §1.12); `*_bars_ago` is how many
    bars before the reclaim bar the sweep extreme printed.
    """
    close = df["close"].to_numpy()
    low = df["low"].to_numpy()
    high = df["high"].to_numpy()
    atr_arr = atr.to_numpy()
    support_level = pools["support_level"].to_numpy()
    support_touches = pools["support_touches"].to_numpy()
    resistance_level = pools["resistance_level"].to_numpy()
    resistance_touches = pools["resistance_touches"].to_numpy()
    n = len(df)

    sweep_low_active = np.zeros(n)
    sweep_low_extreme = np.full(n, np.nan)
    sweep_low_bars_ago = np.full(n, np.nan)
    sweep_low_pool_touches = np.full(n, np.nan)
    sweep_low_pool_level = np.full(n, np.nan)

    sweep_high_active = np.zeros(n)
    sweep_high_extreme = np.full(n, np.nan)
    sweep_high_bars_ago = np.full(n, np.nan)
    sweep_high_pool_touches = np.full(n, np.nan)
    sweep_high_pool_level = np.full(n, np.nan)

    for i in range(n):
        anchor = max(i - reclaim_window_bars, 0)
        lo = max(i - reclaim_window_bars, 0)

        support = support_level[anchor]
        if not np.isnan(support) and close[i] > support:
            # "Already reclaimed" means bar i-1 *itself* already fired this signal --
            # not merely that close[i-1] also happened to sit above the pool (true of
            # almost every bar in a market that trades well above its support pool,
            # which would otherwise suppress a legitimate same-bar wick-and-reclaim).
            already_reclaimed = i > 0 and sweep_low_active[i - 1] == 1.0
            if not already_reclaimed:
                for s in range(i, lo - 1, -1):
                    margin = sweep_margin_atr_mult * atr_arr[s]
                    if not np.isnan(margin) and low[s] < support - margin:
                        sweep_low_active[i] = 1.0
                        sweep_low_extreme[i] = low[s]
                        sweep_low_bars_ago[i] = i - s
                        sweep_low_pool_touches[i] = support_touches[anchor]
                        sweep_low_pool_level[i] = support
                        break

        resistance = resistance_level[anchor]
        if not np.isnan(resistance) and close[i] < resistance:
            already_reclaimed = i > 0 and sweep_high_active[i - 1] == 1.0
            if not already_reclaimed:
                for s in range(i, lo - 1, -1):
                    margin = sweep_margin_atr_mult * atr_arr[s]
                    if not np.isnan(margin) and high[s] > resistance + margin:
                        sweep_high_active[i] = 1.0
                        sweep_high_extreme[i] = high[s]
                        sweep_high_bars_ago[i] = i - s
                        sweep_high_pool_touches[i] = resistance_touches[anchor]
                        sweep_high_pool_level[i] = resistance
                        break

    return pd.DataFrame(
        {
            "sweep_low_active": sweep_low_active,
            "sweep_low_extreme": sweep_low_extreme,
            "sweep_low_bars_ago": sweep_low_bars_ago,
            "sweep_low_pool_touches": sweep_low_pool_touches,
            "sweep_low_pool_level": sweep_low_pool_level,
            "sweep_high_active": sweep_high_active,
            "sweep_high_extreme": sweep_high_extreme,
            "sweep_high_bars_ago": sweep_high_bars_ago,
            "sweep_high_pool_touches": sweep_high_pool_touches,
            "sweep_high_pool_level": sweep_high_pool_level,
        },
        index=df.index,
    )
