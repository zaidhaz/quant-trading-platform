# Liquidity Exhaustion Reversal System

*(formerly "Sweep & Reclaim at Value")*

Status: research review + mathematical specification complete (this document);
implementation tracked in `TASKS.md`. This is a **research document**, not
marketing copy — it argues for and against its own design choices, and says
plainly where the evidence is weak.

---

## 0. Framing

This strategy is a **falsifiable hypothesis about a specific, narrow market
mechanism** — not a collection of chart patterns. The mechanism:

> Resting orders (stop-losses behind swing extremes, breakout entries above
> prior highs / below prior lows) cluster at price levels that have been
> tested more than once. A fast move that briefly trades through such a
> level and then closes back on the other side of it is consistent with
> those resting orders being filled and exhausted, without genuine new
> directional interest continuing the move. If so, the balance of
> now-unfilled intent favors a move back toward "fair value" (a
> volume-weighted reference price), not continuation.

Every rule below exists to operationalize one piece of that mechanism into a
deterministic test. Where the standard "Smart Money Concepts" (SMC) version
of a rule is well-defined in price-geometry terms, it is kept (renamed to a
neutral, precise name). Where it is vague, contested, or depends on data we
don't have, that is stated explicitly rather than quietly assumed away.

**Hard data constraint that shapes everything below:** the codebase currently
has exactly two historical datasets — `candles` (OHLCV) and `funding_rate`
(`market_data/historical/{candles_dataset,funding_rate_dataset}.py`). There is
no trade-level/tick data, no order book, no open interest, and no liquidation
feed. `market_data/historical/dataset.py` was explicitly designed as an
extension point for exactly this ("open interest, liquidations, CVD, ...")
but none of those subclasses exist yet. Consequently:

- **Delta / CVD**: no real buy/sell-initiated volume exists. This system uses
  a documented OHLCV-derived *proxy* (§2.6) — never described to a caller as
  real order flow.
- **Open Interest Flush**: cannot be computed at all right now. Implemented
  as an optional filter that accepts an injected OI series; with no series
  injected (today's default — there's nothing to inject), the filter is
  inert and the corresponding feature columns are logged as `NaN`, not
  fabricated. Real implementation is future work (a new
  `OpenInterestDataset`, symmetric with `FundingRateDataset`).
- **Liquidations**: same treatment — no data source exists, feature is
  logged as `NaN`, not used to gate any rule.

Anything computable purely from OHLCV (+ funding rate) is implemented for
real, not stubbed.

---

## 1. Rule-by-rule research review

Format per rule: **why it exists → hypothesis being tested → microstructure
support → overfitting risk → logic decision (kept / redefined / rejected /
descoped) and why.**

### 1.1 Liquidity Sweep

- **Why**: retail and algorithmic stop-losses / breakout entries cluster at
  prior swing extremes and round levels. A brief breach followed by a close
  back on the other side is consistent with that resting liquidity being
  taken out.
- **Hypothesis**: the breach was liquidity-driven (stops/breakout orders
  filling), not the start of sustained directional trade.
- **Microstructure support**: moderate-to-good. Price clustering at prior
  extremes and stop-run behavior around them is documented outside of SMC
  folklore (e.g. Osler 2003, *"Currency Orders and Exchange-Rate Dynamics"*,
  on stop-loss clustering at round numbers and prior extremes). We have no
  order-book data to *prove* a specific sweep was liquidity-driven — this
  remains a geometric proxy for the mechanism, not direct evidence of it.
- **Overfitting risk**: high if the breach/reclaim thresholds are raw price
  offsets or a hand-picked bar count — those don't generalize across symbols
  or volatility regimes and are exactly the kind of "looks good in
  hindsight" knob the brief warns against.
- **Decision — redefine, don't optimize**: express both the breach margin
  and the reclaim window in **ATR units and a small integer bar count that
  is a structural upper bound, not a fitted value** (see §2.1). Require the
  swept level to be a *liquidity pool* (§1.2), not an arbitrary N-bar high,
  which gives the rule an actual quantitative liquidity-density argument
  instead of "any local high."

### 1.2 Equal Highs / Equal Lows

- **Why**: multiple touches near the same price are the closest thing OHLCV
  data gives us to evidence of a liquidity pool (repeated tests without a
  sustained break imply resting orders have survived there).
- **Hypothesis**: touch count is a proxy for resting-order density at a
  level.
- **Microstructure support**: weak-to-moderate on its own — "equal" highs is
  a chart-pattern label, not a measurement. It becomes a real measurement
  once "equal" is replaced with a volatility-normalized tolerance and a
  minimum touch count.
- **Overfitting risk**: high with a fixed price tolerance (e.g. "$5 apart")
  — breaks immediately across symbols/timeframes/volatility regimes.
- **Decision — redefine**: tolerance in **ATR units**, touches counted from
  **structurally detected swing points** (§2.2 fractal pivots), not from raw
  closes or every local wiggle. A "pool" requires `min_touches >= 2`
  (configurable, default 2 — the minimum that makes "equal" meaningful at
  all, not a fitted value).

### 1.3 CHoCH / BOS / "Structure Shift"

