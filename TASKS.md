# TASKS.md — Implementation Milestones

This is the execution plan derived from `docs/ARCHITECTURE.md`. Every task is scoped
to be completable independently, reviewable in a single PR, and small enough to not
require touching more than one or two folders. Phases are ordered by dependency —
later phases assume earlier ones are done, but tasks *within* a phase can generally
be parallelized across contributors.

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

- [ ] 1.1 Define `core/enums.py` (`OrderSide`, `OrderType`, `TimeInForce`, `OrderStatus`, `StrategyMode`, `PositionSide`).
- [ ] 1.2 Define `core/types.py` value objects (`Symbol`, `Money`/`Price` using `Decimal`).
- [ ] 1.3 Define `core/exceptions.py` full hierarchy (§17 of architecture doc).
- [ ] 1.4 Define `core/constants.py` (default timeframes, precision defaults).
- [ ] 1.5 Define `core/events.py` event dataclasses (`MarketDataEvent` family, `SignalEvent`, `OrderIntentEvent`, `OrderUpdateEvent`, `FillEvent`, `RiskRejectedEvent`, `AlertEvent`).
- [ ] 1.6 Implement `core/event_bus.py` in-process asyncio implementation + abstract `EventBus` interface.
- [ ] 1.7 Implement Redis-backed `EventBus` implementation (behind the same interface).
- [ ] 1.8 Define `core/interfaces/exchange_gateway.py` ABC.
- [ ] 1.9 Define `core/interfaces/strategy.py` ABC.
- [ ] 1.10 Define `core/interfaces/repository.py` generic ABC.
- [ ] 1.11 Define `core/interfaces/notifier.py` ABC.
- [ ] 1.12 Unit tests for event bus (pub/sub ordering, multiple subscribers) — both backends.
- [ ] 1.13 Add import-boundary lint check (custom AST/import-linter config) enforcing `core` has zero first-party imports.

## Phase 2 — Configuration & Logging

- [ ] 2.1 Implement `config/settings.py` (`Pydantic BaseSettings`, env-driven, per-environment).
- [ ] 2.2 Implement `config/logging.py` structured JSON logging factory + secret redaction filter.
- [ ] 2.3 Write `config/environments/development.env.example`, `staging.env.example`, `production.env.example`.
- [ ] 2.4 Unit tests: settings validation fails fast on missing required vars.

## Phase 3 — Database & Persistence Layer

- [ ] 3.1 Implement `database/base.py` (`DeclarativeBase`, `TimestampMixin`, `UUIDPkMixin`).
- [ ] 3.2 Implement `database/session.py` async engine/session factory.
- [ ] 3.3 Initialize Alembic (`database/alembic/`, `alembic.ini`).
- [ ] 3.4 Model + migration: `exchanges`, `symbols`.
- [ ] 3.5 Model + migration: `accounts`, `balances` (with encrypted API key fields).
- [ ] 3.6 Model + migration: `candles` (Timescale hypertable if extension available), `orderbook_snapshots`.
- [ ] 3.7 Model + migration: `strategy_definitions`, `strategy_instances`.
- [ ] 3.8 Model + migration: `orders`, `trades`, `positions`.
- [ ] 3.9 Model + migration: `backtest_runs`, `backtest_trades`, `equity_curve_points`.
- [ ] 3.10 Model + migration: `optimization_runs`.
- [ ] 3.11 Model + migration: `risk_limits`, `audit_log`, `alerts`.
- [ ] 3.12 Implement `repositories/base.py` generic async CRUD repository.
- [ ] 3.13 Implement `market_repository.py`, `order_repository.py`, `trade_repository.py`, `position_repository.py`, `strategy_repository.py`, `backtest_repository.py`.
- [ ] 3.14 Integration tests for every repository against a real test-Postgres container.
- [ ] 3.15 `scripts/seed_db.py` for local dev seed data (sample exchanges/symbols).
- [ ] 3.16 Add `docker-compose.yml` service for `postgres` (Timescale image) + `redis`, with healthchecks.

## Phase 4 — Schemas (Pydantic DTOs)

- [ ] 4.1 `schemas/common.py` (pagination envelope, error envelope).
- [ ] 4.2 `schemas/market.py` (Symbol, Candle DTOs).
- [ ] 4.3 `schemas/order.py`, `schemas/position.py`.
- [ ] 4.4 `schemas/strategy.py` (instance create/update/response DTOs).
- [ ] 4.5 `schemas/backtest.py` (run request/response, tearsheet DTO).
- [ ] 4.6 Unit tests: schema validation edge cases (bad enums, negative sizes, etc.).

## Phase 5 — Market Data Subsystem

