"""Liquidity Exhaustion Reversal System ("Sweep & Reclaim at Value").

Pure, deterministic, unit-testable primitives (`structure.py`,
`microstructure.py`), a fully configurable parameter set (`config.py`), and
registration of everything as `FeatureEngine` indicators (`indicators.py`) so
the strategy class in `strategies/examples/liquidity_exhaustion_reversal.py`
reads them exactly like any built-in indicator.

See `docs/strategies/LIQUIDITY_EXHAUSTION_REVERSAL.md` for the research
review and mathematical definitions behind every function in this package.
"""
