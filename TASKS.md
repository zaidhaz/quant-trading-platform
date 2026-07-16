# TASKS.md — Implementation Milestones

This is the execution plan derived from `docs/ARCHITECTURE.md`. Every task is scoped
to be completable independently, reviewable in a single PR, and small enough to not
require touching more than one or two folders. Phases are ordered by dependency —
later phases assume earlier ones are done, but tasks *within* a phase can generally
be parallelized across contributors.

**Version 1 scope**: Binance Futures only · Paper + Live Trading · Backtesting
(Grid Search + Walk-Forward only) · Dashboard · Risk Engine · Strategy Engine
(incl. Feature Engine, Market Regime, optional Strategy Voting) · Portfolio
Management · Trade Journal · Confidence Scoring. Everything else (Bybit/other
exchanges, AI research, Bayesian optimization, sentiment data) is Phase 24+
(Post-V1 Roadmap).

Checkbox legend: `[ ]` not started · `[~]` in progress · `[x]` done.

---

## Phase 0 — Repository & Tooling Foundations

- [ ] 0.1 Initialize `pyproject.toml` with Python 3.12 target, dependency groups (`main`, `dev`, `test`).
- [ ] 0.2 Configure Ruff (`pyproject.toml [tool.ruff]`) with project lint rules.
- [ ] 0.3 Configure Black formatting settings.
- [ ] 0.4 Configure Mypy (`strict` mode for `core/`, standard elsewhere).
- [ ] 0.5 Configure Pytest (`pyproject.toml [tool.pytest.ini_options]`, `tests/` rootdir).
- [ ] 0.6 Add `.pre-commit-config.yaml` wiring ruff/black/mypy as pre-commit hooks.
- [ ] 0.7 Create `Makefile` with `make lint`, `make format`, `make test`, `make up`, `make down`.
- [ ] 0.8 Write `README.md` skeleton (project purpose, quickstart, links to `docs/ARCHITECTURE.md`).
- [ ] 0.9 Create `.env.example` with all required environment variables documented.
- [ ] 0.10 Scaffold empty package directories from the folder structure with `__init__.py` files.
- [ ] 0.11 Add `.github/workflows/ci.yml` running lint + mypy on push/PR (tests added once they exist).
- [ ] 0.12 Add `.gitignore` (Python, Docker, IDE, `.env`).

## Phase 1 — Domain Kernel (`core/`)

- [ ] 1.1 Define `core/enums.py` (`OrderSide`, `OrderType`, `TimeInForce`, `OrderStatus`, `StrategyMode`, `PositionSide`, `TrendState`, `VolatilityState`, `MarketBias`).
- [ ] 1.2 Define `core/types.py` value objects (`Symbol`, `Money`/`Price` using `Decimal`).
- [ ] 1.3 Define `core/exceptions.py` full hierarchy, including `InsufficientDataError`.
- [ ] 1.4 Define `core/constants.py` (default timeframes, precision defaults).
- [ ] 1.5 Define `core/events.py` event dataclasses: `MarketDataEvent` family, `SignalEvent` (incl. `confidence`, `reasoning` fields), `OrderIntentEvent`, `OrderUpdateEvent`, `FillEvent`, `RiskRejectedEvent`, `MarketRegimeChangedEvent`, `AlertEvent`.
- [ ] 1.6 Implement `core/event_bus.py` in-process asyncio implementation + abstract `EventBus` interface.
- [ ] 1.7 Implement Redis-backed `EventBus` implementation (behind the same interface).
- [ ] 1.8 Define `core/interfaces/exchange_gateway.py` ABC.
- [ ] 1.9 Define `core/interfaces/strategy.py` ABC.
- [ ] 1.10 Define `core/interfaces/repository.py` generic ABC.
- [ ] 1.11 Define `core/interfaces/notifier.py` ABC.
- [ ] 1.12 Unit tests for event bus (pub/sub ordering, multiple subscribers) — both backends.
- [ ] 1.13 Add import-boundary lint check: `core` has zero first-party imports; `strategies` may import `core`/`features`/`market_regime`/`strategy_voting` only (not `execution`/`database`/`api`).