- [ ] 5.1 Implement `market_data/providers/binance_futures.py` WS subscription wrapper (CCXT Pro).
- [ ] 5.2 Implement `market_data/providers/bybit_futures.py` WS subscription wrapper (CCXT Pro).
- [ ] 5.3 Implement `market_data/ws_manager.py` connection lifecycle + reconnect/backoff logic.
- [ ] 5.4 Implement `market_data/feed_normalizer.py` (raw payload → `core.events` MarketDataEvent family).
- [ ] 5.5 Implement `market_data/orderbook_builder.py` (L2 diff application, checksum validation).
- [ ] 5.6 Implement `market_data/candle_aggregator.py` (trade stream → OHLCV bars, multiple timeframes).
- [ ] 5.7 Implement `market_data/historical_loader.py` REST backfill with gap detection against `candles`.
- [ ] 5.8 Wire market data pipeline to publish onto `core.event_bus`.
- [ ] 5.9 Unit tests: normalizer, orderbook_builder (using recorded fixture payloads).
- [ ] 5.10 Integration test: live testnet WS connection smoke test (nightly/manual only).
- [ ] 5.11 `services/market_data_service.py` orchestration entrypoint + worker container (`docker/Dockerfile.worker` target).

## Phase 6 — Exchange Execution Adapters (Paper First)

- [ ] 6.1 Implement `execution/adapters/base_adapter.py` shared adapter scaffolding.
- [ ] 6.2 Implement `execution/adapters/paper_adapter.py` (simulated fills against live market data).
- [ ] 6.3 Implement `execution/order_manager.py` order state machine.
- [ ] 6.4 Implement `execution/execution_router.py` (routes `OrderIntentEvent` → correct adapter by account).
- [ ] 6.5 Unit tests: order state machine transitions, idempotency via `client_order_id`.
- [ ] 6.6 Implement `execution/adapters/binance_adapter.py` (CCXT REST, testnet first).
- [ ] 6.7 Implement `execution/adapters/bybit_adapter.py` (CCXT REST, testnet first).
- [ ] 6.8 Implement `execution/reconciliation.py` periodic local-vs-exchange state diff.
- [ ] 6.9 Implement `utils/rate_limiter.py` token-bucket limiter, wire into adapters.
- [ ] 6.10 Implement `utils/retry.py` backoff/retry decorator, wire into REST calls.
- [ ] 6.11 Integration tests: adapters against exchange testnets (place/cancel/fetch order).
- [ ] 6.12 `services/order_service.py` orchestration + worker container wiring.

## Phase 7 — Strategy Plugin Engine

- [ ] 7.1 Implement `strategies/base_strategy.py` ABC (`on_market_data`, `on_fill`, `on_start`, `on_stop`).
- [ ] 7.2 Implement `strategies/signal.py` value object.
- [ ] 7.3 Implement `strategies/registry.py` (decorator-based + entry-point discovery).
- [ ] 7.4 Implement `StrategyContext` (read-only position/candle accessors).
- [ ] 7.5 Implement example strategy `strategies/examples/ma_crossover.py`.
- [ ] 7.6 Implement example strategy `strategies/examples/mean_reversion.py`.
- [ ] 7.7 Unit tests: registry discovery, base strategy lifecycle, both example strategies against fixture data.
- [ ] 7.8 Add import-boundary lint rule: `strategies/` cannot import `execution`/`database`/`api`.
- [ ] 7.9 `services/strategy_service.py`: load `strategy_instances` from DB, instantiate registered strategies, wire to event bus.

## Phase 8 — Portfolio Management

- [ ] 8.1 Implement `portfolio/position_tracker.py` (updates from `FillEvent`).
- [ ] 8.2 Implement `portfolio/pnl_calculator.py` (realized/unrealized PnL, funding accrual).
- [ ] 8.3 Implement `portfolio/portfolio_manager.py` (aggregate view across strategies/symbols).
- [ ] 8.4 Implement `portfolio/allocator.py` (capital allocation across strategy instances).
- [ ] 8.5 Unit tests: PnL calculation correctness across partial fills, both position sides, fee handling.
- [ ] 8.6 Wire `portfolio` to persist positions/trades via `repositories`.

## Phase 9 — Risk Management

- [ ] 9.1 Implement `risk/position_sizing.py` (fixed-fractional model first).
- [ ] 9.2 Implement `risk/limits.py` (exposure/leverage/concentration checks reading `risk_limits` table).
- [ ] 9.3 Implement `risk/pre_trade_checks.py` pipeline (composable check chain).
- [ ] 9.4 Implement `risk/circuit_breaker.py` (drawdown trip, error-rate trip, manual trip).
- [ ] 9.5 Implement `risk/risk_engine.py` orchestrator wiring 9.1–9.4 into the `SignalEvent → OrderIntentEvent` path.
- [ ] 9.6 Add volatility-target position sizing model (second `position_sizing` implementation).
- [ ] 9.7 Unit tests: every check independently, plus full pipeline integration test with a deliberately-breaching signal.
- [ ] 9.8 Wire `risk_engine` rejections to `AlertEvent` + `audit_log`.

