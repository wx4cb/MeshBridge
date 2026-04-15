"""Bounded in-memory message history."""

from __future__ import annotations

from collections import deque

from meshbridge.models import BridgeMessage


class MessageHistory:
    """Bounded rolling history of recent bridge messages."""

    def __init__(self, max_messages: int) -> None:
        self._messages: deque[BridgeMessage] = deque(maxlen=max_messages)

    def add(self, msg: BridgeMessage) -> None:
        """Add one message to history."""
        self._messages.append(msg)

    def recent(self) -> list[BridgeMessage]:
        """Return recent messages newest-first."""
        return list(reversed(self._messages))
