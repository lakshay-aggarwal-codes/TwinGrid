"""Copilot failover router (CP-2).

Tries the configured providers in order and moves on when one is exhausted or failing. Pure Python: no FastAPI, no
database, no network, and no import of ``llm.py`` (``llm.enhance`` hands in the function that makes one attempt). State
(cooldowns, disabled providers) lives in this process only and is guarded by a lock.

Rules
-----
* An attempt either returns a value or raises :class:`Failure`. Any other exception is treated as a transient failure
  (``unexpected_<type>``), so nothing raised by a provider can escape :meth:`Router.route`.
* ``quota`` (HTTP 429) and ``transient`` (5xx, timeout, network, bad envelope, bad JSON, too large, other 4xx) start a
  cooldown: ``base * 2**(n-1)`` seconds for the n-th consecutive failure (quota base 60 s, transient base 30 s, capped at
  900 s). A ``Retry-After`` the provider sent is respected if it is longer (capped at 3600 s). A success resets ``n``.
* ``auth`` (HTTP 401/403) disables the provider for the life of the process and logs once.
* ``rejected`` (the answer failed the rule checks) is NOT an availability problem: no cooldown. It does use up the
  rejection allowance: after the first rejection exactly one more provider is tried, then the chain stops.
* The whole chain shares one time budget. Each attempt gets ``min(provider timeout, time left)``.
* A chain with a single provider keeps no state (Task 24 behaviour; nothing to fail over to, and tests stay isolated).

Logging: provider name and our own outcome words only. Never a prompt, an answer, a question, telemetry or a key.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, Sequence, TypeVar

logger = logging.getLogger(__name__)

KIND_QUOTA = "quota"
KIND_TRANSIENT = "transient"
KIND_AUTH = "auth"
KIND_REJECTED = "rejected"

DEFAULT_BUDGET_S = 12.0
MIN_ATTEMPT_S = 0.25  # less than this left in the budget: do not start another attempt
QUOTA_BASE_S = 60.0
TRANSIENT_BASE_S = 30.0
MAX_BACKOFF_S = 900.0
MAX_RETRY_AFTER_S = 3600.0
REJECTION_RETRIES = 1  # providers tried after the first rejected answer

S = TypeVar("S")
T = TypeVar("T")


class Failure(Exception):
    """One failed attempt. ``code`` is our own outcome word (the only thing logged); ``kind`` drives the state."""

    def __init__(self, kind: str, code: str, *, retry_after: float | None = None):
        super().__init__(code)
        self.kind = kind
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True)
class Attempt:
    provider: str
    outcome: str  # "ok", the Failure code, or a skip word: skipped_cooldown, skipped_disabled
    kind: str | None = None
    elapsed_ms: int = 0


@dataclass(frozen=True)
class RouteResult(Generic[S, T]):
    value: T | None
    provider: S | None
    attempts: tuple[Attempt, ...]
    budget_exhausted: bool = False

    @property
    def ok(self) -> bool:
        return self.provider is not None

    @property
    def rejected(self) -> bool:
        return any(a.kind == KIND_REJECTED for a in self.attempts)

    def summary(self) -> str:
        """``name:outcome`` pairs in order, e.g. ``groq:unavailable_http_429,ollama:ok``."""
        return ",".join(f"{a.provider}:{a.outcome}" for a in self.attempts) or "-"


@dataclass
class _State:
    failures: int = 0
    cooldown_until: float = 0.0
    disabled: bool = False


def budget_from_env(environ: Any = None) -> float:
    """``COPILOT_LLM_BUDGET_S`` in [0.5, 120]; anything else gives the 12 s default. Never raises."""
    import os

    from .providers import number

    env = os.environ if environ is None else environ
    return number(env.get("COPILOT_LLM_BUDGET_S"), DEFAULT_BUDGET_S, 0.5, 120.0)


def _retry_after(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_S) if seconds == seconds else 0.0  # NaN -> 0


class Router:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, _State] = {}

    # -- state -----------------------------------------------------------------------------------------------------
    def reset(self) -> None:
        with self._lock:
            self._state.clear()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Read-only view for tests and ops: key -> failures, seconds of cooldown left, disabled."""
        now = self._clock()
        with self._lock:
            return {
                k: {
                    "failures": s.failures,
                    "cooldown_left_s": round(max(0.0, s.cooldown_until - now), 3),
                    "disabled": s.disabled,
                }
                for k, s in self._state.items()
            }

    def _skip_reason(self, key: str) -> str | None:
        now = self._clock()
        with self._lock:
            s = self._state.get(key)
            if s is None:
                return None
            if s.disabled:
                return "skipped_disabled"
            if s.cooldown_until > now:
                return "skipped_cooldown"
        return None

    def _record_success(self, key: str) -> None:
        with self._lock:
            s = self._state.get(key)
            if s is not None:
                s.failures, s.cooldown_until = 0, 0.0

    def _record_failure(self, key: str, name: str, failure: Failure) -> None:
        if failure.kind == KIND_REJECTED:
            return  # the provider answered; this is about the answer, not about availability
        with self._lock:
            s = self._state.setdefault(key, _State())
            if failure.kind == KIND_AUTH:
                first = not s.disabled
                s.disabled = True
            else:
                first = False
                s.failures += 1
                base = QUOTA_BASE_S if failure.kind == KIND_QUOTA else TRANSIENT_BASE_S
                backoff = min(base * (2 ** (s.failures - 1)), MAX_BACKOFF_S)
                wait = min(max(backoff, _retry_after(failure.retry_after)), MAX_RETRY_AFTER_S)
                s.cooldown_until = self._clock() + wait
        if failure.kind == KIND_AUTH and first:
            logger.warning("copilot_llm provider=%s disabled outcome=auth_failure", name)

    # -- the chain -------------------------------------------------------------------------------------------------
    def route(
        self,
        chain: Sequence[S],
        attempt: Callable[[S, float], T],
        *,
        name: Callable[[S], str],
        key: Callable[[S], str],
        timeout: Callable[[S], float],
        budget_s: float = DEFAULT_BUDGET_S,
        stateful: bool | None = None,
    ) -> RouteResult[S, T]:
        """Run ``attempt(provider, timeout_s)`` down ``chain`` until one returns. Never raises."""
        use_state = len(chain) > 1 if stateful is None else stateful
        start = self._clock()
        attempts: list[Attempt] = []
        retries_left: int | None = None  # None until a rejection happens
        for provider in chain:
            pname = name(provider)
            if use_state:
                skip = self._skip_reason(key(provider))
                if skip:
                    attempts.append(Attempt(pname, skip))
                    continue
            remaining = budget_s - (self._clock() - start)
            if remaining < MIN_ATTEMPT_S:
                return RouteResult(None, None, tuple(attempts), budget_exhausted=True)
            t0 = self._clock()
            try:
                value = attempt(provider, min(timeout(provider), remaining))
            except Failure as failure:
                self._finish_failure(use_state, provider, pname, key, failure, attempts, t0)
                kind = failure.kind
            except Exception as exc:  # noqa: BLE001 - nothing from a provider may reach the client
                failure = Failure(KIND_TRANSIENT, f"unexpected_{type(exc).__name__}")
                self._finish_failure(use_state, provider, pname, key, failure, attempts, t0)
                kind = failure.kind
            else:
                if use_state:
                    self._record_success(key(provider))
                attempts.append(Attempt(pname, "ok", None, int((self._clock() - t0) * 1000)))
                return RouteResult(value, provider, tuple(attempts))
            if kind == KIND_REJECTED and retries_left is None:
                retries_left = REJECTION_RETRIES
            elif retries_left is not None:
                retries_left -= 1
            if retries_left is not None and retries_left <= 0:
                break
        return RouteResult(None, None, tuple(attempts))

    def _finish_failure(
        self,
        use_state: bool,
        provider: Any,
        pname: str,
        key: Callable[[Any], str],
        failure: Failure,
        attempts: list[Attempt],
        t0: float,
    ) -> None:
        if use_state:
            self._record_failure(key(provider), pname, failure)
        attempts.append(Attempt(pname, failure.code, failure.kind, int((self._clock() - t0) * 1000)))


ROUTER = Router()


def reset() -> None:
    """Forget every cooldown and disabled provider (tests, and an operator restart-free reset)."""
    ROUTER.reset()


__all__ = [
    "Attempt",
    "Failure",
    "KIND_AUTH",
    "KIND_QUOTA",
    "KIND_REJECTED",
    "KIND_TRANSIENT",
    "ROUTER",
    "RouteResult",
    "Router",
    "budget_from_env",
    "reset",
]
