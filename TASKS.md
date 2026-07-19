# TASKS.md — Implementation Milestones

This is the execution plan derived from `docs/ARCHITECTURE.md` (see its Revision 2
note for the reasoning behind this ordering). Every task is scoped to be completable
independently, reviewable in a single PR, and small enough to not require touching
more than one or two folders.

**Implementation order changed:** the platform is now built **research-first**.
Part A (Research & Backtesting Engine) is built and validated before Part B
(Execution Platform — live market data, exchange adapters, order placement, API,
dashboard). No capital, paper or live, is put at risk until strategies have been
validated in Part A. See `docs/ARCHITECTURE.md` Revision 2 for why.

Checkbox legend: `[ ]` not started · `[~]` in progress · `[x]` done.

**Pre-Part-B audit completed:** a full correctness/realism audit of everything
through Phase A14 found and fixed 8 real issues (4 critical — including a same-bar
signal/execution look-ahead-adjacent bug in the backtest engine — 1 high, 2 medium,
1 transparency gap), each with regression tests (test suite: 158 → 196 tests). See
[`docs/VALIDATION_REPORT.md`](docs/VALIDATION_REPORT.md) for the full findings,
fixes, what was verified, and what assumptions/limitations remain.

**Pre-first-strategy validation completed:** before implementing any production
strategy, the engine was cross-validated against Backtrader (an established
backtesting library — see [`docs/BACKTRADER_COMPARISON.md`](docs/BACKTRADER_COMPARISON.md),
every completed round-trip trade matches to float precision) and put through a
dedicated stress-test suite (missing data, duplicate/out-of-order timestamps,
flash crashes, extreme gaps, zero-volume bars, corrupted inputs — 19 tests, all
passing). Found and fixed 2 more real issues (slippage not clamped to a bar's
trading range; `final_equity` inconsistent with `closed_trades` after a forced
close) and added an OHLCV validation gate. Test suite: 196 → 241 tests. See
`docs/VALIDATION_REPORT.md` §5 for the summary.

---

# PART A — Research & Backtesting Engine (build first)

Deliverable: given historical Binance Futures data, be able to define a strategy,
backtest it with realistic costs, optimize its parameters, and review the results
(metrics + trade journal) — entirely offline, no exchange account, no live
connectivity, no dashboard.

## Phase A0 — Repository & Tooling Foundations

- [x] A0.1 Initialize `pyproject.toml` with Python 3.12 target, dependency groups (`main`, `dev`, `test`). Include `pandas`/`polars`, `pyarrow` (Parquet), `httpx` (REST downloads) in `main`.
- [x] A0.2 Configure Ruff (`pyproject.toml [tool.ruff]`) with project lint rules.
- [x] A0.3 Configure Black formatting settings.
- [x] A0.4 Configure Mypy (`strict` mode for `core/`, standard elsewhere).
- [x] A0.5 Configure Pytest (`pyproject.toml [tool.pytest.ini_options]`, `tests/` rootdir).
- [x] A0.6 Add `.pre-commit-config.yaml` wiring ruff/black/mypy as pre-commit hooks.
- [x] A0.7 Create `Makefile` with `make lint`, `make format`, `make test`, `make backtest`.
- [x] A0.8 Write `README.md` skeleton (project purpose, quickstart, links to `docs/ARCHITECTURE.md`).
- [x] A0.9 Create `.env.example` (DB connection for research-phase Postgres; no exchange API keys needed yet).
- [x] A0.10 Scaffold Part A package directories with `__init__.py` files.
- [x] A0.11 Add `.github/workflows/ci.yml` running lint + mypy on push/PR (tests added once they exist).
- [x] A0.12 Add `.gitignore` (Python, Docker, IDE, `.env`, local Parquet data directory).

## Phase A1 — Domain Kernel (`core/`)

