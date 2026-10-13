"""Login lockout with exponential backoff (Task 6), on top of the existing 10/minute per-IP limit.

Key: HMAC(per-process random salt, client IP + normalised username). The attempted username is never stored in
clear (people paste passwords into that field) and an attacker can only lock their OWN (ip, username) pair, never a
victim's account from elsewhere. A username that does not exist is locked exactly like one that does, so the guard
reveals nothing about accounts.

Policy (env read per call, defaults in brackets):
* ``LOGIN_LOCKOUT_THRESHOLD`` [5] consecutive failures before the first lock;
* ``LOGIN_LOCKOUT_BASE_SECONDS`` [30] first lock, doubling with each further failure up to
  ``LOGIN_LOCKOUT_MAX_SECONDS`` [900];
* failures are forgotten after ``LOGIN_LOCKOUT_RESET_SECONDS`` [900] without one; a success clears the key;
* ``LOGIN_LOCKOUT_ENABLED``: unset/``auto`` (default) = active whenever the shared request limiter is active (so the
  existing ``limiter.enabled`` rollback/test switch covers it too); ``true`` = always on; ``false`` = off.

Process-local memory, like the request-rate windows in api/rate_limit.py (several workers = several counters).
Pure logic; the ASGI wiring is in api/plugins/login_lockout.py.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass

_SALT = secrets.token_bytes(16)
_MAX_ENTRIES = 10_000

now = time.monotonic  # indirection so tests control the clock


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def mode() -> str:
    """``"on"``, ``"off"`` or ``"auto"`` (follow the shared limiter's switch)."""
    raw = os.getenv("LOGIN_LOCKOUT_ENABLED", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw in {"0", "false", "no", "off"}:
        return "off"
    return "auto"


def active(limiter_enabled: bool) -> bool:
    current = mode()
    return current == "on" or (current == "auto" and limiter_enabled)


@dataclass
class _Entry:
    failures: int = 0
    last_failure: float = 0.0
    locked_until: float = 0.0


_lock = threading.Lock()
_entries: dict[str, _Entry] = {}


def reset() -> None:
    with _lock:
        _entries.clear()


def make_key(ip: str, username: str) -> str:
    material = f"{ip}\x00{username.strip().lower()}".encode("utf-8", "replace")
    return hmac.new(_SALT, material, hashlib.sha256).hexdigest()


def _forget_stale(t: float) -> None:
    horizon = _env_int("LOGIN_LOCKOUT_RESET_SECONDS", 900)
    for key in [k for k, e in _entries.items() if t - e.last_failure > horizon and e.locked_until <= t]:
        del _entries[key]


def retry_after(key: str) -> int | None:
    """Whole seconds the caller must wait, or None when attempts are allowed."""
    t = now()
    with _lock:
        entry = _entries.get(key)
        if entry is None or entry.locked_until <= t:
            return None
        return max(1, int(entry.locked_until - t + 0.999))


def record_failure(key: str) -> None:
    t = now()
    threshold = _env_int("LOGIN_LOCKOUT_THRESHOLD", 5)
    base = _env_int("LOGIN_LOCKOUT_BASE_SECONDS", 30)
    cap = _env_int("LOGIN_LOCKOUT_MAX_SECONDS", 900)
    horizon = _env_int("LOGIN_LOCKOUT_RESET_SECONDS", 900)
    with _lock:
        if len(_entries) >= _MAX_ENTRIES:
            _forget_stale(t)
            if len(_entries) >= _MAX_ENTRIES:
                _entries.pop(next(iter(_entries)))  # oldest insertion: bounded memory beats perfect memory
        entry = _entries.setdefault(key, _Entry())
        if entry.failures and t - entry.last_failure > horizon:
            entry.failures = 0
        entry.failures += 1
        entry.last_failure = t
        if entry.failures >= threshold:
            entry.locked_until = t + min(base * 2 ** (entry.failures - threshold), cap)


def record_success(key: str) -> None:
    with _lock:
        _entries.pop(key, None)
