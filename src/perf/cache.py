"""Short-TTL response cache with generation-based invalidation. Synchronous, JSON values only, fail-open.

* Backend is anything with ``mget(keys)``, ``set(key, value, ttl_ms)`` and ``incr(key)`` (``RedisBackend`` below; tests
  use a dict).  Values are JSON, never pickles, so a compromised Redis cannot feed code to the API.
* One entry stores the namespace *generation* it was written under; ``invalidate(ns)`` bumps the generation, so every
  older entry of that namespace is ignored at once (and expires by TTL).  A lookup is a single ``MGET``.
* Fail-open: any backend error computes the value directly.  After ``failure_limit`` consecutive errors the cache is
  bypassed for ``pause_s`` seconds, so a dead Redis costs at most a few short timeouts, then nothing.
* An exception raised by ``compute`` propagates and is never cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    bypassed: int = 0
    errors: int = 0


class RedisBackend:
    """Thin sync wrapper; the ``redis`` package is imported on first use only."""

    def __init__(self, url: str, timeout_s: float = 0.05) -> None:
        self._url = url
        self._timeout = timeout_s
        self._client: Any = None

    def _c(self) -> Any:
        if self._client is None:
            from redis import Redis

            self._client = Redis.from_url(
                self._url, socket_connect_timeout=self._timeout, socket_timeout=self._timeout, decode_responses=True
            )
        return self._client

    def mget(self, keys: list[str]) -> list[str | None]:
        return self._c().mget(keys)

    def set(self, key: str, value: str, ttl_ms: int) -> None:
        self._c().set(key, value, px=ttl_ms)

    def incr(self, key: str) -> int:
        return int(self._c().incr(key))


class ResponseCache:
    def __init__(
        self,
        backend: Any,
        *,
        prefix: str = "tg:perf:",
        clock: Callable[[], float] = time.monotonic,
        failure_limit: int = 3,
        pause_s: float = 10.0,
    ) -> None:
        self._b = backend
        self._prefix = prefix
        self._clock = clock
        self._limit = failure_limit
        self._pause = pause_s
        self._failures = 0
        self._paused_until = 0.0
        self.stats = CacheStats()

    def _fail(self, what: str) -> None:
        self.stats.errors += 1
        self._failures += 1
        if self._failures >= self._limit:
            self._paused_until = self._clock() + self._pause
            self._failures = 0
            logger.warning("perf cache: backend unavailable (%s); bypassing for %.0f s", what, self._pause)

    def get_or_compute(self, namespace: str, parts: Any, ttl_s: float, compute: Callable[[], Any]) -> Any:
        if self._clock() < self._paused_until:
            self.stats.bypassed += 1
            return compute()
        digest = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:32]
        vkey, gkey = f"{self._prefix}v:{namespace}:{digest}", f"{self._prefix}g:{namespace}"
        try:
            raw, gen_raw = self._b.mget([vkey, gkey])
            self._failures = 0
        except Exception as exc:  # noqa: BLE001 - fail open on any backend problem
            self._fail(type(exc).__name__)
            return compute()
        gen = int(gen_raw or 0)
        if raw:
            try:
                rec = json.loads(raw)
                if rec["g"] == gen:
                    self.stats.hits += 1
                    return rec["v"]
            except (ValueError, KeyError, TypeError):
                pass  # unreadable entry: recompute and overwrite
        self.stats.misses += 1
        value = compute()
        try:
            payload = json.dumps({"g": gen, "v": value}, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return value  # not plain JSON: serve it uncached
        try:
            self._b.set(vkey, payload, max(1, int(ttl_s * 1000)))
        except Exception as exc:  # noqa: BLE001
            self._fail(type(exc).__name__)
        return value

    def invalidate(self, namespace: str) -> bool:
        """Make every cached entry of ``namespace`` unreadable now. False if the backend could not be reached."""
        try:
            self._b.incr(f"{self._prefix}g:{namespace}")
            return True
        except Exception as exc:  # noqa: BLE001
            self._fail(type(exc).__name__)
            return False