- [x] A1.1 Define `core/enums.py` (`OrderSide`, `OrderType`, `TimeInForce`, `PositionSide`, `TrendState`, `VolatilityState`, `MarketBias`). Live-only enums (`OrderStatus` transitions specific to exchange lifecycle) deferred to Part B where not needed for simulated fills.
- [x] A1.2 Define `core/types.py` value objects (`Symbol`, `Money`/`Price` using `Decimal`).
- [x] A1.3 Define `core/exceptions.py` hierarchy, including `InsufficientDataError`, `InvalidBacktestConfigError`.
- [x] A1.4 Define `core/constants.py` (default timeframes, precision defaults).
- [x] A1.5 Define `core/events.py`: `CandleEvent`, `FundingRateEvent`, `SignalEvent` (incl. `confidence`, `reasoning`), `OrderIntentEvent`, `FillEvent`, `RiskRejectedEvent`, `MarketRegimeChangedEvent`.
- [x] A1.6 Implement `core/event_bus.py` in-process asyncio implementation (Redis-backed implementation deferred to Part B — research engine runs single-process).
- [x] A1.7 Define `core/interfaces/strategy.py` ABC (decomposed hooks — see A8).
- [x] A1.8 Define `core/interfaces/repository.py` generic ABC.
- [x] A1.9 Unit tests for event bus (pub/sub ordering, multiple subscribers).
- [x] A1.10 Add import-boundary lint check: `core` has zero first-party imports; `strategies` may import `core`/`features`/`market_regime` only.

## Phase A2 — Configuration & Logging

- [x] A2.1 Implement `config/settings.py` (`Pydantic BaseSettings`) — research-phase settings only (DB connection, local data directory path, Binance REST base URL).
- [x] A2.2 Implement `config/logging.py` structured JSON logging factory.
- [x] A2.3 Unit tests: settings validation fails fast on missing required vars.

## Phase A3 — Historical Data Layer

- [x] A3.1 Implement `market_data/historical/dataset.py` — `HistoricalDataset` ABC (`download(symbol, start, end)`, `store(df)`, `load(symbol, start, end) -> DataFrame`).
- [x] A3.2 Implement `market_data/historical/parquet_store.py` — local columnar store, partitioned by `exchange/symbol/timeframe`, append-safe, dedup on overlapping downloads.
- [x] A3.3 Implement `market_data/historical/binance_client.py` — REST client for Binance Futures klines endpoint (OHLCV), with pagination and rate-limit backoff.
- [x] A3.4 Implement `market_data/historical/candles_dataset.py` — `HistoricalDataset` implementation for OHLCV using A3.2/A3.3.
- [x] A3.5 Extend `binance_client.py` for the funding rate history endpoint.
- [x] A3.6 Implement `market_data/historical/funding_rate_dataset.py` — `HistoricalDataset` implementation for funding rates.
- [x] A3.7 Implement gap detection (`dataset.load` reports missing ranges instead of silently returning partial data).
- [x] A3.8 Unit tests: parquet_store round-trip, append/dedup behavior, gap detection — using recorded/synthetic fixtures (no live network dependency in tests).
- [x] A3.9 `scripts/download_historical_data.py` CLI: `--symbol --timeframe --start --end --dataset {candles,funding_rate}`.
- [x] A3.10 Document in `README.md` that `market_data/historical/dataset.py`'s ABC is the extension point for open interest / liquidations / CVD later — no other module changes needed to add them.

## Phase A4 — Database & Persistence (research subset)

> Not yet started: this sandbox has no running Postgres (Docker daemon isn't
> available here), so SQLAlchemy models/migrations/repositories would ship
> untested against a real database, which isn't acceptable for a persistence
> layer. Everything through Phase A14 runs and is fully tested without a DB —
> `backtest_runs`/`signals`/`journal_entries` currently exist as in-memory
> Python objects and local files (Parquet/CSV) rather than Postgres rows. Do this
> phase next, in an environment where `docker compose up postgres` actually works.

- [ ] A4.1 Implement `database/base.py` (`DeclarativeBase`, `TimestampMixin`, `UUIDPkMixin`).
- [ ] A4.2 Implement `database/session.py` async engine/session factory.
- [ ] A4.3 Initialize Alembic (`database/alembic/`, `alembic.ini`).
- [ ] A4.4 Model + migration: `exchanges`, `symbols` (seed: Binance Futures only).
- [ ] A4.5 Model + migration: `strategy_definitions`, `strategy_instances` (mode restricted to `backtest` in Part A).
- [ ] A4.6 Model + migration: `signals` (confidence, reasoning, regime_snapshot_id, features_snapshot).
- [ ] A4.7 Model + migration: `market_regime_snapshots`.
- [ ] A4.8 Model + migration: `backtest_runs`, `backtest_trades`, `equity_curve_points`.
- [ ] A4.9 Model + migration: `optimization_runs`.
- [ ] A4.10 Model + migration: `journal_entries`.
- [ ] A4.11 Model + migration: `risk_limits`.
- [ ] A4.12 Implement `repositories/base.py` generic async CRUD repository.
- [ ] A4.13 Implement `strategy_repository.py`, `signal_repository.py`, `regime_repository.py`, `backtest_repository.py`, `journal_repository.py`.
- [ ] A4.14 Integration tests for every repository against a real test-Postgres container.
- [ ] A4.15 `docker-compose.yml`: `postgres` (Timescale image) service only for Part A — no Redis dependency yet (feature cache is in-memory, see A6).