## Phase 2 — Configuration & Logging

- [ ] 2.1 Implement `config/settings.py` (`Pydantic BaseSettings`, env-driven, per-environment).
- [ ] 2.2 Implement `config/logging.py` structured JSON logging factory + secret redaction filter.
- [ ] 2.3 Write `config/environments/development.env.example`, `staging.env.example`, `production.env.example`.
- [ ] 2.4 Unit tests: settings validation fails fast on missing required vars.

## Phase 3 — Database & Persistence Layer

- [ ] 3.1 Implement `database/base.py` (`DeclarativeBase`, `TimestampMixin`, `UUIDPkMixin`).
- [ ] 3.2 Implement `database/session.py` async engine/session factory.
- [ ] 3.3 Initialize Alembic (`database/alembic/`, `alembic.ini`).
- [ ] 3.4 Model + migration: `exchanges`, `symbols` (seed data: Binance Futures only).
- [ ] 3.5 Model + migration: `accounts`, `balances` (with encrypted API key fields).
- [ ] 3.6 Model + migration: `candles` (Timescale hypertable if extension available), `orderbook_snapshots`.
- [ ] 3.7 Model + migration: `strategy_definitions`, `strategy_instances`.
- [ ] 3.8 Model + migration: `orders`, `trades`, `positions`.
- [ ] 3.9 Model + migration: `signals` (confidence, reasoning, regime_snapshot_id, features_snapshot).
- [ ] 3.10 Model + migration: `market_regime_snapshots` (hypertable).
- [ ] 3.11 Model + migration: `journal_entries`.
- [ ] 3.12 Model + migration: `backtest_runs`, `backtest_trades`, `equity_curve_points`.
- [ ] 3.13 Model + migration: `optimization_runs`.
- [ ] 3.14 Model + migration: `risk_limits`, `audit_log`, `alerts`.
- [ ] 3.15 Implement `repositories/base.py` generic async CRUD repository.
- [ ] 3.16 Implement `market_repository.py`, `order_repository.py`, `trade_repository.py`, `position_repository.py`, `strategy_repository.py`, `backtest_repository.py`.
- [ ] 3.17 Implement `signal_repository.py`, `regime_repository.py`, `journal_repository.py`.
- [ ] 3.18 Integration tests for every repository against a real test-Postgres container.
- [ ] 3.19 `scripts/seed_db.py` for local dev seed data (Binance Futures exchange/symbols).
- [ ] 3.20 Add `docker-compose.yml` service for `postgres` (Timescale image) + `redis`, with healthchecks.

## Phase 4 — Schemas (Pydantic DTOs)

- [ ] 4.1 `schemas/common.py` (pagination envelope, error envelope).
- [ ] 4.2 `schemas/market.py` (Symbol, Candle DTOs).
- [ ] 4.3 `schemas/order.py`, `schemas/position.py`.
- [ ] 4.4 `schemas/strategy.py` (instance create/update/response DTOs).
- [ ] 4.5 `schemas/signal.py` (signal history DTO incl. confidence/reasoning).
- [ ] 4.6 `schemas/regime.py` (current/historical market regime DTO).
- [ ] 4.7 `schemas/journal.py` (journal entry DTO).
- [ ] 4.8 `schemas/backtest.py` (run request/response, tearsheet DTO).
- [ ] 4.9 Unit tests: schema validation edge cases (bad enums, negative sizes, confidence out of [0,100], etc.).

## Phase 5 — Market Data Subsystem (Binance Futures only)

