"""Small bounded runtime stores."""

from __future__ import annotations

from collections import deque
from itertools import islice


class UnhandledEventStore:
    """Bounded store of recently observed unhandled events."""

    def __init__(self, max_events: int) -> None:
        self._events: deque[tuple[int, str, str]] = deque(maxlen=max_events)

    def add(self, when: int, event_type: str, preview: str) -> None:
        """Store one unhandled event preview."""
        self._events.append((when, event_type, preview))

    def __len__(self) -> int:
        """Return the number of buffered events."""
        return len(self._events)

    def recent(self, limit: int | None = None) -> list[tuple[int, str, str]]:
        """Return recent events newest-first."""
        items = reversed(self._events)
        if limit is None:
            return list(items)
        return list(islice(items, limit))
