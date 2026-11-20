"""Small in-process sliding-window rate limiter (no Redis by design at pilot scale).

Limits are per API instance. With N instances the effective limit is up to N times higher; the AWS
deployment adds a WAF rate rule in front of the load balancer for a global limit (Phase 7).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events, self.window = max_events, window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Record one event. Returns None if allowed, otherwise seconds until the next slot frees up."""
        t = time.monotonic() if now is None else now
        with self._lock:
            events = self._events[key]
            while events and t - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.max_events:
                return self.window - (t - events[0])
            events.append(t)
            return None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


# 10 login attempts per 5 minutes per (email, client address); successful logins count too.
login_limiter = SlidingWindowLimiter(max_events=10, window_seconds=300)
