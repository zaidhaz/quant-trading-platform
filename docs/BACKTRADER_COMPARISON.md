# Cross-Validation Against Backtrader

**Purpose:** before implementing the first production strategy, validate this
platform's backtesting engine against an established, independently-developed
backtesting library — [Backtrader](https://www.backtrader.com/) — run under
identical data, fees, slippage, and a simple benchmark strategy, and account for
every difference found.

**Result:** on every round-trip trade both engines actually completed, prices and
P&L match to float64 precision (~1e-14, i.e. floating-point noise, not a real
difference). Two real discrepancies were found during this process; both were
understood, and one was fixed (the other is an explained, intentional design
choice — see §3). One live finding also confirmed that this engine's execution
timing fix (from the prior correctness audit) matches an established library's
default behavior exactly.

---

## 1. Methodology

A moving-average crossover is the standard, well-understood benchmark for this
kind of validation, but comparing two engines' *own* SMA/EMA implementations risks
measuring an irrelevant confound: different libraries make different (both
defensible) choices about indicator warmup/seeding, and a mismatch there would
masquerade as an execution bug when it's really just two valid ways to compute a
moving average.

To isolate what actually matters here — **order execution timing, fee application,
slippage application, and P&L accounting** — the crossover signal was precomputed
**once**, with plain pandas (`close.rolling(10).mean()` / `close.rolling(30).mean()`,
crossing detected as a sign change), and fed as an identical sequence of
entry/exit decisions into both engines. Neither engine computes its own moving
average in this comparison. This means: any difference in results can only come
from what each engine does *after* a signal fires, which is exactly what needs
validating before a real strategy is built on top of this engine.

**Held identical between both engines:**

| Parameter | Value |
|---|---|
| Data | 500 bars of synthetic hourly OHLCV (deterministic, seeded), fed to both engines from the same in-memory DataFrame |
| Strategy | Long-only SMA(10)/SMA(30) crossover — enter on golden cross, exit on death cross, no stop-loss/take-profit |
| Position size | Fixed 1.0 unit per trade (no compounding, no risk-based sizing — another confound removed) |
| Initial capital | 100,000 |
| Fee | 10 bps of notional per fill (`taker_fee_rate=0.001` / `broker.setcommission(commission=0.001)`) |
| Slippage | 5 bps, adverse to the trader (`FixedBpsSlippage(bps=5.0)` / `broker.set_slippage_perc(perc=0.0005, slip_open=True)`) |
| Funding | Disabled on both sides (Backtrader has no native perpetual-funding concept; not a relevant confound for this comparison) |

Full harness: `tests/integration/test_backtrader_comparison.py` (runs automatically
if `backtrader` is installed — `pip install -e ".[validation]"` — and is otherwise
skipped; it's a validation-only dependency, not a runtime one).

## 2. Headline result

500-bar run, seed 7 — 10 golden crosses, 10 death crosses (every entry has a
matching exit before the data ends):

| | This engine | Backtrader |
|---|---|---|
| Closed trades | 10 | 10 |
| Final equity | 100,004.786519 | 100,004.786519 |
| Difference | **0.000000** | |
| Max entry-price difference across all 10 matched trades | 1.4×10⁻¹⁴ | |
| Max net-PnL difference across all 10 matched trades | 1.5×10⁻¹⁴ | |

That residual is floating-point noise (10⁻¹⁴ on prices around 100), not a real
discrepancy. Every entry timestamp, exit timestamp, entry price, exit price, and
net P&L matched exactly. This was re-run across 4 different random seeds
(`tests/integration/test_backtrader_comparison.py` parametrizes `[7, 1, 42, 123]`)
with the same result on every fully-completed trade.

## 3. What this found — and what it confirmed

### 3.1 Confirmed: execution timing matches Backtrader's own default

The prior correctness audit (`docs/VALIDATION_REPORT.md`) fixed this engine to
decide a trade from a bar's *close* but fill it at the *next* bar's *open* — because
filling at the same close used to generate the signal is a well-known source of
optimistic bias. This comparison independently confirms that's not just a defensible
choice but the **industry-standard default**: probing Backtrader directly (a
strategy that issues `self.buy()` inside `next()`) shows it fills at the following
bar's open by default too, and its own documentation calls same-bar-open execution
"cheating" (`Cerebro(cheat_on_open=True)` is an explicit, named opt-in for the
unrealistic behavior). Both engines landing on the same default from independent
design processes is a strong signal this wasn't an arbitrary call.

### 3.2 Fixed: slippage wasn't clamped to the bar's own trading range

**Found:** on one trade in the very first comparison run (before any fix), this
engine's entry price (98.71916...) and Backtrader's (98.70629...) disagreed by
about 1.3 cents — small, but real, not float noise. Backtrader's fill was *exactly*
equal to that bar's `high` (98.7062940604398). The cause: that bar's range was
tight enough that `open × (1 + 5bps)` came out *above* the bar's own high — i.e.,
this engine's slippage model was willing to fill at a price the market never
actually traded at that bar. Backtrader clamps a slippage-adjusted fill to the
bar's `[low, high]` by default (`slip_out=False`); this engine didn't clamp at all.

**Fix:** `BrokerSimulator.fill()` now clamps the slippage-adjusted price to the
relevant bar's `[low, high]` when that range is available
(`backtesting/broker_simulator.py`; wired through every fill call site in
`backtesting/engine.py`). After the fix, that same trade — and every other trade
across all 4 tested seeds — matches Backtrader exactly (§2).

### 3.3 Fixed (found *while investigating* this comparison, not by Backtrader directly): `final_equity` could be inconsistent with `closed_trades`

**Found:** while explaining a small residual difference in final equity for seeds
where the backtest ends with an open position (§3.4), it became clear the residual
didn't match what it should have been from fee/slippage math alone. Tracing it
down: this engine's `equity_curve` is appended to once per bar (`record_equity()`,
step 4 of `_on_candle`), but the end-of-backtest forced close
(`_force_close_at_end()`) runs *after* the last bar's processing completes — so it
never updated that last recorded point. The result: `BacktestResult.final_equity`
(`= equity_curve[-1][1]`) reported the *unrealized* mark-to-market value from just
before the forced close, while `closed_trades` correctly included the forced
close's fee- and slippage-adjusted numbers. The two were quietly inconsistent —
summing `closed_trades` net P&L plus initial capital would not have equaled
`final_equity` whenever a backtest ended mid-position.

**Fix:** `BacktestEngine._sync_last_equity_point_to_realized_cash()` corrects the
last equity-curve point to the post-close realized cash value immediately after
any forced close (end-of-backtest or ruin). `equity_curve` and `closed_trades` are
now guaranteed consistent. This was a real, if small (order of one trade's
fee+slippage on a single position, so cents to low dollars on a $100k account),
internal bug that this cross-validation exercise is what actually surfaced it —
not something Backtrader's numbers directly disagreed with, but something the
*process* of explaining a Backtrader discrepancy uncovered.

### 3.4 Explained, not a bug: force-close-at-end vs. leave-open-at-end

For seeds 1 and 42 (of the 4 tested), the data ends with one more golden cross than
death cross — i.e., a position is still open when the data runs out. The two
engines handle this differently **by design**, not by accident:

- **This engine** force-closes any still-open position at the end of a backtest
  run (`ExitReason.END_OF_BACKTEST`), through the same fee+slippage path as any
  other exit — giving every backtest a single, unambiguous, fully-realized final
  P&L, and ensuring `analytics.performance_metrics` (win rate, profit factor,
  R-multiple, ...) — all computed from `closed_trades` — never silently drops the
  final position's contribution.
- **The benchmark Backtrader strategy used in this comparison** does not force-close
  (a minimal choice, made to isolate crossover-trading mechanics for this specific
  comparison) — `cerebro.broker.getvalue()` marks the open position to market at
  the last bar's close with no exit fee or slippage charged, since nothing was
  actually sold.

Seed 1 example: my engine's final equity (100,021.47) is 0.20 lower than
Backtrader's (100,021.67) — consistent with one extra fee+slippage-bearing exit
that Backtrader's simpler benchmark never took. This is the expected, correctly
bounded direction and magnitude (asserted directly in
`test_matches_backtrader_on_every_completed_round_trip`, which checks
`-2.0 < diff <= 1e-6` for the has-a-dangling-position case), not an unexplained
residual. Both conventions (force-realize vs. mark-to-market-only) are used by real
backtesting tools; this engine's choice was deliberate before this comparison and
remains unchanged — see `docs/VALIDATION_REPORT.md` §3 for the original reasoning.

## 4. What this comparison does *not* cover

- **Short selling** — the benchmark strategy is long-only. This engine's short-side
  mechanics (fill direction, funding sign, stop/take-profit resolution) were
  already covered by this engine's own test suite
  (`tests/unit/backtesting/test_execution_timing.py` etc.) but not independently
  cross-validated against Backtrader here.
- **Stop-loss / take-profit / funding** — deliberately excluded from the benchmark
  strategy to keep the comparison isolated to crossover-trading + cost mechanics.
  Gap-through stop/take-profit pricing (this engine's own behavior, see
  `docs/VALIDATION_REPORT.md` §1.1) was not cross-checked against Backtrader's
  equivalent slippage/gap handling for stop orders specifically.
- **Position sizing / risk engine** — the benchmark uses a fixed unit size on both
  sides; `risk/position_sizing.py` and `risk/pre_trade_checks.py` are exercised by
  this engine's own unit tests, not by this comparison.
- **Real market data** — both engines ran on the same synthetic dataset (this
  sandbox has no outbound network access to Binance's API, per
  `docs/VALIDATION_REPORT.md`). The comparison validates mechanics, not real-data
  behavior specifically.

## 5. How to reproduce

```bash
pip install -e ".[dev,validation]"
pytest tests/integration/test_backtrader_comparison.py -v
```

The test is parametrized across 4 seeds and skips itself
(`pytest.importorskip("backtrader")`) if the optional `validation` dependency group
isn't installed — it never blocks the regular test suite.
