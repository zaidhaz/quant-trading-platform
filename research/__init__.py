"""Long-horizon research pipeline for validating (not optimizing) the
Liquidity Exhaustion Reversal System across the longest available history.

**Everything in this package that touches price/funding data operates on
SYNTHETIC data**, because this sandbox has no outbound network route to
`fapi.binance.com` (verified directly — see
`docs/research/LIQUIDITY_EXHAUSTION_REVERSAL_LONG_HORIZON_REPORT.md` §0 for
the exact error). The platform's real Binance downloader
(`market_data/historical/binance_client.py`) is untouched and will work the
moment network access exists — this package exists so the analysis
*methodology* (data quality checks, regime segmentation, rolling
out-of-sample validation, Monte Carlo, parameter-robustness sweeps, report
generation) is built and tested now, ready to run for real without changes,
rather than the whole exercise waiting on infrastructure.

No function in this package is allowed to silently blur that line: every
dataset it produces is loaded from `research/synthetic_history.py`, never
`market_data/historical/`, and every report it generates says so explicitly.
"""
