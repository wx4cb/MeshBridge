"""Bounded in-memory message history."""

from __future__ import annotations

from collections import deque
from itertools import islice

from meshbridge.models import BridgeMessage


class MessageHistory:
    """Bounded rolling history of recent bridge messages."""

    def __init__(self, max_messages: int) -> None:
        self._messages: deque[BridgeMessage] = deque(maxlen=max_messages)

    def add(self, msg: BridgeMessage) -> None:
        """Add one message to history."""
        self._messages.append(msg)

    def __len__(self) -> int:
        """Return the number of buffered messages."""
        return len(self._messages)

    def recent(self, limit: int | None = None) -> list[BridgeMessage]:
        """Return recent messages newest-first."""
        items = reversed(self._messages)
        if limit is None:
            return list(items)
        return list(islice(items, limit))
