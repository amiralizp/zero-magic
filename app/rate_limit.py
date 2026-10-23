"""Sliding-window rate limiting, kept in memory for weeks 1-3.

A production deployment (week 7+) moves this to Redis so every worker sees the
same counters. The interface is deliberately tiny: ``hit`` returns ``None`` if
the call is allowed, or the number of seconds to wait.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, *, now: float | None = None) -> float | None:
        moment = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            cutoff = moment - self.window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, self.window - (moment - hits[0]))
            hits.append(moment)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