- [ ] 5.1 Implement `market_data/providers/binance_futures.py` WS subscription wrapper (CCXT Pro).
- [ ] 5.2 Implement `market_data/ws_manager.py` connection lifecycle + reconnect/backoff logic.
- [ ] 5.3 Implement `market_data/feed_normalizer.py` (raw payload → `core.events` MarketDataEvent family).
- [ ] 5.4 Implement `market_data/orderbook_builder.py` (L2 diff application, checksum validation).
- [ ] 5.5 Implement `market_data/candle_aggregator.py` (trade stream → OHLCV bars, multiple timeframes).
- [ ] 5.6 Implement `market_data/historical_loader.py` REST backfill with gap detection against `candles`.
- [ ] 5.7 Wire market data pipeline to publish onto `core.event_bus`.
- [ ] 5.8 Unit tests: normalizer, orderbook_builder (using recorded fixture payloads).
- [ ] 5.9 Integration test: live testnet WS connection smoke test (nightly/manual only).
- [ ] 5.10 `services/market_data_service.py` orchestration entrypoint + worker container (`docker/Dockerfile.worker` target).

## Phase 6 — Feature Engine

- [ ] 6.1 Implement `features/cache.py` (Redis-backed cache keyed by symbol/timeframe/indicator/params, incremental update).
- [ ] 6.2 Implement `features/indicators/trend.py` (EMA, ADX, MACD, Donchian).
- [ ] 6.3 Implement `features/indicators/volatility.py` (ATR, Bollinger Bands).
- [ ] 6.4 Implement `features/indicators/momentum.py` (RSI).
- [ ] 6.5 Implement `features/indicators/volume.py` (VWAP, Volume Profile).
- [ ] 6.6 Implement `features/indicators/derivatives.py` (Funding Rate, Open Interest — Binance-specific field mapping).
- [ ] 6.7 Implement `features/feature_engine.py` unified `get(symbol, timeframe, indicator, **params)` entrypoint with cold-start warmup from `market_repository`.
- [ ] 6.8 Wire `feature_engine` to subscribe to `CandleEvent` for incremental cache updates.
- [ ] 6.9 Unit tests: every indicator against known reference values (e.g. TA-Lib or hand-computed fixtures).
- [ ] 6.10 Unit test: cache hit avoids recomputation (assert underlying calculation called once for N concurrent requesters).

## Phase 7 — Market Regime

- [ ] 7.1 Implement `market_regime/market_state.py` (`MarketState` value object).
- [ ] 7.2 Implement `market_regime/trend_detector.py` (ADX-threshold trending classification).
- [ ] 7.3 Implement `market_regime/range_detector.py` (Donchian-width/compression-based ranging classification).
- [ ] 7.4 Implement `market_regime/volatility_detector.py` (ATR-percentile high/low classification).
- [ ] 7.5 Implement bias classification (MA slope/ordering → bullish/bearish/neutral) inside `market_state.py`.
- [ ] 7.6 Wire regime recomputation on candle close; publish `MarketRegimeChangedEvent` on state transitions.
- [ ] 7.7 Persist `market_regime_snapshots` on every recomputation via `regime_repository`.
- [ ] 7.8 Unit tests: regime classification against hand-labeled historical fixture periods (known trend / known range / known high-vol period).

## Phase 8 — Exchange Execution Adapters (Binance + Paper only)

- [ ] 8.1 Implement `execution/adapters/base_adapter.py` shared adapter scaffolding.
- [ ] 8.2 Implement `execution/adapters/paper_adapter.py` (simulated fills against live market data).
- [ ] 8.3 Implement `execution/order_manager.py` order state machine.
- [ ] 8.4 Implement `execution/execution_router.py` (routes `OrderIntentEvent` → correct adapter by account).
- [ ] 8.5 Unit tests: order state machine transitions, idempotency via `client_order_id`.
- [ ] 8.6 Implement `execution/adapters/binance_adapter.py` (CCXT REST, testnet first).
- [ ] 8.7 Implement `execution/reconciliation.py` periodic local-vs-exchange state diff.
- [ ] 8.8 Implement `utils/rate_limiter.py` token-bucket limiter, wire into the Binance adapter.
- [ ] 8.9 Implement `utils/retry.py` backoff/retry decorator, wire into REST calls.
- [ ] 8.10 Integration tests: Binance adapter against testnet (place/cancel/fetch order).
- [ ] 8.11 `services/order_service.py` orchestration + worker container wiring.

