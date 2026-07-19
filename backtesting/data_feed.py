from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.exceptions import DataGapError
from core.types import Symbol
from features.indicators import derivatives
from market_data.historical.candles_dataset import CandlesDataset
from market_data.historical.funding_rate_dataset import FundingRateDataset
from market_data.historical.validation import validate_candles

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DataFeed:
    symbol: Symbol
    timeframe: str
    candles: pd.DataFrame
    funding_rate: pd.Series
    """Forward-filled onto every candle — "the funding rate currently in effect",
    usable as a feature by strategies."""
    funding_events: pd.Series
    """NaN except on bars that exactly coincide with a real funding timestamp — this
    is what the backtest engine uses to decide *when* to actually charge funding,
    since forward-filled `funding_rate` repeats across many bars."""

    def __len__(self) -> int:
        return len(self.candles)

    @classmethod
    def from_candles(
        cls,
        symbol: Symbol,
        timeframe: str,
        candles: pd.DataFrame,
        funding_df: pd.DataFrame | None = None,
    ) -> DataFeed:
        validate_candles(candles, context=f"candles for {symbol} [{timeframe}]")
        funding_df = (
            funding_df if funding_df is not None else pd.DataFrame(columns=["funding_rate"])
        )
        funding_rate = derivatives.funding_rate(funding_df, candles.index)
        funding_events = (
            funding_df["funding_rate"].reindex(candles.index)
            if not funding_df.empty
            else pd.Series(index=candles.index, dtype=float)
        )
        return cls(symbol, timeframe, candles, funding_rate, funding_events)

    @classmethod
    def load(
        cls,
        symbol: Symbol,
        timeframe: str,
        start: datetime,
        end: datetime,
        candles_dataset: CandlesDataset,
        funding_dataset: FundingRateDataset | None = None,
    ) -> DataFeed:
        # Candle gaps are a hard failure: a backtest on fundamentally incomplete
        # price data is not trustworthy, so this is *not* wrapped — let
        # DataGapError propagate.
        candles = candles_dataset.ensure_range(symbol, start, end, timeframe)

        funding_df = None
        if funding_dataset is not None:
            try:
                funding_df = funding_dataset.ensure_range(symbol, start, end)
            except DataGapError as exc:
                # Funding is enrichment, not core price data: missing funding
                # history degrades cost accuracy for the affected periods (they'll
                # be treated as zero funding) rather than blocking the backtest —
                # but that degradation must be visible, not silent.
                logger.warning(
                    "Funding rate data incomplete for %s, proceeding with partial "
                    "funding history (missing periods treated as zero funding cost): %s",
                    symbol,
                    exc,
                )
                funding_df = funding_dataset.ensure_range(symbol, start, end, allow_gaps=True)
        return cls.from_candles(symbol, timeframe, candles, funding_df)
