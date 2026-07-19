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