## Phase 9 — Strategy Plugin Engine

- [ ] 9.1 Implement `strategies/base_strategy.py` ABC (`on_market_data`, `on_fill`, `on_start`, `on_stop`).
- [ ] 9.2 Implement `strategies/signal.py` value object (incl. `confidence`, `reasoning`).
- [ ] 9.3 Implement `strategies/registry.py` (decorator-based + entry-point discovery).
- [ ] 9.4 Implement `StrategyContext` with `context.features.get(...)` and `context.regime.current(symbol)` accessors.
- [ ] 9.5 Implement example strategy `strategies/examples/ma_crossover.py` (simple confidence formula: trend quality + regime fit).
- [ ] 9.6 Implement example strategy `strategies/examples/mean_reversion.py`.
- [ ] 9.7 Unit tests: registry discovery, base strategy lifecycle, both example strategies against fixture data.
- [ ] 9.8 `services/strategy_service.py`: load `strategy_instances` from DB, instantiate registered strategies, wire to event bus.

## Phase 10 — Strategy Voting Engine (optional/composable pattern)

- [ ] 10.1 Implement `strategy_voting/signal_generator.py` (lightweight `SignalGenerator` interface — direction/confidence/reasoning per bar, no owned capital/position).
- [ ] 10.2 Implement `strategy_voting/generators/trend_following.py`.
- [ ] 10.3 Implement `strategy_voting/generators/momentum.py`.
- [ ] 10.4 Implement `strategy_voting/generators/breakout.py`.
- [ ] 10.5 Implement `strategy_voting/generators/volume.py`.
- [ ] 10.6 Implement `strategy_voting/generators/mean_reversion.py`.
- [ ] 10.7 Implement `strategy_voting/confidence.py` (composite confidence: trend quality, momentum, volume, volatility, regime fit, funding, signal agreement).
- [ ] 10.8 Implement `strategy_voting/voting_engine.py` (`combine(sub_signals) -> Signal`).
- [ ] 10.9 Implement `strategies/composite_strategy.py` (`CompositeStrategy` base wiring generators → voting engine → single emitted `Signal`).
- [ ] 10.10 Unit tests: voting engine combination logic (unanimous, split, low-agreement cases), confidence formula against known inputs.
- [ ] 10.11 Integration test: one example `CompositeStrategy` instance end-to-end against fixture data, verify it emits exactly one `Signal` per bar indistinguishable in shape from a simple strategy's.

## Phase 11 — Portfolio Management

- [ ] 11.1 Implement `portfolio/position_tracker.py` (updates from `FillEvent`).
- [ ] 11.2 Implement `portfolio/pnl_calculator.py` (realized/unrealized PnL, funding accrual).
- [ ] 11.3 Implement `portfolio/portfolio_manager.py` (aggregate view across strategies/symbols).
- [ ] 11.4 Implement `portfolio/allocator.py` (capital allocation across strategy instances).
- [ ] 11.5 Unit tests: PnL calculation correctness across partial fills, both position sides, fee handling.
- [ ] 11.6 Wire `portfolio` to persist positions/trades via `repositories`.

## Phase 12 — Risk Management

- [ ] 12.1 Implement `risk/position_sizing.py` fixed-fractional model.
- [ ] 12.2 Implement `risk/position_sizing.py` volatility-target model.
- [ ] 12.3 Implement `risk/position_sizing.py` confidence-scaled model (scales base size by `signal.confidence / 100`, configurable floor, opt-in per strategy instance).
- [ ] 12.4 Implement `risk/limits.py` (exposure/leverage/concentration checks reading `risk_limits` table).
- [ ] 12.5 Implement `risk/pre_trade_checks.py` pipeline (composable check chain).
- [ ] 12.6 Implement `risk/circuit_breaker.py` (drawdown trip, error-rate trip, manual trip).
- [ ] 12.7 Implement `risk/risk_engine.py` orchestrator wiring 12.1–12.6 into the `SignalEvent → OrderIntentEvent` path.
- [ ] 12.8 Unit tests: every check independently, plus full pipeline integration test with a deliberately-breaching signal.
- [ ] 12.9 Wire `risk_engine` rejections to `AlertEvent` + `audit_log`.

