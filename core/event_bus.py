"""In-process, synchronous event bus.

The backtesting engine replays thousands of bars deterministically and
sequentially — a synchronous observer-pattern bus is simpler, faster, and just as
deterministic as an asyncio-based one for that workload, so that's what this
implementation is. A Redis-backed, async implementation for live multi-process
fan-out is a Part B concern (see docs/ARCHITECTURE.md) and will share this same
`EventBus` protocol.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from core.events import Event

E = TypeVar("E", bound=Event)
Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]

    def publish(self, event: Event) -> None:
        for event_type, handlers in self._handlers.items():
            if isinstance(event, event_type):
                for handler in handlers:
                    handler(event)

    def clear(self) -> None:
        self._handlers.clear()