## Phase 10 — Backtesting Engine

- [ ] 10.1 Implement `backtesting/data_feed.py` (historical candles/trades from `repositories`, time-ordered).
- [ ] 10.2 Implement `backtesting/event_simulator.py` (deterministic replay loop, look-ahead prevention).
- [ ] 10.3 Implement `backtesting/slippage_models.py` (fixed-bps, next-bar-open, volume-participation).
- [ ] 10.4 Implement `backtesting/broker_simulator.py` implementing `ExchangeGateway`.
- [ ] 10.5 Implement `backtesting/engine.py` orchestrating simulator + strategies + risk + portfolio (all reused unmodified).
- [ ] 10.6 Persist results to `backtest_runs`/`backtest_trades`/`equity_curve_points`.
- [ ] 10.7 Golden-dataset regression test fixture + CI check (§18 of architecture doc).
- [ ] 10.8 `scripts/run_backtest.py` CLI entrypoint.
- [ ] 10.9 `services/backtest_service.py` for API-triggered runs.

## Phase 11 — Analytics

- [ ] 11.1 Implement `analytics/performance_metrics.py` (Sharpe, Sortino, Calmar, max drawdown, win rate).
- [ ] 11.2 Implement `analytics/attribution.py` (per-strategy, per-symbol PnL breakdown).
- [ ] 11.3 Implement `analytics/tearsheet.py` (structured report data model).
- [ ] 11.4 Implement `analytics/reporting.py` (HTML/PDF export).
- [ ] 11.5 Unit tests: metrics correctness against known reference values.

## Phase 12 — Optimization / Walk-Forward

- [ ] 12.1 Implement `optimization/objective_functions.py` (Sharpe, Calmar, custom).
- [ ] 12.2 Implement `optimization/param_search.py` grid search.
- [ ] 12.3 Implement `optimization/param_search.py` random search.
- [ ] 12.4 Implement `optimization/param_search.py` Bayesian search (optional dependency, e.g. `scikit-optimize`).
- [ ] 12.5 Implement `optimization/overfitting_guards.py` (deflated Sharpe, min sample size gate).
- [ ] 12.6 Implement `optimization/walk_forward.py` rolling train/test orchestrator.
- [ ] 12.7 Persist `optimization_runs` linked to child `backtest_runs`.
- [ ] 12.8 Integration test: full walk-forward run on fixture dataset, verify in/out-of-sample split correctness.

## Phase 13 — FastAPI Application

- [ ] 13.1 Implement `api/main.py` app factory + lifespan (DB/Redis connection setup/teardown).
- [ ] 13.2 Implement `api/deps.py` (DB session dependency, auth dependency).
- [ ] 13.3 Implement auth middleware (JWT) in `api/middleware/`.
- [ ] 13.4 Implement request-id/correlation-id middleware.
- [ ] 13.5 Implement global exception handler mapping `core.exceptions` → HTTP responses.
- [ ] 13.6 Implement `api/v1/routers/system.py` (health, readiness, version, circuit-breaker status/trip).
- [ ] 13.7 Implement `api/v1/routers/market.py` (symbols, candles query endpoints).
- [ ] 13.8 Implement `api/v1/routers/positions.py`.
- [ ] 13.9 Implement `api/v1/routers/orders.py` (list/cancel).
- [ ] 13.10 Implement `api/v1/routers/strategies.py` (CRUD + start/pause/stop).
- [ ] 13.11 Implement `api/v1/routers/backtests.py` (submit run, fetch results/tearsheet).
- [ ] 13.12 Implement `api/websockets/live_feed.py` bridging Redis event bus → connected clients.
- [ ] 13.13 Generate/commit OpenAPI schema artifact for contract review.
- [ ] 13.14 Integration tests for every router (real test DB, mocked auth).
- [ ] 13.15 `docker/Dockerfile.api` + wire into `docker-compose.yml`.

## Phase 14 — Notifications

- [ ] 14.1 Implement `notifications/base_notifier.py` ABC.
- [ ] 14.2 Implement `notifications/telegram_notifier.py`.
- [ ] 14.3 Implement `notifications/discord_notifier.py`.
- [ ] 14.4 Implement message templates per event type (`notifications/templates/`).
- [ ] 14.5 Implement `services/notification_service.py` subscribing to `AlertEvent`/`FillEvent`/`CircuitBreakerTrippedEvent` on the bus.
- [ ] 14.6 Unit tests: template rendering, notifier retry-on-failure behavior.
- [ ] 14.7 Worker container wiring for the notification service.