## Phase 13 — Backtesting Engine

- [ ] 13.1 Implement `backtesting/data_feed.py` (historical candles/trades from `repositories`, time-ordered).
- [ ] 13.2 Implement `backtesting/event_simulator.py` (deterministic replay loop, look-ahead prevention — extended to `features`/`market_regime` lookbacks).
- [ ] 13.3 Implement `backtesting/slippage_models.py` (fixed-bps, next-bar-open, volume-participation).
- [ ] 13.4 Implement `backtesting/broker_simulator.py` implementing `ExchangeGateway`.
- [ ] 13.5 Implement `backtesting/engine.py` orchestrating simulator + features + market_regime + strategies + risk + portfolio (all reused unmodified from live).
- [ ] 13.6 Persist results to `backtest_runs`/`backtest_trades`/`equity_curve_points`, and `signals` for every backtest run.
- [ ] 13.7 Golden-dataset regression test fixture + CI check.
- [ ] 13.8 `scripts/run_backtest.py` CLI entrypoint.
- [ ] 13.9 `services/backtest_service.py` for API-triggered runs.

## Phase 14 — Analytics

- [ ] 14.1 Implement `analytics/performance_metrics.py` (Sharpe, Sortino, Calmar, max drawdown, win rate).
- [ ] 14.2 Implement `analytics/attribution.py` (per-strategy, per-symbol PnL breakdown).
- [ ] 14.3 Extend `analytics/attribution.py` with per-regime and per-confidence-bucket breakdowns.
- [ ] 14.4 Implement `analytics/tearsheet.py` (structured report data model).
- [ ] 14.5 Implement `analytics/reporting.py` (HTML/PDF export).
- [ ] 14.6 Unit tests: metrics correctness against known reference values.

## Phase 15 — Optimization (Grid Search + Walk-Forward only)

- [ ] 15.1 Implement `optimization/objective_functions.py` (Sharpe, Calmar, custom).
- [ ] 15.2 Implement `optimization/param_search.py` grid search (behind a `SearchStrategy` protocol that a future Bayesian implementation will also satisfy).
- [ ] 15.3 Implement `optimization/param_search.py` random search.
- [ ] 15.4 Implement `optimization/overfitting_guards.py` (deflated Sharpe, min sample size gate).
- [ ] 15.5 Implement `optimization/walk_forward.py` rolling train/test orchestrator.
- [ ] 15.6 Persist `optimization_runs` linked to child `backtest_runs`.
- [ ] 15.7 Integration test: full walk-forward run on fixture dataset, verify in/out-of-sample split correctness.

## Phase 16 — Trade Journal

- [ ] 16.1 Implement `journal/journal_recorder.py`: subscribe to `SignalEvent`/`FillEvent`/`OrderUpdateEvent`.
- [ ] 16.2 Implement open-entry logic: first fill establishing a new position → create `journal_entries` row from the triggering `signals` row.
- [ ] 16.3 Implement close-entry logic: fill that flattens a position → finalize `pnl`/`fees`/`funding`/`holding_time_seconds`/`exit_reason`.
- [ ] 16.4 Implement `journal/exporters/csv_exporter.py`.
- [ ] 16.5 Implement `journal/exporters/pdf_exporter.py`.
- [ ] 16.6 Unit tests: open/close lifecycle against synthetic fill sequences (incl. partial fills, scale-ins).
- [ ] 16.7 Integration test: journal entries produced correctly during a full paper-trading soak (ties into Phase 20).

## Phase 17 — FastAPI Application