- **Why**: distinguishing trend-continuation breaks from the first
  countertrend break is central to every SMC framework, but in practice
  "CHoCH," "BOS," and "structure shift" are used inconsistently across
  sources — the ambiguity the user's brief specifically warned about.
- **Hypothesis**: the *sequence* of swing highs/lows (higher-highs/
  higher-lows vs. lower-highs/lower-lows) reflects the market's realized
  supply/demand balance — this is just Dow Theory, not new.
- **Microstructure support**: this is the most defensible of the SMC-derived
  concepts precisely because it isn't microstructure at all — it's price
  bookkeeping. It doesn't need order-flow justification.
- **Overfitting risk**: low, once the swing/fractal width is fixed, because
  the state machine that follows is deterministic with no free parameters
  beyond that one.
- **Decision — collapse three ambiguous names into one precise state
  machine**: track the alternating sequence of confirmed swing highs/lows;
  define exactly two events — **Break of Structure (BoS)**: close beyond the
  last swing point *in the direction of the prevailing structure*
  (continuation); **Change of Character (ChoCH)**: close beyond the last
  swing point *against* the prevailing structure (first countertrend
  signal). "Structure shift" as a separate third term is retired — it was
  never anything other than ChoCH under another name. See §2.3.

### 1.4 Displacement

- **Why**: separates a genuine reversal (aggressive, high-conviction move
  away from the swept level) from a low-conviction drift back toward it.
- **Hypothesis**: an abnormally large, directional true-range bar reflects
  market-order-driven (aggressive) participation rather than passive drift.
