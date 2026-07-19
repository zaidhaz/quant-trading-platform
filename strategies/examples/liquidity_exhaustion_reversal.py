"""Liquidity Exhaustion Reversal System ("Sweep & Reclaim at Value") -- the
platform's first production strategy.

See `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md` for the full research
review, mathematical definitions, and research report this implements.
Nothing here should be read as "SMC works" -- it is a specific, narrow,
falsifiable claim about liquidity clustering and stop/breakout-order
exhaustion at prior swing extremes, deliberately kept separable (via the
optional filters) from the weaker-evidence concepts it can optionally be
combined with.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from core.enums import MarketBias, PositionSide, SignalDirection, TrendState, VolatilityState
from core.exceptions import InsufficientDataError
from core.types import Position
from risk.position_sizing import fixed_fractional
from strategies.base_strategy import Strategy
from strategies.context import StrategyContext
from strategies.liquidity_exhaustion_reversal import (
    indicators as _register_indicators,  # noqa: F401
)
from strategies.liquidity_exhaustion_reversal.config import LiquidityExhaustionReversalConfig
from strategies.registry import register_strategy
from strategies.signal import Setup

_FAVORABLE_BIAS = {
    SignalDirection.LONG: MarketBias.BULLISH,
    SignalDirection.SHORT: MarketBias.BEARISH,
}


def _session_bucket(ts: datetime) -> float:
    """UTC-hour session bucket: 0=Asia [00-08), 1=London [08-13), 2=New York
    [13-21), 3=Late US / pre-Asia [21-24). A deterministic, documented
    encoding for instrumentation only -- not a claim about precise real-world
    liquidity-session boundaries."""
    hour = ts.hour
    if hour < 8:
        return 0.0
    if hour < 13:
        return 1.0
    if hour < 21:
        return 2.0
    return 3.0


def _isnan(x: float) -> bool:
    return x != x  # noqa: PLR0124 - the NaN self-inequality trick, avoids an extra import


@register_strategy("liquidity_exhaustion_reversal")
class LiquidityExhaustionReversalStrategy(Strategy):
    """Falsifiable hypothesis: a fast breach of a multi-touch liquidity pool
    (equal highs/lows) that closes back inside it within a few bars, followed
    by a displacement move away from it, indicates exhausted resting
    stop/breakout liquidity rather than genuine directional continuation --
    and favors reversion toward "value" (VWAP / volume-profile POC).

    Baseline setup (always active, no optional filter required): liquidity
    pool + sweep-and-reclaim + displacement (docs §3). Absorption, delta
    divergence, Fair Value Gap, Order Block, and Open Interest flush are each
    an independently toggleable optional filter (`require_*` config fields,
    all default `False`) -- the baseline works with all of them off, so their
    marginal contribution can be measured with A/B backtests instead of
    assumed. See `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md`.
    """

    def __init__(self, **params: object) -> None:
        config = LiquidityExhaustionReversalConfig(**params)  # type: ignore[arg-type]
        super().__init__(**asdict(config))
        self.config = config

    # -- indicator-parameter groupings; each must exactly match the
    #    corresponding registered indicator's signature (see
    #    strategies/liquidity_exhaustion_reversal/indicators.py) --

    def _pool_params(self) -> dict[str, object]:
        cfg = self.config
        return dict(
            atr_period=cfg.atr_period,
            fractal_width=cfg.fractal_width,
            tolerance_atr_mult=cfg.tolerance_atr_mult,
            min_touches=cfg.min_touches,
            pool_lookback_bars=cfg.pool_lookback_bars,
        )

    def _sweep_params(self) -> dict[str, object]:
        cfg = self.config
        return {
            **self._pool_params(),
            "sweep_margin_atr_mult": cfg.sweep_margin_atr_mult,
            "reclaim_window_bars": cfg.reclaim_window_bars,
        }

    def _displacement_params(self) -> dict[str, object]:
        cfg = self.config
        return dict(
            atr_period=cfg.atr_period,
            displacement_atr_mult=cfg.displacement_atr_mult,
            strong_close_threshold=cfg.strong_close_threshold,
        )

    def _order_block_params(self) -> dict[str, object]:
        return {
            **self._displacement_params(),
            "order_block_max_lookback_bars": self.config.order_block_max_lookback_bars,
        }

    # -- setup detection (docs §3) --

    def _find_recent_sweep_lag(self, context: StrategyContext, side: str) -> int | None:
        """How many bars back (0 = current bar) the reclaim was confirmed, if
        any within `displacement_confirm_window_bars`. Searches nearest-first
        so a same-bar sweep+reclaim (the strongest form, docs §2.1) wins."""
        params = self._sweep_params()
        for lag in range(0, self.config.displacement_confirm_window_bars + 1):
            if context.index - lag < 0:
                break
            active = context.features.get(f"les_sweep_{side}_active", offset=lag, **params)
            if active >= 0.5:
                return lag
        return None

    def _detect_side(
        self, context: StrategyContext, side: str, direction: SignalDirection
    ) -> Setup | None:
        cfg = self.config
        lag = self._find_recent_sweep_lag(context, side)
        if lag is None:
            return None

        # Displacement must confirm on the CURRENT bar -- see docs §3: this is
        # what makes the trigger bar causal (only ever looking at bars <= now)
        # even though the sweep itself may have happened up to
        # `displacement_confirm_window_bars` bars earlier.
        disp_name = (
            "les_displacement_up" if direction == SignalDirection.LONG else "les_displacement_down"
        )
        if context.features.get(disp_name, offset=0, **self._displacement_params()) < 0.5:
            return None

        sweep_params = self._sweep_params()
        extreme = context.features.get(f"les_sweep_{side}_extreme", offset=lag, **sweep_params)
        bars_ago = context.features.get(f"les_sweep_{side}_bars_ago", offset=lag, **sweep_params)
        pool_touches = context.features.get(
            f"les_sweep_{side}_pool_touches", offset=lag, **sweep_params
        )
        pool_level = context.features.get(
            f"les_sweep_{side}_pool_level", offset=lag, **sweep_params
        )

        if pool_level == extreme:
            return None  # degenerate: no retracement distance to reason about
        if direction == SignalDirection.LONG:
            retracement_pct = (context.price - extreme) / (pool_level - extreme)
        else:
            retracement_pct = (extreme - context.price) / (extreme - pool_level)

        metadata = self._build_metadata(
            context,
            side,
            direction,
            lag,
            extreme,
            bars_ago,
            pool_touches,
            pool_level,
            retracement_pct,
        )

        if cfg.require_absorption and metadata["absorption_confirmed"] < 0.5:
            return None
        if cfg.require_delta_divergence and metadata["delta_divergence_confirmed"] < 0.5:
            return None
        if cfg.require_fvg and metadata["fvg_confirmed"] < 0.5:
            return None
        if cfg.require_order_block and metadata["order_block_confirmed"] < 0.5:
            return None
        if cfg.require_oi_flush and metadata["oi_flush_confirmed"] < 0.5:
            return None
        if cfg.require_ranging_regime and context.regime.current().trend != TrendState.RANGING:
            return None

        return Setup(
            direction=direction,
            reference_price=context.price,
            reasoning=self._build_reasoning(context, side, direction, metadata),
            metadata=metadata,
        )

    def detect_setup(self, context: StrategyContext) -> Setup | None:
        try:
            setup = self._detect_side(context, "low", SignalDirection.LONG)
            if setup is not None:
                return setup
            return self._detect_side(context, "high", SignalDirection.SHORT)
        except InsufficientDataError:
            return None

    # -- Phase 5/6: explainability + research instrumentation --

    def _build_metadata(
        self,
        context: StrategyContext,
        side: str,
        direction: SignalDirection,
        lag: int,
        extreme: float,
        bars_ago: float,
        pool_touches: float,
        pool_level: float,
        retracement_pct: float,
    ) -> dict[str, float]:
        cfg = self.config

        def _safe(
            name: str, default: float = float("nan"), offset: int = 0, **kwargs: object
        ) -> float:
            try:
                return context.features.get(name, offset=offset, **kwargs)
            except InsufficientDataError:
                return default

        atr = _safe("atr", period=cfg.atr_period)
        sweep_size = abs(pool_level - extreme)

        absorption_score = _safe(
            "les_absorption_score", absorption_lookback_bars=cfg.absorption_lookback_bars
        )
        absorption_confirmed = (
            1.0
            if not _isnan(absorption_score) and absorption_score >= cfg.absorption_percentile
            else 0.0
        )

        sweep_bar_offset = int(lag + bars_ago)
        div_name = (
            "les_bullish_delta_divergence" if side == "low" else "les_bearish_delta_divergence"
        )
        delta_divergence_confirmed = _safe(
            div_name,
            default=0.0,
            offset=sweep_bar_offset,
            divergence_lookback_bars=cfg.divergence_lookback_bars,
        )

        fvg_active_name = (
            "les_bullish_fvg_active"
            if direction == SignalDirection.LONG
            else "les_bearish_fvg_active"
        )
        fvg_size_name = (
            "les_bullish_fvg_size" if direction == SignalDirection.LONG else "les_bearish_fvg_size"
        )
        fvg_params = dict(
            atr_period=cfg.atr_period, fvg_min_size_atr_mult=cfg.fvg_min_size_atr_mult
        )
        fvg_confirmed = _safe(fvg_active_name, default=0.0, offset=0, **fvg_params)
        fvg_size = (
            _safe(fvg_size_name, offset=0, **fvg_params) if fvg_confirmed >= 0.5 else float("nan")
        )

        ob_dir = "up" if direction == SignalDirection.LONG else "down"
        ob_params = self._order_block_params()
        ob_low = _safe(f"les_order_block_{ob_dir}_low", default=float("nan"), offset=0, **ob_params)
        ob_high = _safe(
            f"les_order_block_{ob_dir}_high", default=float("nan"), offset=0, **ob_params
        )
        order_block_confirmed = 1.0 if not (_isnan(ob_low) or _isnan(ob_high)) else 0.0
        order_block_size = abs(ob_high - ob_low) if order_block_confirmed >= 0.5 else float("nan")

        # No OpenInterestDataset exists in this codebase (docs §0, §1.7) --
        # logged as NaN and the filter is permanently inert, never fabricated.
        oi_flush_confirmed = 0.0
        open_interest_change = float("nan")

        poc = _safe("volume_profile_poc", period=cfg.poc_period, bins=cfg.poc_bins)
        vah = _safe(
            "volume_profile_vah",
            period=cfg.poc_period,
            bins=cfg.poc_bins,
            value_area_pct=cfg.value_area_pct,
        )
        val = _safe(
            "volume_profile_val",
            period=cfg.poc_period,
            bins=cfg.poc_bins,
            value_area_pct=cfg.value_area_pct,
        )
        vwap = _safe("vwap", period=cfg.vwap_period)

        regime = context.regime.current()

        return {
            "direction": 1.0 if direction == SignalDirection.LONG else -1.0,
            "sweep_extreme": extreme,
            "sweep_size": sweep_size,
            "sweep_duration_bars": float(bars_ago),
            "sweep_bars_before_now": float(sweep_bar_offset),
            "pool_level": pool_level,
            "pool_touches": pool_touches,
            "retracement_pct": retracement_pct,
            "atr": atr,
            "ema_20": _safe("ema", period=20),
            "ema_50": _safe("ema", period=50),
            "ema_200": _safe("ema", period=200),
            "rsi_14": _safe("rsi", period=14),
            "macd_line": _safe("macd_line"),
            "macd_hist": _safe("macd_hist"),
            "adx": _safe("adx", period=cfg.adx_period),
            "volume": float(context.bar["volume"]),
            "vwap": vwap,
            "poc": poc,
            "vah": vah,
            "val": val,
            "distance_to_poc": context.price - poc if not _isnan(poc) else float("nan"),
            "distance_to_vah": context.price - vah if not _isnan(vah) else float("nan"),
            "distance_to_val": context.price - val if not _isnan(val) else float("nan"),
            "funding_rate": (
                context.funding_rate if context.funding_rate is not None else float("nan")
            ),
            "open_interest_change": open_interest_change,
            "liquidations": float("nan"),  # no data source exists yet -- docs §0
            "delta_proxy": _safe("les_delta_proxy"),
            "cvd_proxy": _safe("les_cvd_proxy"),
            "absorption_score": absorption_score,
            "absorption_confirmed": absorption_confirmed,
            "delta_divergence_confirmed": 1.0 if delta_divergence_confirmed >= 0.5 else 0.0,
            "fvg_confirmed": 1.0 if fvg_confirmed >= 0.5 else 0.0,
            "fvg_size": fvg_size,
            "order_block_confirmed": order_block_confirmed,
            "order_block_size": order_block_size,
            "oi_flush_confirmed": oi_flush_confirmed,
            "structure_direction": _safe(
                "les_structure_direction", default=0.0, fractal_width=cfg.fractal_width
            ),
            "trend_strength_adx": _safe("adx", period=cfg.adx_period),
            "volatility_regime_atr_percentile": _safe(
                "atr_percentile",
                period=cfg.atr_period,
                lookback=cfg.regime_percentile_lookback_bars,
            ),
            "liquidity_regime_volume_percentile": _safe(
                "volume_percentile", lookback=cfg.regime_percentile_lookback_bars
            ),
            "session": _session_bucket(context.ts),
            "day_of_week": float(context.ts.weekday()),
            "market_regime_trending": 1.0 if regime.trend == TrendState.TRENDING else 0.0,
            "market_regime_high_volatility": (
                1.0 if regime.volatility == VolatilityState.HIGH else 0.0
            ),
        }

    def _build_reasoning(
        self,
        context: StrategyContext,
        side: str,
        direction: SignalDirection,
        metadata: dict[str, float],
    ) -> str:
        cfg = self.config
        pool_kind = "support" if side == "low" else "resistance"
        dir_word = "long" if direction == SignalDirection.LONG else "short"
        invalidation_price = metadata["sweep_extreme"]

        evidence_for = [
            f"{pool_kind} liquidity pool at {metadata['pool_level']:.6g} "
            f"({metadata['pool_touches']:.0f} touches)",
            f"swept to {metadata['sweep_extreme']:.6g} and reclaimed within "
            f"{metadata['sweep_bars_before_now']:.0f} bar(s)",
            f"displacement confirmed on the trigger bar "
            f"(true range >= {cfg.displacement_atr_mult}x ATR, strong close)",
        ]
        if metadata["absorption_confirmed"] >= 0.5:
            evidence_for.append(
                f"absorption proxy at the sweep bar in the "
                f"{cfg.absorption_percentile:.0f}th+ percentile"
            )
        if metadata["delta_divergence_confirmed"] >= 0.5:
            evidence_for.append("delta-proxy divergence at the sweep extreme")
        if metadata["fvg_confirmed"] >= 0.5:
            evidence_for.append(f"Fair Value Gap of size {metadata['fvg_size']:.6g} present")
        if metadata["order_block_confirmed"] >= 0.5:
            evidence_for.append(
                f"Order Block zone (weak-evidence, optional filter) of size "
                f"{metadata['order_block_size']:.6g} identified"
            )

        evidence_against = []
        if metadata["absorption_confirmed"] < 0.5:
            evidence_against.append("absorption proxy not elevated at the sweep bar")
        if metadata["delta_divergence_confirmed"] < 0.5:
            evidence_against.append("no delta-proxy divergence detected")
        if metadata["fvg_confirmed"] < 0.5:
            evidence_against.append("no Fair Value Gap present")
        if metadata["market_regime_trending"] >= 0.5:
            evidence_against.append(
                "market regime is TRENDING -- the reversal hypothesis is weaker against a "
                "strong prevailing trend (docs §1.11, not hard-gated by default)"
            )

        triggered_rules = ["liquidity_pool", "sweep_and_reclaim", "displacement"]
        for key, label in (
            ("absorption_confirmed", "absorption"),
            ("delta_divergence_confirmed", "delta_divergence"),
            ("fvg_confirmed", "fair_value_gap"),
            ("order_block_confirmed", "order_block"),
        ):
            if metadata[key] >= 0.5:
                triggered_rules.append(label)
        rejected_rules = [
            label
            for key, label in (
                ("absorption_confirmed", "absorption"),
                ("delta_divergence_confirmed", "delta_divergence"),
                ("fvg_confirmed", "fair_value_gap"),
                ("order_block_confirmed", "order_block"),
                ("oi_flush_confirmed", "oi_flush (no data source available)"),
            )
            if metadata[key] < 0.5
        ]

        trend_word = "TRENDING" if metadata["market_regime_trending"] >= 0.5 else "RANGING"
        vol_word = "HIGH" if metadata["market_regime_high_volatility"] >= 0.5 else "LOW"
        evidence_against_text = (
            "; ".join(evidence_against) if evidence_against else "none identified"
        )
        rejected_rules_text = ", ".join(rejected_rules) if rejected_rules else "none"
        expected_holding_bars = cfg.reclaim_window_bars + cfg.displacement_confirm_window_bars

        return (
            f"LIQUIDITY EXHAUSTION REVERSAL ({dir_word})\n"
            f"Market regime: trend={trend_word}, volatility={vol_word}\n"
            f"Primary hypothesis: the {pool_kind} pool's resting stop/breakout liquidity was "
            f"exhausted by the sweep and failed to sustain continuation; balance of intent now "
            f"favors reversion toward value (docs §0).\n"
            f"Entry reason: sweep-and-reclaim of a {metadata['pool_touches']:.0f}-touch pool at "
            f"{metadata['pool_level']:.6g}, confirmed by displacement.\n"
            f"Evidence supporting trade: {'; '.join(evidence_for)}.\n"
            f"Evidence against trade: {evidence_against_text}.\n"
            f"Triggered rules: {', '.join(triggered_rules)}.\n"
            f"Rejected/absent rules: {rejected_rules_text}.\n"
            f"Invalidation condition: a close beyond {invalidation_price:.6g} (the swept extreme) "
            f"falsifies the hypothesis -- this is also the stop-loss.\n"
            f"Expected holding time: up to {expected_holding_bars} bars to target/stop under "
            f"normal conditions, exit early on an opposing Change-of-Character (docs §2.3)."
        )

    # -- confirmation veto (docs §3: stop-sanity check only; optional-filter
    #    gating already happened in detect_setup, this is a bug guard) --

    def check_entry(self, context: StrategyContext, setup: Setup) -> bool:
        stop = self.stop_loss(context, setup)
        if stop is None:
            return False
        if setup.direction == SignalDirection.LONG:
            return stop < context.price
        return stop > context.price

    # -- exit: hypothesis invalidation via an opposing Change of Character,
    #    ahead of stop/take-profit (docs §1.12, §2.3) --

    def check_exit(self, context: StrategyContext, position: Position) -> bool:
        cfg = self.config
        try:
            if position.side == PositionSide.LONG:
                choch = context.features.get("les_choch_down", fractal_width=cfg.fractal_width)
            else:
                choch = context.features.get("les_choch_up", fractal_width=cfg.fractal_width)
        except InsufficientDataError:
            return False
        return choch >= 0.5

    # -- stop-loss = the hypothesis's own falsification boundary (docs §1.12) --

    def stop_loss(self, context: StrategyContext, setup: Setup) -> float | None:
        extreme = setup.metadata.get("sweep_extreme")
        if extreme is None:
            return None
        atr = context.features.get("atr", period=self.config.atr_period)
        buffer = self.config.stop_buffer_atr_mult * atr
        if setup.direction == SignalDirection.LONG:
            return extreme - buffer
        return extreme + buffer

    # -- take-profit: value anchor, R-multiple fallback (docs §1.12) --

    def take_profit(self, context: StrategyContext, setup: Setup) -> float | None:
        cfg = self.config
        if cfg.take_profit_mode == "value":
            try:
                if cfg.value_anchor == "vwap":
                    anchor = context.features.get("vwap", period=cfg.vwap_period)
                else:
                    anchor = context.features.get(
                        "volume_profile_poc", period=cfg.poc_period, bins=cfg.poc_bins
                    )
            except InsufficientDataError:
                anchor = None
            if anchor is not None:
                if setup.direction == SignalDirection.LONG and anchor > setup.reference_price:
                    return anchor
                if setup.direction == SignalDirection.SHORT and anchor < setup.reference_price:
                    return anchor

        stop = self.stop_loss(context, setup)
        if stop is None:
            return None
        risk = abs(setup.reference_price - stop)
        if setup.direction == SignalDirection.LONG:
            return setup.reference_price + cfg.take_profit_r_multiple * risk
        return setup.reference_price - cfg.take_profit_r_multiple * risk

    def position_size(self, context: StrategyContext, setup: Setup) -> float:
        stop = self.stop_loss(context, setup)
        if stop is None:
            return 0.0
        return fixed_fractional(
            context.equity, setup.reference_price, stop, self.config.risk_per_trade
        )

    # -- confidence: capped, deterministic weighted sum, weights not fit
    #    (docs §1.12) --

    def confidence(self, context: StrategyContext, setup: Setup) -> float:
        cfg = self.config
        meta = setup.metadata

        pool_strength = (
            min(meta.get("pool_touches", 0.0) / cfg.confidence_pool_touches_saturation, 1.0) * 100.0
        )

        atr = meta.get("atr", 0.0)
        tr = float(context.bar["high"] - context.bar["low"])
        displacement_ratio = (tr / atr) if atr > 0 else 0.0
        displacement_score = (
            min(displacement_ratio / cfg.confidence_displacement_atr_mult_saturation, 1.0) * 100.0
        )

        absorption_score = meta.get("absorption_score", 0.0)
        absorption_score = 0.0 if _isnan(absorption_score) else absorption_score

        confluence_flags = [
            meta.get("fvg_confirmed", 0.0),
            meta.get("order_block_confirmed", 0.0),
            meta.get("delta_divergence_confirmed", 0.0),
            meta.get("oi_flush_confirmed", 0.0),
        ]
        confluence_score = (sum(confluence_flags) / len(confluence_flags)) * 100.0

        regime = context.regime.current()
        favorable = _FAVORABLE_BIAS.get(setup.direction)
        if regime.bias == favorable:
            regime_fit = 100.0
        elif regime.bias == MarketBias.NEUTRAL:
            regime_fit = 50.0
        else:
            regime_fit = 0.0

        raw = (
            cfg.confidence_weight_pool_strength * pool_strength
            + cfg.confidence_weight_displacement * displacement_score
            + cfg.confidence_weight_absorption * absorption_score
            + cfg.confidence_weight_confluence * confluence_score
            + cfg.confidence_weight_regime_fit * regime_fit
        )
        return round(min(max(raw, 0.0), 100.0), 2)

    def reasoning(self, context: StrategyContext, setup: Setup) -> str:
        return setup.reasoning
