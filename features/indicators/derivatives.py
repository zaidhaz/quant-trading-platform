import pandas as pd


def funding_rate(funding_df: pd.DataFrame, candle_index: pd.DatetimeIndex) -> pd.Series:
    """Align the (sparser, ~8h-spaced) funding rate series onto a candle index by
    forward-filling the most recent known rate — the rate in effect at each candle."""
    if funding_df.empty:
        return pd.Series(index=candle_index, dtype=float)
    aligned = funding_df["funding_rate"].reindex(funding_df.index.union(candle_index)).ffill()
    return aligned.reindex(candle_index)


def open_interest(*_args: object, **_kwargs: object) -> pd.Series:
    """Placeholder — no open-interest dataset exists yet (see market_data/historical/
    and docs/ARCHITECTURE.md §20). Adding `OpenInterestDataset` there is all that's
    needed before implementing this for real; nothing else in the feature engine
    changes."""
    raise NotImplementedError(
        "open_interest feature requires an OpenInterestDataset — not yet implemented "
        "(Part C roadmap)"
    )
