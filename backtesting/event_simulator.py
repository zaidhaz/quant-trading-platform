from backtesting.data_feed import DataFeed
from core.event_bus import EventBus
from core.events import CandleEvent


class EventSimulator:
    """Deterministic, time-ordered replay: publishes one CandleEvent per bar, in
    order, onto the event bus. `engine.py` subscribes to do the actual work — the
    simulator itself has no strategy/risk/portfolio knowledge, matching the same
    "publish onto a bus, consumers subscribe" shape live market data will use in
    Part B (see docs/ARCHITECTURE.md)."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    def run(self, feed: DataFeed) -> None:
        for i in range(len(feed.candles)):
            row = feed.candles.iloc[i]
            self.bus.publish(
                CandleEvent(
                    ts=row.name.to_pydatetime(),
                    symbol=feed.symbol,
                    timeframe=feed.timeframe,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    bar_index=i,
                )
            )