- [ ] 17.1 Implement `api/main.py` app factory + lifespan (DB/Redis connection setup/teardown).
- [ ] 17.2 Implement `api/deps.py` (DB session dependency, auth dependency).
- [ ] 17.3 Implement auth middleware (JWT) in `api/middleware/`.
- [ ] 17.4 Implement request-id/correlation-id middleware.
- [ ] 17.5 Implement global exception handler mapping `core.exceptions` → HTTP responses.
- [ ] 17.6 Implement `api/v1/routers/system.py` (health, readiness, version, circuit-breaker status/trip).
- [ ] 17.7 Implement `api/v1/routers/market.py` (symbols, candles query endpoints).
- [ ] 17.8 Implement `api/v1/routers/positions.py`.
- [ ] 17.9 Implement `api/v1/routers/orders.py` (list/cancel).
- [ ] 17.10 Implement `api/v1/routers/strategies.py` (CRUD + start/pause/stop).
- [ ] 17.11 Implement `api/v1/routers/signals.py` (signal + confidence history, read-only).
- [ ] 17.12 Implement `api/v1/routers/regime.py` (current/historical market regime per symbol).
- [ ] 17.13 Implement `api/v1/routers/journal.py` (query + CSV/PDF export).
- [ ] 17.14 Implement `api/v1/routers/backtests.py` (submit run, fetch results/tearsheet).
- [ ] 17.15 Implement `api/websockets/live_feed.py` bridging Redis event bus → connected clients.
- [ ] 17.16 Generate/commit OpenAPI schema artifact for contract review.
- [ ] 17.17 Integration tests for every router (real test DB, mocked auth).
- [ ] 17.18 `docker/Dockerfile.api` + wire into `docker-compose.yml`.

## Phase 18 — Notifications

- [ ] 18.1 Implement `notifications/base_notifier.py` ABC.
- [ ] 18.2 Implement `notifications/telegram_notifier.py`.
- [ ] 18.3 Implement `notifications/discord_notifier.py`.
- [ ] 18.4 Implement message templates per event type (`notifications/templates/`), incl. `MarketRegimeChangedEvent`.
- [ ] 18.5 Implement `services/notification_service.py` subscribing to `AlertEvent`/`FillEvent`/`CircuitBreakerTrippedEvent`/`MarketRegimeChangedEvent` on the bus.
- [ ] 18.6 Unit tests: template rendering, notifier retry-on-failure behavior.
- [ ] 18.7 Worker container wiring for the notification service (journal recorder co-located here per §13 of architecture doc).

## Phase 19 — Dashboard (Streamlit)

- [ ] 19.1 Implement `dashboard/app.py` shell + API client wrapper (auth token handling).
- [ ] 19.2 Implement `dashboard/pages/overview.py` (equity curve, circuit-breaker status, current regime per symbol).
- [ ] 19.3 Implement `dashboard/pages/positions.py`.
- [ ] 19.4 Implement `dashboard/pages/strategies.py` (list + start/pause/stop controls + confidence distribution).
- [ ] 19.5 Implement `dashboard/pages/journal.py` (table view, filters, export buttons).
- [ ] 19.6 Implement `dashboard/pages/backtests.py` (run submission + tearsheet viewer).
- [ ] 19.7 Implement `dashboard/pages/risk.py` (limits view, recent rejections, manual kill-switch).
- [ ] 19.8 Wire live updates via the WS endpoint.
- [ ] 19.9 `docker/Dockerfile.dashboard` + wire into `docker-compose.yml`.

## Phase 20 — Paper Trading End-to-End

- [ ] 20.1 Wire `paper_adapter` into `execution_router` for `accounts.is_paper = true`.
- [ ] 20.2 Run one `ma_crossover` strategy instance in paper mode against live Binance testnet market data for a soak test.
- [ ] 20.3 Run one `CompositeStrategy` instance in paper mode alongside it, to validate the voting pattern end-to-end.
- [ ] 20.4 Verify full loop: market data → features → regime → signal (with confidence) → risk → paper fill → portfolio update → journal entry → dashboard reflects it → Telegram alert fires.
- [ ] 20.5 Document the paper-trading runbook in `README.md`.

## Phase 21 — Live Execution Readiness

