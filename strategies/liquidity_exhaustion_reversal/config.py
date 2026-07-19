"""Every threshold the Liquidity Exhaustion Reversal System uses, in one
place. Defaults are round, interpretable numbers chosen for that reason --
none are fit to historical performance (see
docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md §4). Nothing in the strategy
module (`strategies/examples/liquidity_exhaustion_reversal.py`) hardcodes a
threshold that isn't a field here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LiquidityExhaustionReversalConfig:
    # Shared
    atr_period: int = 14
    adx_period: int = 14
    regime_percentile_lookback_bars: int = 100

    # Swing points / structure (§2.3)
    fractal_width: int = 2

    # Liquidity pool: equal highs / equal lows (§2.2)
    min_touches: int = 2
    tolerance_atr_mult: float = 0.15
    pool_lookback_bars: int = 100

    # Sweep and reclaim (§2.1)
    sweep_margin_atr_mult: float = 0.1
    reclaim_window_bars: int = 3

    # Displacement (§2.4)
    displacement_atr_mult: float = 1.5
    strong_close_threshold: float = 0.5
    displacement_confirm_window_bars: int = 3

    # Absorption proxy (§2.5) -- optional confirmation filter
    absorption_lookback_bars: int = 100
    absorption_percentile: float = 80.0
    require_absorption: bool = False

    # Delta proxy / divergence (§2.6) -- optional confirmation filter
    divergence_lookback_bars: int = 20
    require_delta_divergence: bool = False

    # Open interest flush (§2.7) -- optional, data-gated filter; inert unless
    # an open_interest_provider is injected (none exists in this codebase yet)
    oi_lookback_bars: int = 3
    oi_flush_drop_pct: float = 0.05
    require_oi_flush: bool = False

    # Fair Value Gap (§2.9) -- optional confirmation filter, Phase 4 required
    fvg_min_size_atr_mult: float = 0.1
    require_fvg: bool = False

    # Order Block (§2.10) -- optional confirmation filter, Phase 4 required;
    # weakest-evidence concept in the system (docs §1.9), off by default
    order_block_max_lookback_bars: int = 20
    require_order_block: bool = False

    # Market regime (§1.11) -- logged on every trade regardless; not a hard
    # gate by default, since gating on it would itself be an untested
    # assumption (see docs §1.11)
    require_ranging_regime: bool = False

    # Risk: stop-loss = the sweep's own extreme (the falsification boundary,
    # §1.12), plus a small buffer so a hairline wick re-tag doesn't stop out
    # noise rather than a genuine re-take of the level
    stop_buffer_atr_mult: float = 0.1

    # Risk: take-profit anchored to "value" per the reversal-to-value
    # hypothesis, with a fixed R-multiple fallback when no value anchor
    # resolves (§1.12)
    take_profit_mode: str = "value"  # "value" | "r_multiple"
    take_profit_r_multiple: float = 2.0
    value_anchor: str = "vwap"  # "vwap" | "poc"
    vwap_period: int | None = 50  # rolling, not cumulative-since-inception -- "value" should
    # mean *current* fair value, not an anchor that drifts arbitrarily far from price over a
    # long backtest; 50 matches `poc_period`'s default for the same reason, not tuned
    poc_period: int = 50
    poc_bins: int = 10
    value_area_pct: float = 0.70

    # Position sizing
    risk_per_trade: float = 0.01

    # Confidence score weights (§1.12) -- equal/round by construction, not
    # fit; sum need not be exactly 1.0, the score is clamped to [0, 100]
    confidence_weight_pool_strength: float = 0.2
    confidence_weight_displacement: float = 0.2
    confidence_weight_absorption: float = 0.2
    confidence_weight_confluence: float = 0.2
    confidence_weight_regime_fit: float = 0.2
    confidence_pool_touches_saturation: int = 5
    confidence_displacement_atr_mult_saturation: float = 3.0

    def __post_init__(self) -> None:
        if self.take_profit_mode not in ("value", "r_multiple"):
            raise ValueError(
                f"take_profit_mode must be 'value' or 'r_multiple', got "
                f"{self.take_profit_mode!r}"
            )
        if self.value_anchor not in ("vwap", "poc"):
            raise ValueError(f"value_anchor must be 'vwap' or 'poc', got {self.value_anchor!r}")

    # NOTE on Open Interest / liquidations: `require_oi_flush` exists as a config
    # field for API stability, but there is currently no `open_interest_provider`
    # injection seam anywhere in this module -- there is no `OpenInterestDataset`
    # in `market_data/historical/` for one to supply data from (see docs §0, §1.7).
    # The OI-flush rule is therefore permanently inert today: `oi_flush_confirmed`
    # is always 0.0 and `open_interest_change` is always logged as NaN in
    # `strategies/examples/liquidity_exhaustion_reversal.py`, never fabricated.
    # Wiring a real provider through is future work once that dataset exists.
