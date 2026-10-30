"""Client-side request limiter for the Copilot providers (CP-4).

Sliding windows (60 s and 24 h), one pair per provider key, in this process only, guarded by a lock. Pure Python, no
network, no import of ``llm.py``. A refused request is not recorded; an allowed one is recorded when it is allowed
(a provider that answers 429 still used a request).

The limiter exists so we stop before a provider rejects us. It never rotates accounts or keys: limits belong to the
account at the provider, and one provider means one key (contract rule 5).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

MINUTE_S = 60.0
DAY_S = 86400.0


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._minute: dict[str, deque[float]] = {}
        self._day: dict[str, deque[float]] = {}

    def reset(self) -> None:
        with self._lock:
            self._minute.clear()
            self._day.clear()

    def snapshot(self) -> dict[str, dict[str, int]]:
        now = self._clock()
        with self._lock:
            return {
                k: {
                    "last_minute": sum(1 for t in self._minute.get(k, ()) if t > now - MINUTE_S),
                    "last_day": sum(1 for t in d if t > now - DAY_S),
                }
                for k, d in self._day.items()
            }

    def try_acquire(self, key: str, rpm: int, rpd: int) -> float:
        """Return 0.0 and record the request, or the seconds to wait (> 0) and record nothing. ``0`` disables a limit."""
        if rpm <= 0 and rpd <= 0:
            return 0.0
        now = self._clock()
        with self._lock:
            minute = self._minute.setdefault(key, deque())
            day = self._day.setdefault(key, deque())
            while minute and minute[0] <= now - MINUTE_S:
                minute.popleft()
            while day and day[0] <= now - DAY_S:
                day.popleft()
            wait = 0.0
            if rpm > 0 and len(minute) >= rpm:
                wait = max(wait, minute[0] + MINUTE_S - now)
            if rpd > 0 and len(day) >= rpd:
                wait = max(wait, day[0] + DAY_S - now)
            if wait > 0:
                return max(wait, 0.001)
            minute.append(now)
            day.append(now)
            return 0.0


LIMITER = RateLimiter()


def reset() -> None:
    LIMITER.reset()


__all__ = ["LIMITER", "RateLimiter", "reset"]
