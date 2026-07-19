from datetime import UTC, datetime

from core.enums import OrderSide
from core.event_bus import EventBus
from core.events import CandleEvent, Event, FillEvent, SignalEvent
from core.types import Symbol

SYMBOL = Symbol(base="BTC", quote="USDT")


def make_candle(bar_index: int = 0) -> CandleEvent:
    return CandleEvent(
        ts=datetime(2024, 1, 1, tzinfo=UTC),
        symbol=SYMBOL,
        timeframe="1h",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
        bar_index=bar_index,
    )


def test_subscriber_receives_matching_event_type() -> None:
    bus = EventBus()
    received: list[CandleEvent] = []
    bus.subscribe(CandleEvent, received.append)

    bus.publish(make_candle())

    assert len(received) == 1
    assert received[0].symbol == SYMBOL


def test_subscriber_does_not_receive_other_event_types() -> None:
    bus = EventBus()
    received: list[SignalEvent] = []
    bus.subscribe(SignalEvent, received.append)

    bus.publish(make_candle())

    assert received == []


def test_multiple_subscribers_all_receive_event_in_order() -> None:
    bus = EventBus()
    order: list[str] = []
    bus.subscribe(CandleEvent, lambda _e: order.append("first"))
    bus.subscribe(CandleEvent, lambda _e: order.append("second"))

    bus.publish(make_candle())

    assert order == ["first", "second"]


def test_base_class_subscriber_receives_all_event_subtypes() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(Event, received.append)

    bus.publish(make_candle())
    bus.publish(
        FillEvent(
            ts=datetime(2024, 1, 1, tzinfo=UTC),
            symbol=SYMBOL,
            strategy_id="s1",
            order_id="o1",
            side=OrderSide.BUY,
            quantity=1.0,
            price=100.0,
            fee=0.04,
        )
    )

    assert len(received) == 2


def test_correlation_id_defaults_to_own_event_id() -> None:
    candle = make_candle()
    assert candle.correlation_id == candle.event_id


def test_clear_removes_all_subscribers() -> None:
    bus = EventBus()
    received: list[CandleEvent] = []
    bus.subscribe(CandleEvent, received.append)
    bus.clear()

    bus.publish(make_candle())

    assert received == []
