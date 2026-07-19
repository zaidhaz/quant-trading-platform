# Quant Trading Platform

Institutional-grade algorithmic cryptocurrency trading platform. Binance Futures
first; a quantitative **research and backtesting engine comes before any execution
platform** — see `docs/ARCHITECTURE.md` Revision 2 for why.

**Status: Part A (Research & Backtesting Engine) implemented.** Part B (live/paper
execution, API, dashboard) has not been started — see `TASKS.md` for the phase gate.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design,
[`TASKS.md`](TASKS.md) for the milestone-by-milestone plan and current status,
[`docs/VALIDATION_REPORT.md`](docs/VALIDATION_REPORT.md) for the pre-Part-B
correctness audit (backtesting logic, data handling, execution simulation, risk
calculations, statistical methodology — what was found, fixed, verified, and what
still remains an open assumption or limitation),
[`docs/BACKTRADER_COMPARISON.md`](docs/BACKTRADER_COMPARISON.md) for an external
cross-validation of the backtest engine against Backtrader, an established
backtesting library, and
[`docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md`](docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md)
for the platform's first production strategy — a research review, mathematical
specification, and research report for a falsifiable liquidity-sweep-and-reclaim
reversal hypothesis, deliberately written to translate ambiguous "Smart Money
Concepts" jargon into precise, testable, market-microstructure-grounded rules.

[`docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md`](docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md)
is a full long-horizon research pipeline (data quality gating, regime analysis,
rolling out-of-sample validation, Monte Carlo, ±10% parameter-robustness sweeps,
sample-size and R-multiple-distribution reporting, a pre-registered scientific
decision rule) run against **synthetic** BTCUSDT/ETHUSDT history — `fapi.binance.com`
is blocked by this sandbox's network policy (confirmed directly, see that report's
§0), so the pipeline itself was built and validated end-to-end instead of stalling
or fabricating a real result. See [`docs/DATA_LAYER.md`](docs/DATA_LAYER.md) for the
full Binance data layer (OHLCV, funding, mark price, premium index, open interest,
exchange info — every endpoint the strategy needs, with documented history-depth
limits), its never-hardcode-a-date-range earliest-detection mechanism, and
`scripts/sync_historical_data.py`'s production incremental sync. Both
`scripts/sync_historical_data.py` and `scripts/run_research_pipeline.py` (via
`--data-source real`) need zero code changes to run for real the moment network
access exists — `research/data_loader.py` is the single real/synthetic switch.

## Quickstart (research engine)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Download Binance Futures historical data into the local Parquet store
python scripts/download_historical_data.py --symbol BTC/USDT --timeframe 1h \
    --start 2023-01-01 --end 2024-01-01
python scripts/download_historical_data.py --symbol BTC/USDT \
    --start 2023-01-01 --end 2024-01-01 --dataset funding_rate

# Or sync the FULL data layer (candles across every timeframe, funding, mark
# price, premium index, open interest) with no hardcoded date range —
# auto-detects each symbol's real earliest available data, incremental and
# resumable on rerun. See docs/DATA_LAYER.md.
python -m scripts.sync_historical_data --symbols BTCUSDT ETHUSDT

# Run a backtest
python scripts/run_backtest.py --strategy ma_crossover --symbol BTC/USDT \
    --timeframe 1h --start 2023-01-01 --end 2024-01-01 \
    --params '{"fast_period": 10, "slow_period": 30}' \
    --journal-csv journal.csv

# Or the first production strategy (see docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md)
python scripts/run_backtest.py --strategy liquidity_exhaustion_reversal \
    --symbol BTC/USDT --timeframe 1h --start 2023-01-01 --end 2024-01-01 \
    --journal-csv journal.csv

make test   # 362 tests
make lint   # ruff + black --check
make typecheck  # mypy

# Optional: cross-validate against Backtrader (an established backtesting library)
pip install -e ".[validation]"
pytest tests/integration/test_backtrader_comparison.py -v

# Long-horizon research pipeline. --data-source defaults to "auto" (real data
# first, synthetic fallback if unreachable, as in this sandbox); use "real" to
# fail loudly instead of falling back, or "synthetic" for methodology testing.
python -m scripts.run_research_pipeline
python -m scripts.run_research_pipeline --data-source real
```

Three strategies ship out of the box: `ma_crossover` and `mean_reversion`
(simple examples, see `strategies/examples/`), and `liquidity_exhaustion_reversal`
(the first production strategy — a falsifiable liquidity-sweep-and-reclaim
reversal hypothesis, see `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md`). All
three implement the full `Strategy` interface (`detect_setup` / `check_entry` /
`check_exit` / `stop_loss` / `take_profit` / `position_size`) and are fully
interchangeable in the backtesting engine.

**Not yet run against real Binance data** — this development environment has no
outbound network access to Binance's API (confirmed directly, see
`docs/DATA_LAYER.md`). The full data layer and pipeline are built and validated
end-to-end against mocked/synthetic data shaped like a real download (see
`TASKS.md` Phases A15/A18). Run the quickstart above from an environment with
network access — `sync_historical_data.py` and `run_research_pipeline.py
--data-source real` need no code changes — to get the real, definitive
validation.

**Database persistence not yet implemented** (`TASKS.md` Phase A4/A5) — there was no
Postgres available to test against in this environment. Everything through Phase A14
runs without a database; backtest/journal output currently lives in Parquet/CSV
files.
