# Quant Trading Platform

Institutional-grade algorithmic cryptocurrency trading platform. Binance Futures
first; a quantitative **research and backtesting engine comes before any execution
platform** — see `docs/ARCHITECTURE.md` Revision 2 for why.

**Status: Part A (Research & Backtesting Engine) implemented.** Part B (live/paper
execution, API, dashboard) has not been started — see `TASKS.md` for the phase gate.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and
[`TASKS.md`](TASKS.md) for the milestone-by-milestone plan and current status.

## Quickstart (research engine)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Download Binance Futures historical data into the local Parquet store
python scripts/download_historical_data.py --symbol BTC/USDT --timeframe 1h \
    --start 2023-01-01 --end 2024-01-01
python scripts/download_historical_data.py --symbol BTC/USDT \
    --start 2023-01-01 --end 2024-01-01 --dataset funding_rate

# Run a backtest
python scripts/run_backtest.py --strategy ma_crossover --symbol BTC/USDT \
    --timeframe 1h --start 2023-01-01 --end 2024-01-01 \
    --params '{"fast_period": 10, "slow_period": 30}' \
    --journal-csv journal.csv

make test   # 158 unit tests
make lint   # ruff + black --check
make typecheck  # mypy
```

Two example strategies ship out of the box: `ma_crossover` and `mean_reversion`
(see `strategies/examples/`). Both implement the full `Strategy` interface
(`detect_setup` / `check_entry` / `check_exit` / `stop_loss` / `take_profit` /
`position_size`) and are fully interchangeable in the backtesting engine.

**Not yet run against real Binance data** — this development environment has no
outbound network access to Binance's API. The pipeline has been validated
end-to-end against synthetic data shaped like a real download (see
`TASKS.md` Phase A15). Run the quickstart above from an environment with network
access to get a real validation.

**Database persistence not yet implemented** (`TASKS.md` Phase A4/A5) — there was no
Postgres available to test against in this environment. Everything through Phase A14
runs without a database; backtest/journal output currently lives in Parquet/CSV
files.
