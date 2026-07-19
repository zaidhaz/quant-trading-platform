"""Registers every Liquidity Exhaustion Reversal primitive as a
`FeatureEngine` indicator (see `features/feature_engine.py::register_indicator`),
so `strategies/examples/liquidity_exhaustion_reversal.py` reads them through
`context.features.get(name, **params)` exactly like `ema`/`rsi`/`atr` --
causal, computed once per (symbol, timeframe, params) and cached, with the
usual `InsufficientDataError` during warmup.

Importing this module (done by `strategies/examples/liquidity_exhaustion_reversal.py`)
is what performs the registration, as an import side effect -- the same
pattern `strategies/registry.py::register_strategy` uses for strategies.

Naming: everything is prefixed `les_` to keep this package's vocabulary
(sweep, order block, ...) out of the shared, generic indicator namespace.
"""

from __future__ import annotations

from features.feature_engine import register_indicator
from features.indicators import volatility
from strategies.liquidity_exhaustion_reversal import microstructure, structure


def _atr(df, atr_period=14):
    return volatility.atr(df, atr_period)


def _pools(
    df,
    atr_period=14,
    fractal_width=2,
    tolerance_atr_mult=0.15,
    min_touches=2,
    pool_lookback_bars=100,
):
    return structure.compute_liquidity_pools(
        df,
        _atr(df, atr_period),
        fractal_width,
        tolerance_atr_mult,
        min_touches,
        pool_lookback_bars,
    )


def _sweeps(
    df,
    atr_period=14,
    fractal_width=2,
    tolerance_atr_mult=0.15,
    min_touches=2,
    pool_lookback_bars=100,
    sweep_margin_atr_mult=0.1,
    reclaim_window_bars=3,
):
    pools = _pools(
        df, atr_period, fractal_width, tolerance_atr_mult, min_touches, pool_lookback_bars
    )
    return structure.compute_sweeps(
        df, _atr(df, atr_period), pools, sweep_margin_atr_mult, reclaim_window_bars
    )


def _displacement(df, atr_period=14, displacement_atr_mult=1.5, strong_close_threshold=0.5):
    return microstructure.displacement(
        df, _atr(df, atr_period), displacement_atr_mult, strong_close_threshold
    )


def _cvd(df):
    return microstructure.cvd_proxy(df)


def _order_block(
    df,
    direction,
    atr_period=14,
    displacement_atr_mult=1.5,
    strong_close_threshold=0.5,
    order_block_max_lookback_bars=20,
):
    disp = _displacement(df, atr_period, displacement_atr_mult, strong_close_threshold)
    mask = (disp["up"] if direction == "up" else disp["down"]).astype(bool)
    return microstructure.order_block_for_direction(
        df, mask, direction, order_block_max_lookback_bars
    )


# --- structure: swing sequence, BoS / ChoCH (§2.3) ---
register_indicator(
    "les_structure_direction",
    lambda df, fractal_width=2: structure.compute_structure(df, fractal_width)["direction"],
)
register_indicator(
    "les_bos_up",
    lambda df, fractal_width=2: structure.compute_structure(df, fractal_width)["bos_up"],
)
register_indicator(
    "les_bos_down",
    lambda df, fractal_width=2: structure.compute_structure(df, fractal_width)["bos_down"],
)
register_indicator(
    "les_choch_up",
    lambda df, fractal_width=2: structure.compute_structure(df, fractal_width)["choch_up"],
)
register_indicator(
    "les_choch_down",
    lambda df, fractal_width=2: structure.compute_structure(df, fractal_width)["choch_down"],
)

# --- liquidity pools: equal highs / equal lows (§2.2) ---
register_indicator("les_support_level", lambda df, **p: _pools(df, **p)["support_level"])
register_indicator("les_support_touches", lambda df, **p: _pools(df, **p)["support_touches"])
register_indicator("les_resistance_level", lambda df, **p: _pools(df, **p)["resistance_level"])
register_indicator("les_resistance_touches", lambda df, **p: _pools(df, **p)["resistance_touches"])