- **Microstructure support**: reasonable — this is a volatility/momentum
  burst filter with real precedent (Wyckoff "sign of strength" bars, "trend
  day" literature), not SMC-specific.
- **Overfitting risk**: moderate if the ATR multiple is tuned to history.
  Kept configurable and explicitly not tuned (default is a round, defensible
  number — see §2.4 — chosen for interpretability, not backtested fit).
- **Decision — kept**, defined as true-range vs. rolling-ATR multiple *and*
  a strong-close requirement in the move's direction (§2.4), so a big bar
  that closes mid-range doesn't count as conviction.

### 1.5 Absorption

- **Why**: at a sweep extreme, high volume with little further price
  progress is classically read as passive orders "absorbing" the aggressive
  flow that caused the sweep.
- **Hypothesis**: elevated volume-per-unit-of-range at the extreme indicates
  the sweeping flow met opposing size.
- **Microstructure support**: the underlying idea (large prints meeting
  resistance without price progress) is real tape-reading/market-profile
  territory, **but it properly requires trade-level or order-book data**,
  which we don't have. From OHLCV alone we can only measure the *outcome*
  (volume high, range low), not the *cause* (an actual passive/aggressive
  imbalance).
- **Overfitting risk**: moderate — percentile thresholds on a
  volume-per-range ratio are a reasonable, low-parameter proxy.
- **Decision — kept as an explicitly-labeled proxy**: `absorption_score` is
  the rolling percentile rank of `volume / true_range` at the swept bar
  (§2.5). Documented everywhere as an OHLCV proxy for absorption, not a
  measurement of it.

### 1.6 Delta Divergence

- **Why**: classic technical divergence (price makes a new extreme, the
  underlying pressure gauge doesn't) applied to buy/sell pressure instead of
  price momentum.
- **Hypothesis**: at the sweep, price makes a new local extreme but net
  buy/sell pressure over the same window does *not* confirm it — waning
  pressure at a fresh price extreme.
- **Microstructure support**: real delta requires trade-side classification
  (tick rule or exchange-provided aggressor side), which requires
  trade-level data we don't have. What we compute is a **bar-level proxy**
  (Close-Location-Value × Volume, the same construction as Chaikin Money
  Flow's numerator): `delta_proxy = volume * ((close - low) - (high -
  close)) / (high - low)`. This assumes volume within a bar is distributed
  in proportion to where the close sits in the bar's range — a known-crude
  assumption (says nothing about the intrabar *path*), standard in
  OHLCV-only toolkits, and explicitly **not** a claim about real order flow.
- **Overfitting risk**: low for the divergence *test* itself (it's a
  parameter-light comparison of two extrema), the risk is entirely in
  over-trusting the proxy's realism.
- **Decision — kept, clearly labeled**: implemented as divergence between
  price extrema and cumulative `delta_proxy` extrema over the same lookback
  (§2.6). The interface (`order_flow_provider`) is written so a future
  `TradesDataset`-backed real-delta implementation is a drop-in replacement
  with no strategy-logic change.

### 1.7 Open Interest Flush

- **Why**: a sharp drop in open interest during a price sweep is read as
  forced deleveraging/liquidations rather than new positioning, reinforcing
  "this move was liquidity, not conviction."
- **Hypothesis**: OI contraction at the sweep = position flushing, not fresh
  directional entry.
- **Microstructure support**: plausible and used in real derivatives
  research, but **cannot be computed at all today** — no OI dataset exists.
- **Overfitting risk**: N/A — not implemented.
- **Decision — descoped to an optional, data-gated filter**: `detect_setup`
  accepts an optional `open_interest_provider`. If unset (default — the
  common case until an `OpenInterestDataset` exists), the OI-flush rule
  never fires and never blocks a trade; `oi_change` in the instrumentation
  snapshot is `NaN`. This is a scope limitation stated in code and in
  §7 of the eventual research report, not a silently-skipped feature.

### 1.8 Fair Value Gap (FVG)

- **Why**: three-candle price geometry where no trading occurred at some
  prices (`bar[i-1].high < bar[i+1].low` for a bullish gap) is read as an
  inefficiency likely to attract a retest.
- **Hypothesis**: untraded price ranges get revisited before a move
  continues (a "fill" tendency).
- **Microstructure support**: the *geometric definition* is completely
  unambiguous — this is the least contested SMC concept precisely because
  it requires no interpretation, only three consecutive highs/lows. The
  *fill tendency* itself is empirically debated in public research; treating
  it as ground truth would be an unjustified assumption.
- **Overfitting risk**: low for the definition; the risk is entirely in
  *how much weight* it's given, which is why it is a strictly optional,
  independently toggleable confirmation filter (Phase 4 requirement) rather
  than baked into the core setup — so its actual marginal contribution can
  be measured with A/B backtests instead of assumed.
- **Decision — kept, optional filter, minimum-size threshold in ATR units**
  to exclude noise-level gaps (§2.9).

### 1.9 Order Block

- **Why**: SMC framing — the last opposite-direction candle before an
  impulsive (displacement) move is read as the origin of the move, and a
  retest of its range is read as a high-probability re-entry.
- **Hypothesis**: that candle's range marks where the informed side was
  still accumulating before displacing price.
- **Microstructure support**: **weakest of all concepts in this
  specification.** Definitions vary widely across SMC sources (last
  opposite candle vs. origin-of-displacement candle vs. last candle before
  a break of structure, etc.), and none are order-flow-verifiable without
  data we don't have. This is closer to a heuristic pattern than a tested
  mechanism.
- **Overfitting risk**: high if used unconditionally — it is the rule most
  likely to look good on a specific historical sample by coincidence.
- **Decision — kept only as a strictly optional, independently toggleable
  confirmation filter** (never part of the baseline setup, per Phase 4),
  narrowly and explicitly defined (§2.10) as *the last opposite-signed-body
  candle immediately preceding a qualifying displacement bar*, exactly one
  candle, no alternative definitions. Its evidentiary weakness is stated
  here precisely so nobody mistakes "implemented" for "validated."

### 1.10 Strong Close

- **Why**: distinguishes a bar that closed near its extreme (conviction)
  from one that closed mid-range (indecision) — used both for displacement
  confirmation and for the reclaim bar itself.
- **Hypothesis / support**: standard Close-Location-Value construction,
  unambiguous, well precedented.
- **Decision — kept as-is** (§2.11), no changes needed.

### 1.11 Trend / Range / Market Regime

- **Why**: context for interpreting a sweep — the hypothesis is a
  *reversal*, and reversal setups plausibly behave differently in trending
  vs. ranging conditions.
- **Decision — reuse, don't reinvent**: `market_regime/market_state.py`
  already implements a deterministic ADX-based trend/range classifier,
  EMA-cross bias, and ATR-percentile volatility classifier
  (`TASKS.md` #6). Defining a second, strategy-local notion of "trend" would
  create two inconsistent sources of truth for the same concept — a
  correctness risk, not a research one. This strategy reads
  `context.regime.current()` for `trend`/`volatility`/`bias` and logs it
  into every trade's instrumentation, but does **not** hard-gate entries on
  it by default (`require_ranging_regime: bool = False`). Hard-gating on an
  untested assumption ("this only works in ranging markets") would itself
  be an unvalidated parameter choice; instead regime is logged on every
  trade specifically so a future feature-importance study (the exact thing
  Phase 6 instrumentation exists for) can determine empirically whether
  regime predicts edge, rather than assuming it upfront.

### 1.12 Design decisions that fall out of the above (stated once, apply throughout)

1. **Stop-loss = the sweep's own extreme** (± a small ATR buffer,
   configurable). This is deliberate: the hypothesis is falsified exactly
   when price re-takes and holds beyond the level it supposedly swept and
   failed at. Tying the stop to the falsification condition (rather than a
   generic ATR-multiple stop unrelated to *why* the trade was taken) is a
   research-grade property — the stop tests the hypothesis, it isn't a
   separate risk knob layered on top of it.
2. **Take-profit anchored to "value"** (VWAP or volume-profile POC/VAH/VAL —
   already available via `features/indicators/volume.py`), consistent with
   "reversal to value," with a configurable fixed R-multiple as a fallback
   when no value anchor is resolvable. Both are configurable exit models,
   neither is hardcoded.
3. **Confidence score** is a capped, deterministic weighted sum over: pool
   strength (touch count), displacement magnitude, absorption score, and
   presence of delta divergence / FVG / order-block confluence when those
   optional filters are enabled, blended with regime fit. Default weights
   are equal/round numbers, explicitly **not fit to historical performance**
   — stated here so nobody mistakes the default weighting for an optimized
   one later.
4. **FVG and Order Block are opt-in, independently toggleable, off by
   default in the baseline config** — required by Phase 4, and independently
   justified above by both being the weakest-evidence concepts in the set.

---

## 2. Mathematical definitions

All formulas operate on a single OHLCV `DataFrame` indexed by bar; `i` is the
current (most recently closed) bar index. All lookback/threshold parameters
below are strategy config fields — nothing is a hardcoded literal in code.

### 2.1 Liquidity Sweep

Given a liquidity pool level `L` (from §2.2) and its side (resistance-side
pool → sweep-high; support-side pool → sweep-low):

```
sweep_high(i, L)  := bar[i].high  > L + sweep_margin_atr_mult * ATR[i]
                      AND exists j in [i, i + reclaim_window_bars]:
                            bar[j].close < L
sweep_low(i, L)   := bar[i].low   < L - sweep_margin_atr_mult * ATR[i]
                      AND exists j in [i, i + reclaim_window_bars]:
                            bar[j].close > L
```

`j = i` is allowed (same-bar reclaim — the strongest form). The setup fires
on the bar `j` where reclaim is first confirmed, not on the sweep bar itself
(no look-ahead: at bar `j` we know both the sweep and the reclaim already
happened).

Parameters: `sweep_margin_atr_mult` (default 0.1 — small, deliberately below
one full ATR since a "sweep" is a marginal breach, not a large move),
`reclaim_window_bars` (default 3 — a small integer structural bound: reclaim
must be fast to be a rejection, not a slow trend change; not tuned against
outcomes).

### 2.2 Liquidity Pool (Equal Highs / Equal Lows)

Swing points first (§2.3's pivot definition). A pool is a set of `>=
min_touches` swing highs (or lows) whose pairwise price distance is `<=
tolerance_atr_mult * ATR` at the time of each touch, within a trailing
`pool_lookback_bars` window. Pool level `L` = mean of the touch prices.

Parameters: `min_touches` (default 2), `tolerance_atr_mult` (default 0.15),
`pool_lookback_bars` (default 100).

### 2.3 Swing Points, Break of Structure (BoS), Change of Character (ChoCH)

**Swing high** at bar `k`: `bar[k].high` is strictly greater than
`bar[k-fractal_width .. k-1].high` and `bar[k+1 .. k+fractal_width].high`
(standard fractal/pivot; confirmed `fractal_width` bars later — no
look-ahead once confirmed). **Swing low**: symmetric on lows.

State: `last_swing_high`, `last_swing_low`, and `structure_direction` ∈
{UP, DOWN}, updated as swing points confirm (UP after a higher-high +
higher-low pair, DOWN after a lower-high + lower-low pair).

```
BoS(i)   := close[i] breaks last_swing_point in the SAME direction as
            structure_direction   (continuation)
ChoCH(i) := close[i] breaks last_swing_point OPPOSITE to
            structure_direction   (first countertrend signal)
```

"Structure shift" is not a separate third term — it is `ChoCH`.

Parameters: `fractal_width` (default 2 — the minimum width that defines a
local extremum at all, not tuned).

### 2.4 Displacement

```
displacement(i) := true_range(i) >= displacement_atr_mult * ATR[i]
                    AND strong_close(i) in the direction of the move
```

Parameters: `displacement_atr_mult` (default 1.5 — chosen as "clearly above
one normal bar," a round, interpretable number, not backtested).

### 2.5 Absorption (proxy)

```
volume_per_range(i) := volume[i] / true_range(i)      (true_range(i) > 0)
absorption_score(i)  := rolling_percentile_rank(volume_per_range, lookback)[i]
```

Absorption confirmed when `absorption_score(i) >= absorption_percentile`.
Parameters: `lookback` (default 100, shared with other percentile features
for consistency), `absorption_percentile` (default 80).

### 2.6 Delta Proxy and Delta Divergence

```
delta_proxy(i) := volume[i] * ((close[i]-low[i]) - (high[i]-close[i]))
                   / (high[i] - low[i])                (high[i] != low[i])
cvd_proxy(i)    := cumsum(delta_proxy)[i]
```

Divergence at a sweep-low bar `i` over lookback window `W`:
```
bullish_delta_divergence(i) := low[i] == min(low[i-W:i+1])
                                AND cvd_proxy[i] > min(cvd_proxy[i-W:i+1])
```
(price makes a new low, cumulative delta proxy does not) — symmetric for
sweep-highs / bearish divergence. If an `order_flow_provider` supplying real
trade-side delta is injected, it replaces `delta_proxy` with no change to
the divergence test itself.

Parameters: `divergence_lookback_bars` (default = `reclaim_window_bars`'s
pool-scale cousin, 20 — separate from the sweep-reclaim window because
divergence is evaluated over the run-up to the sweep, not the reclaim).

### 2.7 Open Interest Flush (optional, data-gated)

```
oi_flush(i) := open_interest_provider is not None
               AND (OI[i] - OI[i-oi_lookback_bars]) / OI[i-oi_lookback_bars]
                    <= -oi_flush_drop_pct
```
Returns `False` unconditionally when no provider is injected (today's
default). Parameters: `oi_lookback_bars` (default 3), `oi_flush_drop_pct`
(default 0.05).

### 2.8 Strong Close

```
clv(i) := ((close[i]-low[i]) - (high[i]-close[i])) / (high[i]-low[i])   ∈[-1,1]
strong_close_up(i)   := clv(i) >= strong_close_threshold
strong_close_down(i) := clv(i) <= -strong_close_threshold
```
Parameter: `strong_close_threshold` (default 0.5).

### 2.9 Fair Value Gap (optional filter)

Bullish FVG confirmed at bar `i` (needs bars `i-2, i-1, i`):
```
gap := bar[i].low - bar[i-2].high
bullish_fvg(i) := gap > 0 AND gap >= fvg_min_size_atr_mult * ATR[i]
```
Bearish symmetric (`bar[i-2].low - bar[i].high`). Parameter:
`fvg_min_size_atr_mult` (default 0.1).

### 2.10 Order Block (optional filter)

For a displacement bar at index `d` (§2.4) in direction `dir`: the order
block is the single most recent bar `b < d` with
`sign(close[b]-open[b]) != sign(dir)` (opposite body color) such that no
bar between `b` and `d` also has that property with a larger body — i.e.
scan backward from `d-1` and take the first opposite-colored bar. Its zone
is `[low[b], high[b]]`. Exactly one definition, no alternatives, per the
research-review decision in §1.9. Parameter: none beyond `displacement`'s
own (the block is derived, not independently thresholded, to avoid adding a
second free parameter to the weakest-evidence concept).

### 2.11 Trend / Range / Market Regime

Reused verbatim from `market_regime/market_state.py::compute()` — ADX
`>= trend_threshold` and not range-compressed ⇒ `TRENDING`, else `RANGING`;
ATR-percentile `>= vol_threshold_percentile` ⇒ `HIGH` volatility;
EMA-fast-vs-slow-with-slope ⇒ `BULLISH`/`BEARISH`/`NEUTRAL` bias. No new
definition introduced (§1.11).

---

## 3. Setup definition (baseline, no optional filters)

A long setup at bar `i` requires, in order:

1. A support-side liquidity pool `L` exists (§2.2) with `>= min_touches`.
2. `sweep_low(i, L)` confirmed (§2.1) — reclaim bar is `i`.
3. `displacement` confirmed on the reclaim leg within
   `displacement_confirm_window_bars` bars of `i` (§2.4), direction up.
4. Optional filters (§2.9 FVG, §2.10 order block, §2.7 OI flush,
   §2.6 delta divergence — divergence is **on by default** since it is
   purely OHLCV-derived and cheap to evaluate, unlike FVG/OB which are the
   Phase-4-mandated toggleable ones) evaluated and recorded regardless of
   whether they're required to gate entry.

Short setup is the fully symmetric mirror.

`check_entry` does not add a second independent condition — the setup
detector already encodes the full falsifiable claim; `check_entry` exists in
the framework as a veto point and is used here only to re-validate that
`stop_loss()` is still on the correct side of price at confirmation time
(protects against a pathological same-bar case, not a new rule).

---

## 4. Remaining open question carried into implementation

`min_touches`, ATR multiples, and lookback windows above are stated with
defaults but **none are backtested or fit** — per the explicit instruction
not to optimize parameters, these are chosen for interpretability
(round numbers, minimum-viable thresholds) and left as config fields for
future, separate, out-of-scope research.

---

## 5. Trade explainability (Phase 5)

Every `Setup` the strategy emits carries a `reasoning` string built by
`LiquidityExhaustionReversalStrategy._build_reasoning()`
(`strategies/examples/liquidity_exhaustion_reversal.py`) with one line per
required field, in order: **Market regime**, **Primary hypothesis**,
**Entry reason**, **Evidence supporting trade**, **Evidence against trade**,
**Triggered rules**, **Rejected/absent rules**, **Invalidation condition**,
**Expected holding time**. This is the only place these are stored as prose
(they are re-derived from the same `metadata` dict that also drives
`confidence()`, so the text can never disagree with the numbers). The
remaining Phase 5 fields (Symbol, Direction, Confidence Score, Risk %,
Position Size, Stop Loss, Take Profit) are not duplicated into the text —
they already exist as first-class, separately-typed fields on `Signal` /
`SignalEvent` / `JournalEntry` (`strategies/signal.py`, `core/events.py`,
`journal/journal_recorder.py`), which is the more robust place for a number
that downstream code (the risk engine, the journal CSV exporter) needs to
read and compare, not parse out of a string.

## 6. Research instrumentation (Phase 6)

Every `Setup.metadata` (`dict[str, float]`) is merged into
`SignalEvent.features_snapshot` and then into `JournalEntry.features_snapshot`
(this required one small, generally-applicable engine fix: `backtesting/engine.py`
previously only ever wrote a fixed 5-indicator snapshot and silently ignored
`Setup.metadata` for *every* strategy, not just this one — see the code comment
at the merge site). The full set logged per trade:

| Feature | Source | Notes |
|---|---|---|
| `sweep_extreme`, `sweep_size`, `sweep_duration_bars` | §2.1 | the swept bar's price, its distance from the pool, bars-before-trigger |
| `pool_level`, `pool_touches` | §2.2 | the liquidity pool that was swept |
| `retracement_pct` | derived | how far price has already retraced from the extreme toward the pool at signal time |
| `atr`, `adx`, `trend_strength_adx` | built-in indicators | `adx` duplicated as `trend_strength_adx` to match the requested vocabulary |
| `ema_20`, `ema_50`, `ema_200`, `rsi_14`, `macd_line`, `macd_hist` | built-in indicators | |
| `volume`, `vwap`, `poc`, `vah`, `val` | built-in + new `volume_profile_vah`/`val` (§ below) | |
| `distance_to_poc`, `distance_to_vah`, `distance_to_val` | derived | `price - anchor` |
| `funding_rate` | `context.funding_rate` (new `StrategyContext` field, §7) | current bar only |
| `delta_proxy`, `cvd_proxy` | §2.6 proxy | explicitly a proxy, see §1.6 |
| `absorption_score`, `absorption_confirmed` | §2.5 proxy | |
| `delta_divergence_confirmed`, `fvg_confirmed`, `fvg_size`, `order_block_confirmed`, `order_block_size` | §2.6, §2.9, §2.10 | confluence flags, logged regardless of whether `require_*` gates on them |
| `oi_flush_confirmed`, `open_interest_change` | §2.7 | **always** `0.0` / `NaN` — no data source exists (§0) |
| `liquidations` | — | **always** `NaN` — no data source exists (§0), never fabricated |
| `structure_direction` | §2.3 | `1.0`/`-1.0`/`0.0` |
| `session`, `day_of_week` | derived from `context.ts` | session bucket 0=Asia/1=London/2=NY/3=late-US (UTC hour, see `_session_bucket`), day-of-week 0=Monday |
| `market_regime_trending`, `market_regime_high_volatility` | `context.regime` | the trend/bias/volatility *strings* are also captured verbatim, unencoded, in `SignalEvent.regime_snapshot` / `JournalEntry.market_regime` — these numeric duplicates exist only because `Setup.metadata` is float-only |
| `volatility_regime_atr_percentile`, `liquidity_regime_volume_percentile` | new `atr_percentile` (existing) + new `volume_percentile` indicator (§7) | |

Confidence Score is intentionally **not** duplicated into this table — it is
already a first-class field on `JournalEntry`/`SignalEvent`, computed from
this same metadata, so storing it a second time inside the metadata it was
computed from would be circular.

## 7. Architecture overview

```
strategies/liquidity_exhaustion_reversal/
  structure.py       swing points, liquidity pools, sweep+reclaim, BoS/ChoCH
  microstructure.py  displacement, absorption, delta proxy, FVG, order block
  config.py          LiquidityExhaustionReversalConfig -- every threshold
  indicators.py       registers all of the above into FeatureEngine
                       (features/feature_engine.py::register_indicator, new)
strategies/examples/liquidity_exhaustion_reversal.py
                       the Strategy subclass -- reads everything through
                       context.features.get(...), same as any built-in indicator
```

`structure.py`/`microstructure.py` are pure `DataFrame -> Series/DataFrame`
functions with no dependency on the Strategy Framework at all — they are
unit-tested directly (`tests/unit/strategies/liquidity_exhaustion_reversal/`).
`indicators.py` is the only file that wires them into `FeatureEngine`, via a
small new extension point (`register_indicator()`, mirroring
`strategies/registry.py::register_strategy`) added to
`features/feature_engine.py` specifically for this — no existing behavior
changed, indicators already registered are untouched.

Three small, narrow, generally-applicable framework extensions were needed
(all backward compatible, covered by the existing 241-test suite plus the new
tests in this change):

1. `features/feature_engine.py::register_indicator()` — extension point, as above.
2. `features/indicators/volume.py::volume_profile_value_area()` and
   `volume_percentile()` — Value Area High/Low and a volume percentile rank,
   generically useful indicators, not LES-specific, added alongside the
   existing `volume_profile_poc()`.
3. `strategies/context.py::StrategyContext.funding_rate` +
   `backtesting/engine.py`'s merge of `Setup.metadata` into
   `features_snapshot` — see §6. Both fixes apply to *every* strategy, not
   just this one (funding was already loaded by `DataFeed` but never exposed
   to a strategy; `Setup.metadata` existed on the dataclass already but
   nothing downstream ever read it).

Everything else — the sweep/pool/structure/microstructure math, the
`LiquidityExhaustionReversalConfig` dataclass, the strategy class itself — is
new and additive; no existing strategy, indicator, or engine behavior changed.

## 8. Flow (one bar, while flat)

```
CandleEvent
  -> detect_setup(context)
       for side in (support/LONG, resistance/SHORT):
         find a sweep+reclaim within displacement_confirm_window_bars  (§2.1)
         require displacement on the trigger bar                       (§2.4)
         if found: build full metadata (§6), evaluate optional filters
                   (require_absorption / require_delta_divergence /
                    require_fvg / require_order_block / require_oi_flush /
                    require_ranging_regime -- all default off)
       -> Setup | None
  -> check_entry(setup)          stop-loss sanity check only (§3)
  -> stop_loss(setup)            sweep extreme +/- buffer                (§1.12)
  -> take_profit(setup)          value anchor, R-multiple fallback        (§1.12)
  -> position_size(setup)        fixed-fractional off the stop distance
  -> confidence(setup)           weighted, capped, unfit                 (§1.12)
  -> reasoning(setup)            the Phase 5 explainability text
  -> Signal -> risk engine -> (fill next bar's open, per the existing
     deferred-execution model, docs/VALIDATION_REPORT.md)
```

While a position is open, `check_exit()` additionally watches for an
opposing Change of Character (§2.3) ahead of the stop/take-profit — the
hypothesis's own early-invalidation signal, not a separate arbitrary rule.

## 9. Full parameter table

All fields of `LiquidityExhaustionReversalConfig`
(`strategies/liquidity_exhaustion_reversal/config.py`); every one is a
constructor kwarg (`create_strategy("liquidity_exhaustion_reversal", **params)`).

| Field | Default | § |
|---|---|---|
| `atr_period` | 14 | shared |
| `adx_period` | 14 | shared |
| `regime_percentile_lookback_bars` | 100 | shared |
| `fractal_width` | 2 | 2.3 |
| `min_touches` | 2 | 2.2 |
| `tolerance_atr_mult` | 0.15 | 2.2 |
| `pool_lookback_bars` | 100 | 2.2 |
| `sweep_margin_atr_mult` | 0.1 | 2.1 |
| `reclaim_window_bars` | 3 | 2.1 |
| `displacement_atr_mult` | 1.5 | 2.4 |
| `strong_close_threshold` | 0.5 | 2.4, 2.8 |
| `displacement_confirm_window_bars` | 3 | 2.1, 2.4 |
| `absorption_lookback_bars` | 100 | 2.5 |
| `absorption_percentile` | 80.0 | 2.5 |
| `require_absorption` | `False` | 2.5 |
| `divergence_lookback_bars` | 20 | 2.6 |
| `require_delta_divergence` | `False` | 2.6 |
| `oi_lookback_bars` | 3 | 2.7 |
| `oi_flush_drop_pct` | 0.05 | 2.7 |
| `require_oi_flush` | `False` (permanently inert, no data source) | 2.7 |
| `fvg_min_size_atr_mult` | 0.1 | 2.9 |
| `require_fvg` | `False` | 2.9 |
| `order_block_max_lookback_bars` | 20 | 2.10 |
| `require_order_block` | `False` | 2.10 |
| `require_ranging_regime` | `False` | 1.11 |
| `stop_buffer_atr_mult` | 0.1 | 1.12 |
| `take_profit_mode` | `"value"` | 1.12 |
| `take_profit_r_multiple` | 2.0 | 1.12 |
| `value_anchor` | `"vwap"` | 1.12 |
| `vwap_period` | 50 | 1.12 |
| `poc_period` | 50 | 1.12 |
| `poc_bins` | 10 | 1.12 |
| `value_area_pct` | 0.70 | 1.12 |
| `risk_per_trade` | 0.01 | position sizing |
| `confidence_weight_*` (5 fields) | 0.2 each | 1.12 |
| `confidence_pool_touches_saturation` | 5 | 1.12 |
| `confidence_displacement_atr_mult_saturation` | 3.0 | 1.12 |

## 10. Testing (Phase 8)

- **Unit — primitives** (`tests/unit/strategies/liquidity_exhaustion_reversal/`):
  swing detection, edge confirmation lag, clustering, pool formation and
  minimum-touch enforcement, same-bar and multi-bar sweep+reclaim, no-pool
  means no-sweep, BoS/ChoCH bootstrap and flip, CLV/strong-close,
  displacement (range alone is insufficient), absorption ranking, delta
  proxy sign/zero-range safety, CVD cumulation, divergence detection, FVG
  geometry, order block discovery and lookback-exhaustion.
- **Unit — strategy hooks** (`tests/unit/strategies/test_liquidity_exhaustion_reversal.py`):
  registration, config validation, warmup safety, setup detection on an
  engineered pattern, stop-loss = sweep extreme ± buffer (both directions),
  check_entry veto on a nonsensical stop, zero-size on zero stop-distance,
  confidence boundedness, reasoning completeness, and an explicit A/B
  containment test (`require_fvg`+`require_order_block` results are always a
  subset of the baseline's).
- **Integration / backtest sanity + edge cases + walkthrough**
  (`tests/integration/test_liquidity_exhaustion_reversal_backtest.py`): a
  full run through the real `BacktestEngine`, full Phase 6 feature-key
  coverage on real emitted signals, stop/target directional sanity, journal
  integration, a complete example-trade walkthrough asserting every Phase
  5/6 field end-to-end, a config that can never form a pool (zero trades, no
  crash), a strict-subset A/B backtest, a backtest shorter than the warmup
  period, and an unreclaimed deep wick that must not itself signal.
- **Validation against the existing research engine**: no engine changes
  were needed beyond the three narrow, backward-compatible extensions in §7
  — the full pre-existing 241-test suite (Backtrader cross-validation,
  stress tests, OHLCV validation, ruin handling, etc.) still passes
  unmodified, confirming this strategy is a pure addition on top of an
  already-validated core.

## 11. Assumptions, limitations, and sources of bias

- **No real market data was available in this development environment**
  (see `README.md`) — this strategy has been validated on synthetic and
  hand-engineered data only, exactly like the rest of Part A. It has never
  been run against real Binance Futures history.
- **Delta/CVD is an OHLCV-derived proxy**, not real trade-side order flow
  (§1.6, §2.6) — its accuracy is bounded by how well "close-location within
  the bar" approximates intrabar buy/sell pressure, which is a known-crude
  assumption on any bar with a complex intrabar path.
- **Absorption is a volume-per-range proxy** (§1.5, §2.5), not a
  measurement of actual passive/aggressive order imbalance.
- **Open Interest flush and Liquidations are entirely unavailable** — the
  corresponding rule is permanently inert and the corresponding
  instrumentation is always `NaN` (§0, §1.7). Nothing about this system's
  behavior should be attributed to those two concepts until real datasets
  exist.
- **Order Block is the weakest-evidence concept implemented** (§1.9) —
  kept strictly optional and off by default for exactly this reason.
- **Single-symbol, single-timeframe** — no multi-timeframe confluence
  (e.g. a higher-timeframe bias filter) is implemented; `market_regime` is
  logged but not used as a hard gate by default (§1.11), so its predictive
  value (if any) is still an open, testable question, not an assumption
  baked into the strategy.
- **Fractal-based swing detection has a fixed confirmation lag**
  (`fractal_width`, default 2 bars) — real-time use would see a signal at
  most `fractal_width` bars later than a `.iloc[]`-indexed backtest might
  suggest at a glance; the causality analysis in §2.3 confirms this lag is
  correctly respected (a swing point is never used before it is confirmed),
  but it is worth restating plainly here.
- **Confidence weights are equal by construction** (§1.12) — this is a
  starting point for future feature-importance research (the entire point
  of §6's instrumentation), not a validated weighting.
- **No transaction-cost or capacity modeling specific to this strategy** —
  it relies entirely on the existing backtest engine's fee/slippage model
  (`docs/VALIDATION_REPORT.md`), which is symbol/strategy-agnostic.
- **Selection bias**: this is the *only* strategy implemented on this
  platform, chosen and specified by the user rather than selected from a
  universe of candidates after backtesting — the usual "best of N
  backtested strategies" survivorship-bias concern does not apply here, but
  the inverse risk (a single untested hypothesis, however carefully
  reasoned, having no comparison point) is real and is exactly why Phase 4's
  optional filters and Phase 6's instrumentation exist: to make this
  falsifiable and improvable rather than a one-shot bet.

## 12. Suggested future experiments

1. **A/B backtests over real data** once available: baseline vs.
   `require_fvg`, vs. `require_order_block`, vs. both — directly testable
   because both are strictly optional and produce a strict subset of the
   baseline's setups (verified in §10's tests).
2. **Feature-importance analysis** on the full §6 instrumentation table
   against realized trade P&L, once enough real trades exist — this is the
   entire reason every feature is logged per-trade rather than only the ones
   the strategy currently gates on.
3. **`require_ranging_regime` sensitivity** — test whether gating on
   `TrendState.RANGING` improves or hurts expectancy, rather than assuming
   either answer.
4. **Real order flow**: replace `delta_proxy`/`cvd_proxy` with real
   trade-side data (and add an `OpenInterestDataset` for §2.7) once a
   trade-level data source exists, via the same indicator names — no
   strategy-logic change required, only `indicators.py`'s internals.
5. **Multi-timeframe confluence**: does a higher-timeframe pool/sweep
   improve the lower-timeframe hypothesis? Not implemented, deliberately, to
   keep this specification single-timeframe and falsifiable on its own
   terms first.
6. **Cross-symbol robustness**: run unchanged (no re-tuning) against other
   Binance Futures symbols to check whether the round-number defaults hold
   up out of sample, before ever considering per-symbol tuning.
7. **Walk-forward validation** using the existing
   `optimization/walk_forward.py` machinery — explicitly a *future*,
   separate exercise; none of this specification's parameters have been
   walk-forward validated or optimized.

## 13. Parameters intentionally left unoptimized

Every field in §9's table is a round, interpretable default chosen for
that reason alone — minimum-viable thresholds (`min_touches=2`,
`fractal_width=2`), scale-invariant ATR multiples chosen to be "clearly
above/below one normal bar" rather than fit (`sweep_margin_atr_mult=0.1`,
`displacement_atr_mult=1.5`), equal confidence weights (`0.2` each), and a
70% value area (the standard Market Profile convention, not a fitted
number). None have been backtested, grid-searched, or walk-forward
optimized as part of this work, per the explicit instruction governing this
entire specification — that is future, separate research (§12.7), and it
should start from these defaults, not from values already reverse-engineered
to fit a specific historical sample.
