"""The one clock module (T12, roadmap §9.2).

Contract
--------
* Every timestamp that is persisted, or sent to a client as an instant, is
  timezone-AWARE UTC.
* ``utc_now()`` is the only wall-clock source for such timestamps. Code in
  ``api/``, ``models/`` and ``src/`` must not call ``datetime.utcnow()`` or a
  tz-less ``datetime.now()`` (enforced by ``tests/test_time_contract.py``).
* A *naive* datetime/string is ambiguous. It is only accepted when the caller
  states which zone it was written in (``source_tz``); otherwise normalisation
  raises :class:`TimeContractError`. Nothing is ever silently assumed to be
  UTC and nothing is silently replaced by "now".
* Wall-clock *display/diurnal* logic (hour-of-day) uses ``to_site_local``,
  which converts to ``SITE_TIMEZONE`` (default ``Asia/Kolkata``).

DST rules for a naive value with a ``source_tz`` (PEP 495, deterministic):
  * ambiguous time (clocks go back, the hour occurs twice) -> the FIRST
    occurrence (``fold=0``);
  * non-existent time (clocks go forward, a gap) -> interpreted with the
    offset in force BEFORE the transition (``fold=0``), i.e. it lands one
    hour later on the UTC axis than the same wall reading after the jump.
    Use :func:`is_nonexistent_local` / :func:`is_ambiguous_local` to detect
    these cases if a caller wants to reject or flag them.

This module imports nothing from ``api`` so ``src`` stays free of upward
dependencies; ``api.config`` re-exports the settings defined here.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
# Stable reference to the real class for isinstance checks. ``utc_now`` deliberately goes through the
# module-level name ``datetime`` so a test can freeze the one clock by patching ``src.timeutil.datetime``
# with a subclass without breaking the type checks below.
_DATETIME = datetime
DEFAULT_SITE_TIMEZONE = "Asia/Kolkata"


class TimeContractError(ValueError):
    """A timestamp violates the time contract (naive without a zone, unparseable, wrong type)."""


@lru_cache(maxsize=32)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise TimeContractError(f"Unknown time zone {name!r}") from exc


def _resolve_tz(tz: str | tzinfo) -> tzinfo:
    if isinstance(tz, tzinfo):
        return tz
    if isinstance(tz, str) and tz.strip():
        return _zone(tz.strip())
    raise TimeContractError(f"Invalid time zone {tz!r}")


def site_timezone_name() -> str:
    """Configured site zone name (env ``SITE_TIMEZONE``, read per call; blank -> default)."""
    raw = os.getenv("SITE_TIMEZONE")
    return raw.strip() if raw and raw.strip() else DEFAULT_SITE_TIMEZONE


def site_timezone() -> tzinfo:
    """The site ``tzinfo``. An invalid ``SITE_TIMEZONE`` raises rather than silently using UTC."""
    return _zone(site_timezone_name())


def utc_now() -> datetime:
    """Current instant as an aware UTC datetime. The only sanctioned wall-clock source."""
    return datetime.now(UTC)


def _is_aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def to_utc(dt: datetime, source_tz: str | tzinfo | None = None) -> datetime:
    """Normalise ``dt`` to aware UTC.

    * aware ``dt``: converted; ``source_tz`` is ignored (the value carries its own offset).
    * naive ``dt`` + ``source_tz``: interpreted in that zone (DST rules in the module docstring).
    * naive ``dt`` without ``source_tz``: :class:`TimeContractError`.
    """
    if not isinstance(dt, _DATETIME):
        raise TimeContractError(f"Expected datetime, got {type(dt).__name__}")
    if _is_aware(dt):
        return dt.astimezone(UTC)
    if source_tz is None:
        raise TimeContractError(
            f"Naive datetime {dt.isoformat()} has no time zone; pass source_tz or supply an offset-aware value"
        )
    return dt.replace(tzinfo=_resolve_tz(source_tz), fold=0).astimezone(UTC)


def parse_timestamp(s: Any, source_tz: str | tzinfo | None = None) -> datetime:
    """Parse an ISO-8601 string (``Z`` or ``±hh:mm`` accepted) or a datetime to aware UTC.

    Raises :class:`TimeContractError` for ``None``, empty/non-string input, unparseable text, or a
    naive value with no ``source_tz``. Never substitutes the current time.
    """
    if isinstance(s, _DATETIME):
        return to_utc(s, source_tz)
    if not isinstance(s, str):
        raise TimeContractError(f"Timestamp must be an ISO-8601 string or datetime, got {type(s).__name__}")
    text = s.strip()
    if not text:
        raise TimeContractError("Timestamp is empty")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text[-1] in "zZ" else text)
    except ValueError as exc:
        raise TimeContractError(f"Unparseable timestamp {s!r}") from exc
    return to_utc(parsed, source_tz)


def to_site_local(dt: datetime) -> datetime:
    """Convert an AWARE datetime to the site zone (naive input is a contract error)."""
    return to_utc(dt).astimezone(site_timezone())


def is_ambiguous_local(dt: datetime, tz: str | tzinfo) -> bool:
    """True if naive wall reading ``dt`` occurs twice in ``tz`` (DST fold)."""
    z = _resolve_tz(tz)
    a = dt.replace(tzinfo=z, fold=0).utcoffset()
    b = dt.replace(tzinfo=z, fold=1).utcoffset()
    return a != b and (a - b) > timedelta(0)


def is_nonexistent_local(dt: datetime, tz: str | tzinfo) -> bool:
    """True if naive wall reading ``dt`` never occurs in ``tz`` (DST gap)."""
    z = _resolve_tz(tz)
    a = dt.replace(tzinfo=z, fold=0).utcoffset()
    b = dt.replace(tzinfo=z, fold=1).utcoffset()
    return a != b and (a - b) < timedelta(0)