## Phase A5 — Schemas (research subset)

- [ ] A5.1 `schemas/common.py` (pagination envelope, error envelope).
- [ ] A5.2 `schemas/strategy.py`, `schemas/signal.py`, `schemas/regime.py`, `schemas/journal.py`, `schemas/backtest.py`.
- [ ] A5.3 Unit tests: schema validation edge cases (confidence out of [0,100], negative sizes, etc.).

## Phase A6 — Feature Engine

- [x] A6.1 Implement `features/cache.py` — `FeatureCache` ABC + `InMemoryFeatureCache` (default). Redis implementation deferred to Part B.
- [x] A6.2 Implement `features/indicators/trend.py` (EMA, ADX, MACD, Donchian).
- [x] A6.3 Implement `features/indicators/volatility.py` (ATR, Bollinger Bands).
- [x] A6.4 Implement `features/indicators/momentum.py` (RSI).
- [x] A6.5 Implement `features/indicators/volume.py` (VWAP, Volume Profile).
- [x] A6.6 Implement `features/indicators/derivatives.py` (Funding Rate feature, from A3.6's dataset; Open Interest stubbed for when that dataset exists).
- [x] A6.7 Implement `features/feature_engine.py` unified `get(symbol, timeframe, indicator, **params)` entrypoint with warmup from the Parquet store.
- [x] A6.8 Unit tests: every indicator against known reference values.
- [x] A6.9 Unit test: cache hit avoids recomputation.

## Phase A7 — Market Regime

- [x] A7.1 Implement `market_regime/market_state.py` (`MarketState` value object).
- [x] A7.2 Implement `market_regime/trend_detector.py` (ADX-threshold trending classification).
- [x] A7.3 Implement `market_regime/range_detector.py` (Donchian-width/compression classification).
- [x] A7.4 Implement `market_regime/volatility_detector.py` (ATR-percentile classification).
- [x] A7.5 Implement bias classification (MA slope/ordering) inside `market_state.py`.
- [x] A7.6 Unit tests: regime classification against hand-labeled historical fixture periods.

## Phase A8 — Strategy Framework

- [x] A8.1 Implement `strategies/base_strategy.py` — decomposed template-method ABC: `detect_setup(context) -> Setup | None`, `check_entry(context, setup) -> bool`, `check_exit(context, position) -> bool`, `stop_loss(context, position) -> Price`, `take_profit(context, position) -> Price`, `position_size(context, setup) -> Quantity`.
- [x] A8.2 Implement `strategies/signal.py` value object (incl. `confidence`, `reasoning`, `stop_loss`, `take_profit`, `size`).
- [x] A8.3 Implement `strategies/registry.py` (decorator-based discovery).
- [x] A8.4 Implement `StrategyContext` with `context.features.get(...)` and `context.regime.current(symbol)` accessors, backed by A6/A7.
- [x] A8.5 Implement example strategy `strategies/examples/ma_crossover.py` implementing all six hooks.
- [x] A8.6 Implement example strategy `strategies/examples/mean_reversion.py`.
- [x] A8.7 Unit tests: each hook independently on both example strategies against fixture data; verify strategies are interchangeable (same harness runs either).

## Phase A9 — Portfolio Management (backtest-scoped)

- [x] A9.1 Implement `portfolio/position_tracker.py` (in-memory during a backtest run; long and short).
- [x] A9.2 Implement `portfolio/pnl_calculator.py` (realized/unrealized PnL, funding cost accrual, fee deduction).
- [x] A9.3 Implement `portfolio/portfolio_manager.py` (equity curve accumulation across the run).
- [x] A9.4 Unit tests: PnL correctness across partial fills, long and short, fee/funding handling.

## Phase A10 — Risk Engine (sizing/limits, no live circuit breaker)

- [x] A10.1 Implement `risk/position_sizing.py` fixed-fractional model.
- [x] A10.2 Implement `risk/position_sizing.py` volatility-target model.
- [x] A10.3 Implement `risk/position_sizing.py` confidence-scaled model.
- [x] A10.4 Implement `risk/limits.py` (exposure/leverage/concentration checks reading `risk_limits`).
- [x] A10.5 Implement `risk/pre_trade_checks.py` pipeline.
- [x] A10.6 Implement `risk/risk_engine.py` orchestrator (drawdown/circuit-breaker logic stubbed as a config-driven backtest-abort condition only — full live circuit breaker is Part B).
- [x] A10.7 Unit tests: every check independently, plus a deliberately-breaching signal.

## Phase A11 — Backtesting Engine

- [x] A11.1 Implement `backtesting/data_feed.py` — reads from the Parquet store (A3), time-ordered, merges candles + funding rate events.
- [x] A11.2 Implement `backtesting/event_simulator.py` (deterministic replay loop, look-ahead prevention across `features`/`market_regime` lookbacks).
- [x] A11.3 Implement `backtesting/slippage_models.py` (fixed-bps, next-bar-open, volume-participation — all configurable).
- [x] A11.4 Implement `backtesting/broker_simulator.py` — simulates fills for long/short, applies trading fees, funding costs, and slippage.
- [x] A11.5 Implement `backtesting/engine.py` orchestrating simulator + features + market_regime + strategies + risk + portfolio.
- [x] A11.6 Persist results to `backtest_runs`/`backtest_trades`/`equity_curve_points`, and `signals` for every run.
- [x] A11.7 Golden-dataset regression test fixture + CI check.
- [x] A11.8 `scripts/run_backtest.py` CLI: `--strategy --symbol --timeframe --start --end --config`.
- [x] A11.9 Integration test: full backtest run on fixture data for both example strategies, long and short, verify fees/funding/slippage all reduce net PnL as expected.
- [x] A11.10 Cross-validate engine execution/accounting against an established backtesting library (Backtrader) under identical data/fees/slippage — see `docs/BACKTRADER_COMPARISON.md`.
- [x] A11.11 Stress-test suite: missing data, duplicate/out-of-order timestamps, flash crashes, extreme gaps, zero-volume bars, corrupted inputs — engine fails safely rather than producing misleading results — see `tests/unit/backtesting/test_stress.py`.
- [x] A11.12 OHLCV validation gate (`market_data/historical/validation.py`) wired into `DataFeed.from_candles`.

## Phase A12 — Analytics

- [x] A12.1 Implement `analytics/performance_metrics.py`: Net Return, CAGR, Sharpe Ratio, Sortino Ratio.
- [x] A12.2 Extend with Profit Factor, Win Rate, Average R Multiple.
- [x] A12.3 Extend with Max Drawdown, Consecutive Wins/Losses.
- [x] A12.4 Extend with Monthly Returns breakdown, Trade Distribution (by outcome, duration, symbol).
- [x] A12.5 Implement `analytics/attribution.py` (per-strategy, per-regime, per-confidence-bucket).
- [x] A12.6 Implement `analytics/tearsheet.py` (structured report combining A12.1–A12.5).
- [x] A12.7 Unit tests: every metric against known reference values (hand-computed or a reference implementation).

## Phase A13 — Trade Journal

- [x] A13.1 Implement `journal/journal_recorder.py`: subscribes to `SignalEvent`/`FillEvent` on the in-process bus during a backtest run.
- [x] A13.2 Implement open-entry logic: first fill establishing a position → `journal_entries` row with entry reason, market conditions (regime snapshot), strategy metadata, confidence score, all calculated features at signal time.
- [x] A13.3 Implement close-entry logic: flattening fill → finalize exit reason, PnL, fees, funding, holding time.
- [x] A13.4 Add `screenshot_url` as a nullable placeholder field (no chart-rendering dependency in Part A).
- [x] A13.5 Implement `journal/exporters/csv_exporter.py`.
- [x] A13.6 Implement `journal/exporters/pdf_exporter.py`.
- [x] A13.7 Unit tests: open/close lifecycle against synthetic fill sequences (partial fills, scale-ins, long and short).

## Phase A14 — Optimization (Grid Search + Walk-Forward only)

- [x] A14.1 Implement `optimization/objective_functions.py` (Sharpe, Calmar, custom).
- [x] A14.2 Implement `optimization/param_search.py` — `SearchStrategy` protocol + grid search implementation. **Do not implement Bayesian search.**
- [x] A14.3 Implement `optimization/param_search.py` random search (second implementation of the same protocol).
- [x] A14.4 Implement `optimization/overfitting_guards.py` (deflated Sharpe, min sample size gate).
- [x] A14.5 Implement `optimization/walk_forward.py` rolling train/test orchestrator.
- [x] A14.6 Persist `optimization_runs` linked to child `backtest_runs`.
- [x] A14.7 Integration test: full walk-forward run on fixture dataset, verify in/out-of-sample split correctness and that overfit parameter sets are flagged.

## Phase A15 — Research Engine Validation (exit gate for Part A)

> A15.2–A15.4 have been run against **synthetic** OHLCV/funding data seeded directly
> into the Parquet store (the sandbox this was built in has no outbound access to
> Binance's API — confirmed, not assumed). The full pipeline — download-shaped data →
> `ma_crossover`/`mean_reversion` backtest → analytics summary → CSV journal export —
> works end-to-end via the real `scripts/run_backtest.py` CLI. A15.1 and the final
> sign-off (A15.5) still need a real multi-year Binance download, which requires
> running this in an environment with outbound network access.

- [ ] A15.1 Download real Binance Futures historical data (candles + funding rate) for at least one symbol across a multi-year window.
- [x] A15.2 Run both example strategies through the full pipeline (backtest → walk-forward → journal → analytics) on synthetic data shaped like real downloads (see note above).
- [x] A15.3 Manual review: do the metrics, journal entries, and equity curve look correct and explainable end-to-end? (Reviewed on synthetic data; re-review recommended once run on real history.)
- [x] A15.4 Full regression pass: unit + integration + backtest golden-dataset tests green (158/158 passing; DB-dependent tests from Phase A4 not yet written — see note there).
- [ ] A15.5 Decision point — only after this phase passes does work begin on Part B (Execution Platform). Document the decision in `docs/adr/`.

## Phase A16 — First Production Strategy: Liquidity Exhaustion Reversal System

> Still Part A (research), not Part B — a strategy is research output, not execution
> infrastructure. See `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md` for the full
> research review (critiquing every "Smart Money Concepts" rule against market
> microstructure before accepting it), mathematical definitions, architecture,
> parameter table, and assumptions/limitations/future-experiments sections.

- [x] A16.1 Phase 1/2 research review + mathematical definitions doc, written *before* any code, per explicit instruction. Notably: collapses the ambiguous "CHoCH/BOS/structure shift" trio into one precise swing-based state machine; redefines "equal highs/lows" as ATR-normalized, minimum-touch liquidity-pool clusters instead of raw price equality; ties the stop-loss directly to the hypothesis's own falsification boundary (the swept extreme) rather than a generic ATR multiple; and explicitly scopes out Open Interest/Liquidations/real order-flow delta as unavailable (no dataset exists) rather than fabricating them.
- [x] A16.2 `strategies/liquidity_exhaustion_reversal/{structure,microstructure,config}.py` — pure, independently unit-tested primitives (swing points, liquidity pools, sweep-and-reclaim, BoS/ChoCH, displacement, absorption proxy, delta proxy + divergence, Fair Value Gap, Order Block) and a fully configurable parameter dataclass.
- [x] A16.3 `strategies/liquidity_exhaustion_reversal/indicators.py` registers all of the above into `FeatureEngine` via a new `register_indicator()` extension point (`features/feature_engine.py`) — same causal/cached/warmup-safe semantics as every built-in indicator, no parallel data-access path.
- [x] A16.4 `strategies/examples/liquidity_exhaustion_reversal.py` implements the full `Strategy` ABC; baseline setup (pool + sweep-and-reclaim + displacement) works with every optional filter (absorption, delta divergence, Fair Value Gap, Order Block, Open Interest flush) disabled, each independently toggleable via config for A/B testing.
- [x] A16.5 Trade explainability (Phase 5) + research instrumentation (Phase 6): every signal's `reasoning` carries the full explainability text, and `Setup.metadata` carries ~40 features covering the requested instrumentation list. Required two small, generally-applicable (not LES-specific) engine fixes: `StrategyContext.funding_rate` (funding was loaded but never exposed to strategies) and merging `Setup.metadata` into `SignalEvent.features_snapshot` (the field existed but nothing downstream ever read it, for any strategy). Also added `volume_profile_value_area()` (VAH/VAL) and `volume_percentile()` to the shared `features/indicators/volume.py`.
- [x] A16.6 Tests: primitive unit tests, strategy-hook unit tests (including an A/B containment test proving optional filters can only narrow, never expand, the baseline), and integration tests (full backtest sanity, Phase 6 instrumentation coverage on real emitted signals, a complete example-trade walkthrough, and edge cases — no-pool-ever-forms, sweep-with-no-reclaim, backtest shorter than warmup). Full pre-existing 241-test suite still green, confirming this is a pure addition.
- [x] A16.7 Research report finalized in `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md` (architecture overview, flow, full parameter table, assumptions/biases, suggested future experiments, parameters intentionally left unoptimized).

## Phase A17 — Long-Horizon Research Pipeline (Binance API unreachable — synthetic data)

> Requested: download the maximum available Binance USDⓈ-M Futures history for
> BTCUSDT/ETHUSDT across every timeframe and run a full long-horizon validation
> (data quality, regime analysis, walk-forward, Monte Carlo, parameter robustness).
> `fapi.binance.com` is blocked by this sandbox's network policy — confirmed directly
> (`gateway answered 403 to CONNECT (policy denial)`, not a transient failure), logged
> in `docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md` §0. Rather
> than stall or silently fabricate a "real" result, the entire analysis *pipeline* was
> built and validated end-to-end against synthetic, regime-structured data instead —
> every module states the synthetic/real boundary explicitly, and the real downloader
> (`market_data/historical/binance_client.py`) needs zero changes to produce a real
> report the moment network access exists.

- [x] A17.1 `research/synthetic_history.py` — deterministic, regime-conditioned (bull/bear/range x high/low-vol, funding-correlated) OHLCV + funding generator spanning each symbol's assumed listing date to now, across all 5 supported timeframes.
- [x] A17.2 `research/data_quality.py` — missing/duplicate/gap/invalid-OHLC/volume-anomaly/funding-range checks; auto-repairs only structural defects (sort, dedupe), flags (never fabricates) anything else, including Open Interest being explicitly unavailable.
- [x] A17.3 `research/backtest_runner.py` + `trade_records.py` — runs the strategy's own unmodified production config through the real `BacktestEngine`, joining `ClosedTrade`/`JournalEntry` into one analysis-ready record.
- [x] A17.4 `research/regime_analysis.py` — ground-truth (synthetic-only) and strategy-observed (works on real data too) performance segmentation by trend/volatility/bias/funding-sign/ADX/session.
- [x] A17.5 `research/rolling_validation.py` — rolling out-of-sample validation with a fixed config (explicitly *not* `optimization/walk_forward.py`'s optimizer) and no look-ahead.
- [x] A17.6 `research/monte_carlo.py` — bootstrap resampling of realized trade P&L for drawdown/ruin/return distributions, with stated serial-correlation and non-compounding simplifications.
- [x] A17.7 `research/robustness.py` — ±10% single-parameter perturbation sweep (not optimization) to surface fragility, plus a structural FVG/Order Block on-off comparison.
- [x] A17.8 `scripts/run_research_pipeline.py` orchestrates all phases into `docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md`, including an honest Phase 9 scientific conclusion that states plainly this run does not validate a real market edge.
- [x] A17.9 Two small, generally-applicable fixes surfaced by actually using the pipeline: `analytics/performance_metrics.py` gained `ulcer_index`/`mar_ratio`/`expectancy`/`yearly_returns`/`rolling_sharpe`/`rolling_drawdown`/`rolling_expectancy`; `backtesting/engine.py`'s `StrategyContext.funding_rate` was wired to the sparse funding-accrual-timing series instead of the forward-filled "currently in effect" rate, making per-trade funding instrumentation `NaN` on ~7/8 of trades — now fixed for every strategy, not just this one.
- [x] A17.10 Tests: `tests/unit/research/` covers the synthetic generator, data-quality repair/flag logic (including injected duplicate/gap/invalid-OHLC/out-of-range fixtures), and every pipeline module. Full suite green (312/312) with zero regressions.

---

## Phase A18 — Complete Data Layer + Real-Data-Ready Pipeline (prep for the definitive study)

> Requested: stop building features/strategies/optimizing parameters and instead
> prepare the platform so that the moment real Binance data becomes available it can
> run the definitive scientific validation with zero further code changes. Six parts:
> complete the Binance data layer, maximum historical coverage with no hardcoded date
> ranges, production-grade incremental sync, an automatic one-command scientific
> validation pipeline, an expanded publication-quality report, and continued
> institutional code-quality standards (tests, docs, types, lint, never fabricate/
> optimize/leak). `fapi.binance.com` remains network-blocked in this sandbox
> (confirmed directly, not assumed) — everything below is implemented against
> Binance's published API docs and tested against a mocked client, ready for live
> verification the moment access exists; see `docs/DATA_LAYER.md`.

- [x] A18.1 Extended `market_data/historical/binance_client.py`: `ping()` (fast-fail connectivity check), `find_earliest_*` empirical-probe methods, mark price / premium index / open interest / exchange info endpoints — all endpoint coverage the strategy needs, each documented with its real history depth.
- [x] A18.2 New dataset classes: `MarkPriceDataset`, `PremiumIndexDataset`, `OpenInterestDataset` (Binance's real ~30-day retention cap clamped and documented, not fabricated or silently ignored), and `exchange_info.get_symbol_info()` (typed `onboardDate` cross-check).
- [x] A18.3 "Never hardcode a date range": `HistoricalDataset.find_earliest_available()` / `sync_full_history()` — a single `limit=1` probe from a safe pre-launch floor finds each symbol/dataset's true earliest available point; implemented for candles, funding, mark price, and premium index (Open Interest correctly uses a fixed retention floor instead — a probe would be dishonest given the real cap).
- [x] A18.4 `scripts/sync_historical_data.py` — production incremental sync CLI: never redownloads existing data (`ensure_range()`'s existing gap-only logic), resumable, deduplicated on write (`ParquetStore.write()`), reports data-quality per dataset, cross-checks `exchangeInfo.onboardDate` against the empirical probe. Verified end-to-end against a fully-mocked `client._get()` (real pagination, not bypassed): a fresh sync followed by a resync makes strictly fewer requests and produces no duplicate timestamps.
- [x] A18.5 `research/data_quality.py` gained `repair_and_check_open_interest()` (shared `_repair_and_check_series()` helper, factored out of the existing funding-rate check).
- [x] A18.6 `research/data_loader.py` — single real/synthetic resolution point: `mode="auto"` (real-first, synthetic fallback, default), `mode="real"` (fail loudly, no silent fallback), `mode="synthetic"` (continued methodology testing). `scripts/run_research_pipeline.py --data-source {auto,real,synthetic}` passes this straight through — nothing in the pipeline script needs to change the day real access exists.
- [x] A18.7 `research/conclusion.py` — the pre-registered (fixed-before-evaluation), four-check objective decision rule behind the mandated unsoftened binary conclusion sentence. Gated strictly on `all_data_is_real`: the real sentence is only ever emitted when every symbol's data came from `source="real"`; on synthetic data the report states "INSUFFICIENT EVIDENCE" and shows the mechanical verdict only as a clearly-labeled, non-binding proof that the rule executes correctly end-to-end.
- [x] A18.8 Report expansion (`scripts/_research_report_body.py`): sample-size table with per-row data source, R-multiple distribution histogram, failure-mode breakdown (max consecutive losses, large-loss rate, exit reasons), per-symbol ground-truth-regime gating (omitted for real data, since there is no ground truth to compare against), §0/§9 provenance and conclusion language branching on `all_data_is_real`.
- [x] A18.9 `docs/DATA_LAYER.md` — the map of endpoint coverage, the Open Interest retention limitation, the never-hardcode-a-date-range mechanism, incremental sync guarantees, and how the pipeline picks a data source.
- [x] A18.10 Tests: `tests/unit/market_data/test_binance_client.py` (ping, pagination, earliest-detection — mocked only at `_get`, exercising real pagination logic), `test_new_datasets.py` (mark price/premium index/open interest/exchange info), `tests/integration/test_sync_historical_data.py` (full sync + resync against a low-level-mocked backend, verifying resumability and no duplicate timestamps), `tests/unit/research/test_conclusion.py` (all four checks, per-symbol failure, real-vs-synthetic gating), `tests/unit/research/test_data_loader.py` (auto/real/synthetic branching, no network touched in synthetic mode). Full suite green (362/362) with zero regressions; `ruff`/`black`/`mypy` clean on every file touched this phase (one pre-existing, out-of-scope `mypy` error in `scripts/download_historical_data.py`, unrelated to this phase, left as found).
- [x] A18.11 Re-ran `python -m scripts.run_research_pipeline --data-source auto` end-to-end against the new code paths: confirmed the rewritten pipeline (data-source-pluggable loading, expanded report body, pre-registered decision rule) produces a complete report, correctly falling back to synthetic data with the real-fetch failure reason logged (`fapi.binance.com unreachable (ping failed)`) at every symbol/timeframe, exactly as designed for this still-network-blocked sandbox. §9's decision rule correctly evaluated all four checks and withheld the mandated binary sentence in favor of "INSUFFICIENT EVIDENCE" since the data was synthetic.

---

# PART B — Execution Platform (build second, after Part A is validated)

Not started until Phase A15 passes. Scope unchanged from the previous plan, retained
here for continuity — Binance-only per V1 scope (§ architecture doc), execution
tables (`accounts`, `balances`, `orders`, `trades`, `positions`) added at this point.

## Phase B1 — Live Market Data (Binance Futures WS)
- [ ] B1.1 `market_data/providers/binance_futures.py` WS subscription wrapper (CCXT Pro).
- [ ] B1.2 `market_data/ws_manager.py` connection lifecycle + reconnect/backoff.
- [ ] B1.3 `market_data/feed_normalizer.py`, `orderbook_builder.py`, `candle_aggregator.py` — live variants (reuse A3/A6 data models).
- [ ] B1.4 Redis-backed `EventBus` implementation activated (multi-process fan-out).
- [ ] B1.5 Redis-backed `FeatureCache` implementation activated.
- [ ] B1.6 `services/market_data_service.py` + worker container.

## Phase B2 — Database & Persistence (execution subset)
- [ ] B2.1 Model + migration: `accounts`, `balances` (encrypted API key fields).
- [ ] B2.2 Model + migration: `orders`, `trades`, `positions`.
- [ ] B2.3 Model + migration: `audit_log`, `alerts`.
- [ ] B2.4 Repositories for the above.

## Phase B3 — Exchange Execution Adapters (Binance + Paper)
- [ ] B3.1 `execution/adapters/base_adapter.py`, `paper_adapter.py`.
- [ ] B3.2 `execution/order_manager.py`, `execution_router.py`.
- [ ] B3.3 `execution/adapters/binance_adapter.py` (CCXT REST, testnet first).
- [ ] B3.4 `execution/reconciliation.py`.
- [ ] B3.5 `utils/rate_limiter.py`, `utils/retry.py`.
- [ ] B3.6 `services/order_service.py` + worker container.

## Phase B4 — Strategy Voting Engine (optional pattern, if still desired post-research)
- [ ] B4.1–B4.11 As previously scoped: `strategy_voting/` + `strategies/composite_strategy.py`. Revisit whether this is still worth building based on what Part A research shows about single-signal strategy performance — do not build speculatively.

## Phase B5 — Notifications
- [ ] B5.1–B5.7 Telegram/Discord notifiers, wired to live/paper events.

## Phase B6 — FastAPI Application
- [ ] B6.1–B6.18 As previously scoped, including `signals`/`regime`/`journal` read routers now backed by live data too.

## Phase B7 — Dashboard (Streamlit)
- [ ] B7.1–B7.9 As previously scoped.

## Phase B8 — Paper Trading End-to-End
- [ ] B8.1–B8.5 As previously scoped.

## Phase B9 — Live Execution Readiness
- [ ] B9.1–B9.6 As previously scoped, including full `risk/circuit_breaker.py` live implementation.

## Phase B10 — CI/CD & Deployment Hardening
- [ ] B10.1–B10.8 As previously scoped.

## Phase B11 — V1 Wrap-Up
- [ ] B11.1–B11.3 As previously scoped. Tag `v1.0.0`.

---

# PART C — Post-V1 Roadmap (unchanged)

- [ ] C1 Bybit adapter + provider (per architecture §9 checklist).
- [ ] C2 Third exchange (OKX or Deribit).
- [ ] C3 Bayesian search (`optimization/param_search.py` third `SearchStrategy` implementation).
- [ ] C4 `market_regime/sentiment_filter.py` + external news/social data ingestion.
- [ ] C5 Statistical/ML regime-switching model (e.g. HMM).
- [ ] C6 `ai_research/` — LLM client, strategy generator, research agent loop.
- [ ] C7 Multi-account / multi-tenant support.
- [ ] C8 Low-latency execution path.
- [ ] C9 FIX protocol adapter.
- [ ] C10 Kafka migration if Redis Streams throughput becomes limiting.
- [ ] C11 Compliance/audit reporting exports.
- [ ] C12 Kubernetes deployment manifests.
- [ ] C13 Mobile companion app.
- [ ] C14 Options/derivatives strategy support.

---

### How to use this file

- Work top-to-bottom within Part A; Phases A0–A2 are hard prerequisites. A3
  (Historical Data) and A6–A8 (Feature Engine, Market Regime, Strategy Framework)
  can proceed in parallel once A0–A2 are done. A9–A14 depend on A6–A8.
- **Do not start Part B until Phase A15 passes.** This is the hard gate the whole
  reordering exists to enforce.
- Each checked-off task should correspond to one PR with its own tests.
- Part B/C task numbering is coarser than Part A intentionally — it will be
  broken back down to the original per-file granularity when Part A validation
  passes and Part B actually starts, since requirements may shift based on what
  research reveals.