## Phase 15 — Dashboard (Streamlit)

- [ ] 15.1 Implement `dashboard/app.py` shell + API client wrapper (auth token handling).
- [ ] 15.2 Implement `dashboard/pages/overview.py` (equity curve, circuit-breaker status).
- [ ] 15.3 Implement `dashboard/pages/positions.py`.
- [ ] 15.4 Implement `dashboard/pages/strategies.py` (list + start/pause/stop controls).
- [ ] 15.5 Implement `dashboard/pages/backtests.py` (run submission + tearsheet viewer).
- [ ] 15.6 Implement `dashboard/pages/risk.py` (limits view, recent rejections, manual kill-switch).
- [ ] 15.7 Wire live updates via the WS endpoint.
- [ ] 15.8 `docker/Dockerfile.dashboard` + wire into `docker-compose.yml`.

## Phase 16 — Paper Trading End-to-End

- [ ] 16.1 Wire `paper_adapter` into `execution_router` for `accounts.is_paper = true`.
- [ ] 16.2 Run one `ma_crossover` strategy instance in paper mode against live testnet market data for a soak test.
- [ ] 16.3 Verify full loop: market data → signal → risk → paper fill → portfolio update → dashboard reflects it → Telegram alert fires.
- [ ] 16.4 Document the paper-trading runbook in `README.md`.

## Phase 17 — Live Execution Readiness

- [ ] 17.1 Security review of API key storage/encryption end-to-end (§14).
- [ ] 17.2 Add manual approval gate in `strategies` promotion (backtest → paper → live) via `strategy_instances.mode` transition audit.
- [ ] 17.3 Load-test `market_data_worker` reconnect handling under simulated exchange disconnects.
- [ ] 17.4 Chaos test: kill `execution_worker` mid-order, verify reconciliation (§7/§17) detects and resolves the mismatch.
- [ ] 17.5 Enable live adapters for a single strategy instance with a small `allocated_capital` and tight `risk_limits`.
- [ ] 17.6 Post-launch monitoring runbook (what to watch, how to trip the kill switch manually).

## Phase 18 — AI-Assisted Strategy Research

- [ ] 18.1 Implement `ai_research/llm_client.py` provider-agnostic wrapper.
- [ ] 18.2 Implement `ai_research/prompts/` templates for hypothesis generation.
- [ ] 18.3 Implement `ai_research/strategy_generator.py` (LLM output → `strategies/` scaffold conforming to `base_strategy.py`).
- [ ] 18.4 Implement `ai_research/research_agent.py` loop: hypothesis → backtest → walk-forward → report.
- [ ] 18.5 Human-in-the-loop approval gate before any AI-generated strategy reaches `paper` mode.
- [ ] 18.6 Unit tests: generated strategy scaffolds pass the same `registry`/schema validation as hand-written ones.

## Phase 19 — CI/CD & Deployment Hardening

- [ ] 19.1 Add integration test job (Postgres/Redis service containers) to `ci.yml`.
- [ ] 19.2 Add `pip-audit` dependency scan job.
- [ ] 19.3 Add import-boundary/architecture-conformance check job.
- [ ] 19.4 Add `.github/workflows/docker-build.yml` (build+push on merge to main).
- [ ] 19.5 Add `.github/workflows/release.yml` (tag-triggered, changelog, approval-gated deploy).
- [ ] 19.6 Add coverage gate for `core/`, `risk/`, `portfolio/`, `backtesting/`.
- [ ] 19.7 Write `docs/adr/` template and backfill ADRs for key decisions already made in `docs/ARCHITECTURE.md`.
- [ ] 19.8 Production `docker-compose.yml` variant with resource limits, restart policies, log driver config.

## Phase 20 — Post-Launch / Roadmap Seeds

- [ ] 20.1 Add third exchange adapter (validates the abstraction from §9 generalizes).
- [ ] 20.2 Multi-account support in `portfolio_manager`/risk scoping.
- [ ] 20.3 Centralized log shipping (Loki/ELK) using the existing structured JSON format.
- [ ] 20.4 Evaluate Kafka migration if Redis Streams throughput becomes limiting.
- [ ] 20.5 Kubernetes manifests as an alternative deployment target to docker-compose.

---

### How to use this file

- Work top-to-bottom within a phase; phases 0–4 are hard prerequisites for everything
  else. Phases 5–15 can largely proceed in parallel once 0–4 are done, since they
  share only `core/` and `repositories/`.
- Each checked-off task should correspond to one PR with its own tests.
- Do not skip ahead to Phase 17 (live execution) until Phase 16 (paper trading
  end-to-end) has run cleanly for a meaningful soak period — this is a hard gate, not
  a suggestion.
