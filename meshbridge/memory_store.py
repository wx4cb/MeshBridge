"""Small bounded runtime stores."""

from __future__ import annotations

from collections import deque


class UnhandledEventStore:
    """Bounded store of recently observed unhandled events."""

    def __init__(self, max_events: int) -> None:
        self._events: deque[tuple[int, str, str]] = deque(maxlen=max_events)

    def add(self, when: int, event_type: str, preview: str) -> None:
        """Store one unhandled event preview."""
        self._events.append((when, event_type, preview))

    def recent(self) -> list[tuple[int, str, str]]:
        """Return recent events newest-first."""
        return list(reversed(self._events))