- [ ] 21.1 Security review of API key storage/encryption end-to-end.
- [ ] 21.2 Add manual approval gate in `strategies` promotion (backtest → paper → live) via `strategy_instances.mode` transition audit.
- [ ] 21.3 Load-test `market_data_worker` reconnect handling under simulated exchange disconnects.
- [ ] 21.4 Chaos test: kill `execution_worker` mid-order, verify reconciliation detects and resolves the mismatch.
- [ ] 21.5 Enable the Binance live adapter for a single strategy instance with a small `allocated_capital` and tight `risk_limits`.
- [ ] 21.6 Post-launch monitoring runbook (what to watch, how to trip the kill switch manually).

## Phase 22 — CI/CD & Deployment Hardening

- [ ] 22.1 Add integration test job (Postgres/Redis service containers) to `ci.yml`.
- [ ] 22.2 Add `pip-audit` dependency scan job.
- [ ] 22.3 Add import-boundary/architecture-conformance check job.
- [ ] 22.4 Add `.github/workflows/docker-build.yml` (build+push on merge to main).
- [ ] 22.5 Add `.github/workflows/release.yml` (tag-triggered, changelog, approval-gated deploy).
- [ ] 22.6 Add coverage gate for `core/`, `risk/`, `portfolio/`, `backtesting/`, `features/`, `market_regime/`.
- [ ] 22.7 Write `docs/adr/` template and backfill ADRs for key decisions (incl. this revision's: optional voting engine, sentiment deferral, single-exchange V1).
- [ ] 22.8 Production `docker-compose.yml` variant with resource limits, restart policies, log driver config.

## Phase 23 — V1 Wrap-Up

- [ ] 23.1 Full regression pass: unit + integration + backtest golden-dataset + paper-trading soak review.
- [ ] 23.2 Documentation pass: confirm `README.md`, `docs/ARCHITECTURE.md`, and API docs (`/docs`) all reflect what actually shipped.
- [ ] 23.3 Tag `v1.0.0`.

---

## Phase 24+ — Post-V1 Roadmap (not V1 milestones — tracked here for continuity)

- [ ] 24.1 `execution/adapters/bybit_adapter.py` + `market_data/providers/bybit_futures.py` (per the checklist in architecture §9 — validates the exchange abstraction generalizes with minimal work).
- [ ] 24.2 Third exchange (OKX or Deribit).
- [ ] 24.3 Bayesian search (`optimization/param_search.py` third `SearchStrategy` implementation).
- [ ] 24.4 `market_regime/sentiment_filter.py` + external news/social data ingestion pipeline.
- [ ] 24.5 Statistical/ML regime-switching model (e.g. HMM) as an alternative to rule-based `market_regime` detectors.
- [ ] 24.6 `ai_research/llm_client.py`, `strategy_generator.py`, `research_agent.py` (produces `strategies/`-conforming plugins only — no redesign of downstream modules required).
- [ ] 24.7 Multi-account / multi-tenant support.
- [ ] 24.8 Low-latency execution path (colocation, WS order entry).
- [ ] 24.9 FIX protocol adapter.
- [ ] 24.10 Kafka migration if Redis Streams throughput becomes limiting.
- [ ] 24.11 Compliance/audit reporting exports.
- [ ] 24.12 Kubernetes deployment manifests.
- [ ] 24.13 Mobile companion app (read-only, over existing `api/`).
- [ ] 24.14 Options/derivatives strategy support.

---

### How to use this file

- Work top-to-bottom within a phase; phases 0–4 are hard prerequisites for everything
  else. Phases 5–19 can largely proceed in parallel once 0–4 are done — note that
  Phase 9 (Strategies) depends on Phase 6 (Feature Engine) and Phase 7 (Market
  Regime) for `StrategyContext`, and Phase 10 (Voting) depends on Phase 9.
- Each checked-off task should correspond to one PR with its own tests.
- Do not skip ahead to Phase 21 (live execution) until Phase 20 (paper trading
  end-to-end) has run cleanly for a meaningful soak period — this is a hard gate, not
  a suggestion.
- Phase 24+ items are explicitly **not** part of the V1 milestone count; they're kept
  here only so roadmap continuity is visible in one place alongside the shipped work.
