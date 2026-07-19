# Research Engine Validation Report

**Scope:** a full audit of Part A (Research & Backtesting Engine) — historical data
handling, the strategy framework, portfolio/risk accounting, the event-driven
backtest engine, analytics, optimization/walk-forward, and the trade journal —
performed before any new functionality was added, at the standard of "would this
survive review at a professional quantitative trading firm."

**Result:** 8 real issues found and fixed (4 critical, 1 high, 2 medium, 1
transparency gap), all with regression tests. Test suite grew from 158 to 196
tests, all passing; ruff/black/mypy clean; a real backtest re-run end-to-end via
the CLI after every fix.

---

## 1. Findings and fixes

### 1.1 CRITICAL — Same-bar signal generation and execution (look-ahead-adjacent bias)

**Finding:** the backtest engine generated a trading signal from a bar's close price
and then filled the resulting order **at that same bar's close** — i.e., it assumed
you could observe a candle closing and have an order already filled at that exact
price, with zero latency. This is a well-known, systematic source of optimistic bias
in naive backtesters: it removes an entire bar's worth of adverse price movement
between "deciding to trade" and "actually being in the trade."

**Fix:** entries and strategy-driven exits (`check_exit`) are now decided from a
bar's close but queued as a `_PendingOrder` and filled at the **next** bar's open
(`backtesting/engine.py`). Stop-loss and take-profit exits are the deliberate
exception — they're checked against the *current* bar's high/low using a level that
was fixed *before* the bar started, so no such delay applies (that's a real,
already-live protective order, not a new decision).

**Bonus fix bundled in:** stop-loss and take-profit fills now account for
gap-through. A stop can't fill better than the bar's open if price already gapped
past it before the bar started trading (`_resolve_stop_loss`); a take-profit is
modeled as a limit order, so a favorable gap fills at the *better* open price
instead of being capped at the target (`_resolve_take_profit`). Previously both
always filled at the exact preset level regardless of gaps, which is optimistic for
stops and just wrong for limit-style take-profits.

**Tests:** `tests/unit/backtesting/test_execution_timing.py` (7 tests) — proves a
decision bar's close and the actual fill price are different and that the fill
matches the *next* bar's open; proves gap-through pricing in both directions for
both stop and take-profit, long and short; a no-gap regression test confirms normal
intrabar stops still fill at the exact level.

### 1.2 CRITICAL — `ensure_range()` silently tolerated unfillable data gaps

**Finding:** `HistoricalDataset.ensure_range()` (the method that downloads missing
data and returns a complete range) ended by calling its own strict `load()` with
`allow_gaps=True` — meaning if the upstream source genuinely had no data for part of
the requested range (a symbol not yet listed, an exchange outage, a permanent hole in
history), the method **silently returned an incomplete range** instead of telling the
caller. This defeated the entire purpose of the gap-detection mechanism: a backtest
could run on data that looks complete but isn't, with no warning.

