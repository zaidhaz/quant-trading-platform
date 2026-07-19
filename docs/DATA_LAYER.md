# Data Layer

The historical data layer sources everything the research pipeline needs from
Binance USDⓈ-M Futures, stores it in Parquet, and syncs it incrementally. This
document is the map of what exists, what each endpoint can and cannot provide,
and how the pieces compose. It is referenced from several module docstrings
(`binance_client.py`, `open_interest_dataset.py`, `exchange_info.py`) as the
place to come for the full picture rather than repeating it in each file.

## Status: not yet verified against the live API

Outbound access to `fapi.binance.com` is blocked by this sandbox's network
policy — confirmed directly (a `CONNECT` to the host is rejected with a 403
policy denial, not a timeout), not assumed. Everything described below is
implemented from Binance's published API documentation and tested against a
mocked client (`tests/unit/market_data/`), never against a real response. No
code in this layer is expected to need changes once network access exists —
only that live verification (does pagination behave as documented, are field
names exactly as documented, etc.) still needs to happen the first time it
runs for real. `research/data_loader.py`'s `mode="real"` is the intended way
to do that verification loudly (it raises instead of silently falling back).

## Endpoint coverage

| Dataset | Binance endpoint | Dataset class | History depth |
|---|---|---|---|
| OHLCV candles | `GET /fapi/v1/klines` | `CandlesDataset` | Full history back to listing |
| Funding rate | `GET /fapi/v1/fundingRate` | `FundingRateDataset` | Full history back to listing |
| Mark price | `GET /fapi/v1/markPriceKlines` | `MarkPriceDataset` | Full history back to listing |
| Premium index | `GET /fapi/v1/premiumIndexKlines` | `PremiumIndexDataset` | Full history back to listing |
| Open interest | `GET /futures/data/openInterestHist` | `OpenInterestDataset` | **~30 trailing days only — Binance-side retention cap, see below** |
| Symbol metadata (incl. listing date) | `GET /fapi/v1/exchangeInfo` | `exchange_info.get_symbol_info()` | Current snapshot, not a time series |

Connectivity check: `GET /fapi/v1/ping` via `BinanceFuturesClient.ping()` — a
single no-retry request used to fail fast when the network is unreachable,
instead of paying `_get()`'s full 5-retry exponential-backoff cost (up to
~60s) per dataset/timeframe/symbol.

### The Open Interest limitation, documented not fabricated

`/futures/data/openInterestHist` does not return data older than roughly 30
days regardless of the requested `startTime` — this is Binance's own
documented behavior, not a limit discovered by shortening a range ourselves.
`OpenInterestDataset.download()` clamps its effective start to
`now - OPEN_INTEREST_MAX_LOOKBACK_DAYS` before ever calling the endpoint, so a
caller asking for full history gets exactly what Binance can provide (the
trailing window) rather than a doomed request for unavailable history or a
silently-truncated response. `find_earliest_available()` for this dataset
does not run an empirical probe like the others — the true earliest point is
always the fixed retention floor, so it returns that directly.

Consequence for the research pipeline: Open Interest can only ever inform the
most recent ~30 days of any run. `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md`
treats `oi_flush_confirmed` as inert by default for exactly this reason — it
is never assumed to be available across a multi-year backtest.

## Architecture

```
BinanceFuturesClient          -- thin REST client, one method pair per endpoint
    ├── get_klines / find_earliest_kline_open_time
    ├── get_funding_rate_history / find_earliest_funding_time
    ├── get_mark_price_klines / find_earliest_mark_price_time
    ├── get_premium_index_klines / find_earliest_premium_index_time
    ├── get_open_interest_hist
    ├── get_exchange_info
    └── ping

HistoricalDataset (ABC)       -- market_data/historical/dataset.py
    ├── download()                    per-subclass: hits the client, shapes a DataFrame
    ├── expected_frequency()          per-subclass: nominal row spacing, drives gap detection
    ├── find_earliest_available()     per-subclass: real earliest timestamp (or documented floor)
    ├── ensure_range()                shared: gap-only download + ParquetStore.write(), resumable
    └── sync_full_history()           shared: find_earliest_available() -> ensure_range() -> now

    ├── CandlesDataset
    ├── FundingRateDataset
    ├── MarkPriceDataset
    ├── PremiumIndexDataset
    └── OpenInterestDataset

ParquetStore                  -- market_data/historical/parquet_store.py
    write()   merge + dedup (keep last) + sort, on every write
    read()    one Parquet file per dataset/exchange/symbol[/timeframe]
```