# --- sweep and reclaim (§2.1) ---
register_indicator("les_sweep_low_active", lambda df, **p: _sweeps(df, **p)["sweep_low_active"])
register_indicator("les_sweep_low_extreme", lambda df, **p: _sweeps(df, **p)["sweep_low_extreme"])
register_indicator("les_sweep_low_bars_ago", lambda df, **p: _sweeps(df, **p)["sweep_low_bars_ago"])
register_indicator(
    "les_sweep_low_pool_touches", lambda df, **p: _sweeps(df, **p)["sweep_low_pool_touches"]
)
register_indicator(
    "les_sweep_low_pool_level", lambda df, **p: _sweeps(df, **p)["sweep_low_pool_level"]
)
register_indicator("les_sweep_high_active", lambda df, **p: _sweeps(df, **p)["sweep_high_active"])
register_indicator("les_sweep_high_extreme", lambda df, **p: _sweeps(df, **p)["sweep_high_extreme"])
register_indicator(
    "les_sweep_high_bars_ago", lambda df, **p: _sweeps(df, **p)["sweep_high_bars_ago"]
)
register_indicator(
    "les_sweep_high_pool_touches", lambda df, **p: _sweeps(df, **p)["sweep_high_pool_touches"]
)
register_indicator(
    "les_sweep_high_pool_level", lambda df, **p: _sweeps(df, **p)["sweep_high_pool_level"]
)

# --- displacement (§2.4) ---
register_indicator("les_displacement_up", lambda df, **p: _displacement(df, **p)["up"])
register_indicator("les_displacement_down", lambda df, **p: _displacement(df, **p)["down"])

# --- absorption proxy (§2.5) ---
register_indicator(
    "les_absorption_score",
    lambda df, absorption_lookback_bars=100: microstructure.absorption_score(
        df, absorption_lookback_bars
    ),
)

# --- delta proxy / divergence (§2.6) ---
register_indicator("les_delta_proxy", lambda df: microstructure.delta_proxy(df))
register_indicator("les_cvd_proxy", lambda df: _cvd(df))
register_indicator(
    "les_bullish_delta_divergence",
    lambda df, divergence_lookback_bars=20: microstructure.bullish_delta_divergence(
        df, _cvd(df), divergence_lookback_bars
    ).astype(float),
)
register_indicator(
    "les_bearish_delta_divergence",
    lambda df, divergence_lookback_bars=20: microstructure.bearish_delta_divergence(
        df, _cvd(df), divergence_lookback_bars
    ).astype(float),
)

# --- Fair Value Gap (§2.9) ---
register_indicator(
    "les_bullish_fvg_active",
    lambda df, atr_period=14, fvg_min_size_atr_mult=0.1: microstructure.bullish_fvg(
        df, _atr(df, atr_period), fvg_min_size_atr_mult
    )["active"],
)
register_indicator(
    "les_bullish_fvg_size",
    lambda df, atr_period=14, fvg_min_size_atr_mult=0.1: microstructure.bullish_fvg(
        df, _atr(df, atr_period), fvg_min_size_atr_mult
    )["size"],
)
register_indicator(
    "les_bearish_fvg_active",
    lambda df, atr_period=14, fvg_min_size_atr_mult=0.1: microstructure.bearish_fvg(
        df, _atr(df, atr_period), fvg_min_size_atr_mult
    )["active"],
)
register_indicator(
    "les_bearish_fvg_size",
    lambda df, atr_period=14, fvg_min_size_atr_mult=0.1: microstructure.bearish_fvg(
        df, _atr(df, atr_period), fvg_min_size_atr_mult
    )["size"],
)

# --- Order Block (§2.10) ---
register_indicator("les_order_block_up_low", lambda df, **p: _order_block(df, "up", **p)["low"])
register_indicator("les_order_block_up_high", lambda df, **p: _order_block(df, "up", **p)["high"])
register_indicator("les_order_block_down_low", lambda df, **p: _order_block(df, "down", **p)["low"])
register_indicator(
    "les_order_block_down_high", lambda df, **p: _order_block(df, "down", **p)["high"]
)
