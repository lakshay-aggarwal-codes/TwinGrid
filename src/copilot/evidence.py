"""Evidence items: what an answer may cite. Built only from tool output; never from the question or the history."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable

SOURCES = (
    "alert_explanation",
    "twin_state",
    "threshold_rule",
    "model_passport",
    "claims_ledger",
    "capability_catalogue",
)
ORIGINS = ("simulated", "measured", "replayed", "assumed", "documentation", "unknown")
FRESHNESS = ("fresh", "stale", "unavailable", "static")
MAX_ITEMS = 24
MAX_TEXT = 200

_ORIGIN_MAP = {
    "simulated": "simulated",
    "simulation": "simulated",
    "measured": "measured",
    "replay": "replayed",
    "replayed": "replayed",
    "assumed": "assumed",
}
MARKER = re.compile(r"\[E\d+\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def origin_from_record(raw: Any) -> str:
    """The data origin a stored record declares; anything not recognised is ``unknown`` (never guessed ``simulated``)."""
    return _ORIGIN_MAP.get(str(raw).strip().lower(), "unknown") if raw is not None else "unknown"


def iso_utc(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:  # the database stores UTC; a naive value is read as UTC, as the rest of the API does
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_seconds(observed_at: datetime | None, now: datetime) -> float | None:
    if observed_at is None:
        return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return (now - observed_at).total_seconds()


def freshness_of(observed_at: datetime | None, now: datetime, stale_after_s: int) -> str:
    """``unavailable`` without a timestamp, ``stale`` once older than ``stale_after_s`` (or dated in the future)."""
    age = age_seconds(observed_at, now)
    if age is None:
        return "unavailable"
    return "fresh" if 0 <= age <= stale_after_s else "stale"


def clean_text(text: Any, limit: int = MAX_TEXT) -> str:
    """Data text made safe to quote: one line, no control characters, no ``[E#]``-lookalike brackets, bounded."""
    out = re.sub(r"\s+", " ", "".join(ch if ch.isprintable() else " " for ch in str(text))).strip()
    out = out.replace("[", "(").replace("]", ")")
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "\u2026"


class EvidenceBook:
    """Collects evidence items and hands out their ids (``E1``, ``E2``, ...) in the order they were added."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def add(
        self,
        *,
        source: str,
        entity: str,
        field: str,
        value: Any,
        origin: str,
        freshness: str,
        unit: str | None = None,
        observed_at: str | None = None,
    ) -> str:
        if source not in SOURCES or origin not in ORIGINS or freshness not in FRESHNESS:
            raise ValueError(f"unknown evidence source/origin/freshness: {source!r}/{origin!r}/{freshness!r}")
        if len(self._items) >= MAX_ITEMS:
            raise ValueError("too many evidence items")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("evidence values must be finite")
        if value is not None and not isinstance(value, (bool, int, float, str)):
            raise ValueError("evidence values are scalars")
        if isinstance(value, str):
            value = clean_text(value)
        item = {
            "id": f"E{len(self._items) + 1}",
            "source": source,
            "entity": clean_text(entity, 80),
            "field": clean_text(field, 80),
            "value": value,
            "unit": unit,
            "observed_at": observed_at,
            "origin": origin,
            "freshness": freshness,
        }
        self._items.append(item)
        return item["id"]

    def items(self) -> list[dict[str, Any]]:
        return [dict(i) for i in self._items]


def _tokens(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def unbacked_numbers(answer: str, evidence: Iterable[dict[str, Any]]) -> list[str]:
    """Numeric literals in ``answer`` (outside ``[E#]`` markers) that no evidence item carries. Empty means every number
    in the text is backed. Templates contain no digits, so anything found here came from data (an entity id or quoted
    text), and those are evidence values/entities too."""
    allowed: set[str] = set()
    for item in evidence:
        allowed |= _tokens(str(item.get("entity", "")))
        value = item.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed |= _tokens(f"{value}") | _tokens(f"{value:g}") | _tokens(f"{value:.4g}")
        elif isinstance(value, str):
            allowed |= _tokens(value)
    return sorted(t for t in _tokens(MARKER.sub(" ", answer)) if t not in allowed)
