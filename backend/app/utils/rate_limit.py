"""A small in-process sliding-window rate limiter (fine for a single instance)."""

import time
from collections import deque


class SlidingWindowLimiter:
    """Counts events per key inside a time window. Memory is bounded: expired keys are pruned,
    and if an attacker floods with unique keys the oldest ones are dropped."""

    def __init__(self, limit: int, window_seconds: int, max_keys: int = 10_000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}

    def _prune(self, now: float) -> None:
        if len(self._events) <= self.max_keys:
            return
        for key in [k for k, q in self._events.items() if not q or now - q[-1] > self.window]:
            del self._events[key]
        if len(self._events) > self.max_keys:  # still flooded: drop the oldest tenth
            oldest = sorted(self._events, key=lambda k: self._events[k][-1])[: self.max_keys // 10]
            for key in oldest:
                del self._events[key]

    def retry_after_minutes(self, key: str) -> int | None:
        """Minutes until the key may try again, or None if it is under the limit."""
        now = time.time()
        events = self._events.get(key)
        if not events:
            return None
        while events and now - events[0] > self.window:
            events.popleft()
        if len(events) >= self.limit:
            return int(self.window - (now - events[0])) // 60 + 1
        return None

    def hit(self, key: str) -> None:
        now = time.time()
        self._prune(now)
        self._events.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        self._events.pop(key, None)