**Fix:** `ensure_range()` is now strict by default — it attempts to backfill, then
raises `DataGapError` if gaps remain, exactly like `load()`. An explicit
`allow_gaps=True` parameter exists for callers who deliberately want to tolerate
this. `DataFeed.load()` applies this asymmetrically on purpose: **candle gaps are a
hard failure** (a backtest on incomplete price data isn't trustworthy), but
**funding-rate gaps degrade gracefully** with a logged warning (funding is
enrichment data — its absence means those periods are treated as zero funding cost,
a real but bounded and now-visible degradation, not a reason to block the backtest).

**Tests:** `tests/unit/market_data/test_dataset.py` (+2 tests: strict-by-default
raises, `allow_gaps=True` still works) and `tests/unit/backtesting/test_data_feed.py`
(new file, 2 tests: candle gap raises, funding gap logs a warning and continues).

### 1.3 CRITICAL — No sanity validation on strategy-provided stop-loss/take-profit

**Finding:** nothing validated that a strategy's `stop_loss()`/`take_profit()`
returned a price on the sane side of `entry_price` for the signal's direction. A
strategy bug (e.g., a sign error in an ATR offset) producing a stop *above* entry
for a long would silently open a position that appears to "stop out" on its very
first bar (since `low <= stop` is almost always true when `stop` is above the entry
price) — with no error anywhere, just quietly wrong backtest results.

**Fix:** `BacktestEngine._stop_take_profit_are_sane()` validates direction before a
position is opened; an invalid stop/target is rejected (published as a
`RiskRejectedEvent` with a clear reason) rather than executed.

**Tests:** `tests/unit/backtesting/test_signal_validation.py` (6 tests) — long/short,
bad stop/bad target, each rejected; confirms a valid signal still trades normally;
confirms the signal is still persisted (for audit) even when rejected.

### 1.4 CRITICAL — No account-ruin handling

**Finding:** there is no liquidation/margin-call mechanic. An over-levered position
(easy to construct: `RiskLimits()` defaults to *no* leverage or notional cap — see
§1.7) could drive account equity arbitrarily negative on an adverse move, and the
engine would keep "trading" with negative equity, producing nonsensical downstream
results (though position-sizing does floor to zero once equity is non-positive, an
*already open* losing position was never force-closed).

**Fix:** after recording equity each bar, if it's `<= 0` the engine force-closes any
open position (tagged with a new `ExitReason.RUIN`) and halts — no further bars are
processed. `BacktestResult.ruined: bool` surfaces this to callers.

**Tests:** `tests/unit/backtesting/test_ruin.py` (3 tests) — a crash scenario
triggers ruin and a `RUIN`-tagged close; no further bars/equity points are
processed after ruin; a normal run is unaffected.

### 1.5 HIGH — Walk-forward windows had no indicator warmup buffer

**Finding:** `run_walk_forward()` sliced each train/test window with no lookback
buffer before it. Indicators (e.g., a 30-period EMA) need real history to produce a
value — a `StrategyContext` querying an indicator inside that warmup gap raises
`InsufficientDataError`, which every example strategy catches and treats as "no
signal." The practical effect: the first N bars of *every* window — most
importantly, out-of-sample test windows — silently produced zero signals while
indicators filled up, quietly shrinking the effective (and specifically
out-of-sample) sample size and biasing which bars actually got evaluated.

**Fix:** `optimization/walk_forward.py` now extends every train/test slice backward
by a configurable `warmup_bars` (default 50), then sets
`BacktestConfig.warmup_bars` to the *actual* number of buffer bars present (measured
from the slice, not assumed, so it's correct even with off-by-one/edge-of-data
effects) so those buffer bars feed indicators but are excluded from
signal/trade/equity evaluation.

**Tests:** `tests/unit/optimization/test_walk_forward.py` (+4 tests) — the buffer
slice extends backward by the right amount; it clips correctly at the start of
available data instead of erroring; a direct proof that a 30-period indicator is
valid at the very first evaluated bar with the buffer, and would have raised
`InsufficientDataError` at that same point without it; `run_walk_forward` accepts a
custom `warmup_bars`.

### 1.6 MEDIUM — `VolumeParticipationSlippage` had a broken interface and was unused

**Finding:** `VolumeParticipationSlippage.__init__` took `bar_volume`/
`order_quantity` as *constructor* arguments and pre-computed a fixed slippage
amount — meaning a single instance could only ever be correct for the one bar/order
size it was constructed with. Since `BacktestCosts`/`BrokerSimulator` hold one
shared slippage model instance for an entire backtest, this class was unusable as
designed. It was also never wired into `BacktestConfig` (only `FixedBpsSlippage`
was hardcoded) and had zero test coverage — effectively dead code advertised in the
architecture but not actually available.

**Fix:** `SlippageModel.apply()`'s signature now takes `quantity`/`bar_volume` as
call-time parameters (all three implementations updated;
`BrokerSimulator.fill()`/engine call sites thread `bar_volume=event.volume`
through). `BacktestConfig` gained a `slippage_model: SlippageModel | None` field
that overrides the default `FixedBpsSlippage(slippage_bps)`, so it's now genuinely
selectable.

**Tests:** `tests/unit/backtesting/test_slippage_models.py` (6 tests) — reusability
across different quantity/bar_volume per call (the actual bug), correct
buy-worse/sell-better direction, zero-bar-volume doesn't divide by zero, and an
engine-level integration test proving it's selectable through `BacktestConfig` and
actually affects real fills end to end.

### 1.7 MEDIUM — `Symbol` didn't normalize case

**Finding:** `Symbol.parse()` uppercases correctly, but `Symbol` can also be
constructed directly (`Symbol(base="btc", quote="usdt")`), which every other module
does when passed a value from elsewhere. Since `Symbol` is frozen and used as a key
(Parquet file paths via `native()`, feature-cache keys, `PositionTracker`/
`PortfolioManager` dict keys via `canonical`), a case mismatch would silently
fragment identity — `Symbol(base="btc", ...)` and `Symbol(base="BTC", ...)` compare
unequal and hash differently, so they'd address *different* cache entries, *different*
Parquet files, and *different* position-tracking slots for what a user would
reasonably expect to be the same symbol.

**Fix:** `Symbol.__post_init__` normalizes `base`/`quote` to uppercase unconditionally,
including for direct construction.

**Tests:** `tests/unit/core/test_types.py` (4 tests) — direct lowercase/mixed-case
construction normalizes and compares/hashes equal to the uppercase form; `.parse()`
behavior is unchanged.

### 1.8 Risk transparency — implied leverage/notional exposure

**Finding:** `RiskLimits()` defaults to *no* `max_leverage`/`max_position_notional`
cap. This is not "fixed" with an invented default number — there is no
universally-correct leverage cap; it's a strategy- and account-specific decision
that belongs to whoever configures the risk engine, and guessing one would be its
own unjustified assumption. But leaving it silently unbounded with no visibility
into what leverage a trade actually implied was a real gap.

**Fix:** `RiskDecision` (`risk/pre_trade_checks.py`) now reports `notional` and
`implied_leverage` on every approved decision. `JournalEntry` surfaces the same
`implied_leverage` (computed from the actual fill price/quantity against
`equity_at_signal`), independent of whether a stop-loss exists (so it's populated
even for the `risk_pct` field's blind spot — no-stop trades). Both are in the CSV
export. **This does not cap anything** — it makes exposure auditable so an operator
configuring a strategy without limits can see exactly what they've left unbounded,
rather than finding out from a drawdown.

**Tests:** `tests/unit/risk/test_pre_trade_checks.py` (+3 tests, including one that
explicitly demonstrates 100x implied leverage sailing through an unconfigured
`RiskLimits()` unblocked — a deliberately visible, not silent, characteristic) and
`tests/unit/journal/test_journal_recorder.py` (+1 test).

---

## 2. What was verified

- **196 unit tests pass** (up from 158 before this audit), including 33 new tests
  added specifically for the findings above.
- **ruff, black --check, mypy** all clean across the full source tree.
- **Real end-to-end CLI runs** (`scripts/run_backtest.py`) against Parquet-backed
  synthetic data (shaped like a real download — this sandbox has no outbound access
  to Binance's API) for both example strategies, before and after every fix in this
  audit, confirming the engine still produces a complete run with sane, internally
  consistent output (equity curve, trade journal with the new `implied_leverage`
  column populated, analytics summary) and not just passing isolated unit tests.
- **Numeric consistency spot-checks**: fee/slippage/funding cost decomposition
  (`gross_pnl - fees - funding == net_pnl`) reverified after the execution-timing
  rewrite; R-multiple, Sharpe/Sortino/CAGR/max-drawdown formulas reverified against
  hand-computed reference values (pre-existing tests, re-run clean after all
  changes).
- **Every fix's test suite includes at least one test that would have failed under
  the pre-fix behavior** (not just "the new code works," but "the old code was
  wrong at this specific point") — verified by construction of the fixtures (e.g.
  `gapped_entry_df`'s decision-bar close vs. next-bar-open are deliberately
  different numbers).

## 3. Assumptions that remain (deliberate, not defects)

- **Reject-vs-scale asymmetry in `risk/pre_trade_checks.py`**: a notional/leverage
  breach hard-rejects the trade; a risk-per-trade breach scales the quantity down
  instead. Both are defensible risk-management philosophies (reject on a hard
  operational limit vs. scale to fit a soft budget) and this was a deliberate
  choice to leave alone rather than force artificial consistency — changing it is a
  policy decision for whoever operates the risk engine, not a bug fix.
- **`float`, not `Decimal`, throughout the research engine** — matches the
  vectorized pandas/numpy pipeline; exchange tick/lot-size precision is a Part B
  (live execution) concern, documented in `core/types.py` since the original
  implementation.
- **Same-bar funding accrual on a same-bar entry**: if a position opens via a
  pending-order fill at the exact bar that also coincides with a funding timestamp,
  funding is charged for that bar. This is a reasonable granularity choice at
  hourly-bar resolution, not a bug — flagged here for visibility.
- **Confidence score formula** (`strategies/base_strategy.py`'s default) is a
  hand-calibrated heuristic (ADX-based trend quality blended with regime-fit), not
  empirically validated against real outcomes. It's documented as a default a
  strategy should override, not a scientifically-derived formula.
- **Symbol-parsing heuristic** (`Symbol.parse()`'s quote-currency suffix matching)
  only recognizes USDT/USDC/BUSD/BTC quote currencies, sufficient for the
  Binance-Futures-only V1 scope but not general.

## 4. Known limitations (out of scope for this audit — features, not bugs)

- **No partial fills / scale-in / scale-out.** `PositionTracker` supports exactly
  one full-size open and one full-size close per symbol. Many real strategies scale
  positions; adding that is a feature, not a fix, and wasn't attempted here.
- **Single-symbol backtests only.** One `DataFeed`/`BacktestEngine` instance trades
  one symbol. Portfolio-level, multi-symbol backtesting is a Part A extension not
  yet built.
- **No liquidation/margin-call *mechanic*** beyond the new hard-stop-at-ruin (§1.4).
  A real exchange would liquidate a position well before equity hits exactly zero,
  based on maintenance margin requirements this engine doesn't model. The ruin
  handling here prevents nonsensical negative-equity output; it does not simulate
  realistic liquidation price/timing.
- **PDF journal export is a stub** (raises `NotImplementedError`) — needs a
  rendering dependency not currently justified for this milestone. CSV export is
  fully functional.
- **Data quality validation beyond gap detection** (malformed rows, zero-volume
  bars, outlier prices from bad exchange data) is not implemented — `find_gaps()`
  only detects *missing* timestamps, not corrupt values at present ones.
- **Not yet run against real Binance data** — this development sandbox has no
  outbound network access to Binance's API (confirmed via a direct request, which
  returned a proxy 403). Every fix in this audit was validated against synthetic
  data shaped like a real download. Re-running the full suite and a real CLI
  backtest from an environment with network access remains the outstanding step
  before this is fully production-validated (tracked as `TASKS.md` A15.1/A15.5).
- **Database persistence** (`TASKS.md` Phase A4/A5) is still not implemented — no
  Postgres was available in this sandbox to test against; this audit did not
  revisit that decision.