`ensure_range()` and `ParquetStore.write()` predate this data-layer expansion
and are unchanged by it — `find_earliest_available()`/`sync_full_history()`
are a thin layer on top that removes the last reason to hardcode a start
date, not a rewrite of the sync mechanism itself.

## Never hardcode a date range

Every dataset except Open Interest (see above) implements
`find_earliest_available()` as a single lightweight `limit=1` request spanning
`[PROBE_FLOOR (2015-01-01), now]`. Binance's klines/funding/markPrice/
premiumIndex endpoints all return the *first row that actually exists* in the
requested window when asked for `limit=1`, so this needs no pagination or
binary search — one request finds the true earliest point, whatever it is,
including if Binance later extends how far back a symbol's history goes.
`PROBE_FLOOR` is a safe lower bound (predates Binance Futures' own 2019-09
launch), never a claim about when any symbol's data actually starts.

`exchange_info.get_symbol_info()`'s `onboard_date` (Binance's own record of a
contract's listing date) serves as an independent cross-check against the
empirically-probed start — `sync_historical_data.py` logs both so a
meaningful disagreement (a relisted contract, a gap right at listing) is
visible rather than silently accepted.

## Incremental sync

`scripts/sync_historical_data.py` is the production entry point:

```
python -m scripts.sync_historical_data --symbols BTCUSDT ETHUSDT
python -m scripts.sync_historical_data --symbols BTCUSDT \
    --candle-timeframes 1h 4h --skip-open-interest
```

For each symbol it syncs candles (across `--candle-timeframes`, default
`1m 5m 15m 1h 4h`), funding rate, mark price and premium index (across
`--mark-premium-timeframes`, default `1h 4h`), and open interest — each via
`HistoricalDataset.sync_full_history()`. Properties, by construction of the
pieces above:

- **Never redownloads existing data** — `ensure_range()` only fetches the
  sub-ranges `find_gaps()` reports missing from the local Parquet store.
- **Resumable** — safe to interrupt and rerun. A partial prior run just
  leaves gaps; the next run fills them. Nothing tracks "where it left off"
  separately from what is already on disk.
- **Deduplicated on write** — `ParquetStore.write()` merges, drops duplicate
  index timestamps (`keep="last"`), and sorts, on every write. The sync
  script's post-sync quality report (`research/data_quality.py`) is
  verification/reporting over that already-repaired storage, not a second
  repair pass.
- **Never fabricates missing data** — a dataset the source genuinely has
  nothing for raises `DataGapError` from `sync_full_history()` and is
  reported as a failed outcome in the summary table, never silently skipped
  or backfilled with invented values.

Verified end-to-end against a fully-mocked `client._get()` (exercising real
pagination and gap-filling logic, not a bypassed convenience method): a first
run performs a full paginated sync, a second run against the same store
performs only the small number of incremental requests needed to cover the
time elapsed since the first run.

## How the research pipeline picks a data source

`research/data_loader.py::load_history()` is the single place that decides,
per symbol/timeframe, whether a pipeline run uses real or synthetic data:

- `mode="auto"` (default) — `ping()` first; on failure, or on a
  `DataGapError`/`ConnectionError` from the real fetch, falls back to
  clearly-labeled synthetic data with the failure reason recorded. Right tool
  for an unattended run in an environment that may or may not have network
  access.
- `mode="real"` — real data or fail loudly; no silent fallback. This is what
  someone deliberately running the definitive study should use.
- `mode="synthetic"` — always synthetic, for continued methodology testing.

`scripts/run_research_pipeline.py --data-source {auto,real,synthetic}` passes
this straight through. Every result the pipeline produces carries its actual
`source` ("real" or "synthetic"), and the report's §0 and the pre-registered
decision rule's mandated binary conclusion (`research/conclusion.py`) both
gate strictly on whether every symbol's data was real — nothing in the
pipeline script itself needs to change the day real access exists.
