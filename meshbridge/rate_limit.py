"""Simple per-route rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Per-key sliding-window rate limiter."""

    def __init__(self, window_seconds: int, max_events: int) -> None:
        self.window_seconds = window_seconds
        self.max_events = max_events
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Return True if another event is allowed for the key."""
        now = time.time()
        bucket = self._buckets[key]
        cutoff = now - self.window_seconds

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_events:
            return False

        bucket.append(now)
        return True
