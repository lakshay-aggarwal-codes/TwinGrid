"""Task 20 (ML-005): one carbon label and one claim guard.

``carbon_label`` turns a :class:`~src.carbon_provider.CarbonSignal` into the label every surface may use. It is
stricter than the legacy ``carbon_data_is_real`` flag: carbon is **real** only if a *dated* series with a documented
meaning (average or marginal) is loaded and complete. Everything else is shown as assumed.

Four statuses, each carrying ``source``, ``region``, ``timestamp``, ``unit`` and ``is_real``:

* ``real_fresh``       -- real, dated series, retrieved within the freshness window.
* ``real_stale``       -- real, dated series, older than the window (still real; the label says it is stale).
* ``unavailable``      -- no signal could be obtained (load error). Not real.
* ``assumed_fallback`` -- the flat 475 gCO2/kWh assumption, or any series that is undated, undocumented,
                          has missing hours, or carries an impossible (future) date. Not real.

``unsupported_carbon_claims`` finds claim phrases ("carbon-optimal", "saves CO2", ...) that report text must not
contain unless the label is real. Sentences that negate the claim ("No carbon reduction is claimed") are allowed.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from .carbon_provider import CarbonSignal, load_carbon_signal
from .timeutil import utc_now

CARBON_UNIT = "gCO2/kWh"

REAL_FRESH = "real_fresh"
REAL_STALE = "real_stale"
UNAVAILABLE = "unavailable"
ASSUMED_FALLBACK = "assumed_fallback"
STATUSES = (REAL_FRESH, REAL_STALE, UNAVAILABLE, ASSUMED_FALLBACK)

MAX_AGE_ENV = "CARBON_SERIES_MAX_AGE_DAYS"
DEFAULT_MAX_AGE_DAYS = 90

ASSUMED_WORD = "Assumed (flat fallback)"


def _max_age_days(explicit: Optional[int]) -> int:
    if explicit is not None:
        return int(explicit)
    try:
        value = int(os.environ.get(MAX_AGE_ENV, DEFAULT_MAX_AGE_DAYS))
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS
    return value if value > 0 else DEFAULT_MAX_AGE_DAYS


def _label(
    status: str, *, source: Optional[str], region: Optional[str], timestamp: Optional[datetime], reason: str, ui: str
) -> dict[str, Any]:
    is_real = status in (REAL_FRESH, REAL_STALE)
    return {
        "status": status,
        "is_real": is_real,
        "is_fresh": status == REAL_FRESH,
        "source": source,
        "region": region,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "unit": CARBON_UNIT,
        "ui_label": ui,
        "statement": reason,
    }


def carbon_label(
    sig: Optional[CarbonSignal], *, now: Optional[datetime] = None, max_age_days: Optional[int] = None
) -> dict[str, Any]:
    """The label for ``sig`` (``None`` = no signal could be obtained)."""
    if sig is None:
        return _label(
            UNAVAILABLE,
            source=None,
            region=None,
            timestamp=None,
            ui="Carbon unavailable",
            reason="Carbon intensity is unavailable. No carbon figure is shown and no carbon claim is made.",
        )
    region = sig.zone or ("world average" if sig.semantic == "constant_assumption" else None)

    def assumed(why: str) -> dict[str, Any]:
        return _label(
            ASSUMED_FALLBACK,
            source=sig.source_version,
            region=region,
            timestamp=sig.retrieved_at,
            ui=ASSUMED_WORD,
            reason=f"Carbon is assumed ({why}), not measured grid data. No carbon reduction is claimed.",
        )

    if sig.semantic == "constant_assumption":
        return assumed("flat world-average constant, the same at every hour and place")
    if sig.is_fallback:
        return assumed("some hours have no data or the series is unlabelled")
    if sig.semantic not in ("average", "marginal"):
        return assumed("the series has no documented average/marginal meaning")
    if sig.retrieved_at is None:
        return assumed("the series has no retrieval date")
    now = now or utc_now()
    age = now - sig.retrieved_at
    if age < timedelta(0):
        return assumed("the series is dated in the future")
    limit = _max_age_days(max_age_days)
    common = {"source": sig.source_version, "region": region, "timestamp": sig.retrieved_at}
    basis = f"{sig.semantic}-intensity hour-of-day mean of a loaded series, retrieved {sig.retrieved_at.date()}"
    if age > timedelta(days=limit):
        return _label(
            REAL_STALE,
            ui=f"Real series, STALE ({age.days} days old)",
            reason=f"Carbon uses a {basis}; it is {age.days} days old (limit {limit}). Treat it as stale.",
            **common,
        )
    return _label(
        REAL_FRESH,
        ui="Real series (hour-of-day mean)",
        reason=f"Carbon uses a {basis}. It is not a live feed and not a dated forecast.",
        **common,
    )


def current_carbon_label(
    zone: Optional[str] = None, *, now: Optional[datetime] = None, max_age_days: Optional[int] = None
) -> dict[str, Any]:
    """Label of what the twin would load now. A load error is ``unavailable``, never a silent fallback to real."""
    try:
        sig = load_carbon_signal(zone)
    except Exception:  # a broken optional file must not take a report down
        return carbon_label(None)
    return carbon_label(sig, now=now, max_age_days=max_age_days)


# ---- claim guard -----------------------------------------------------------------------------------------------
_CLAIMS = re.compile(
    r"carbon[- ]optimal"
    r"|saves?\s+(?:co2|co₂|carbon|emissions?)"
    r"|(?:co2|co₂|carbon|emissions?)\s+(?:savings?|saved|avoided)"
    r"|(?:reduc\w+|cuts?)\s+(?:the\s+)?(?:co2|co₂|carbon|emissions?)"
    r"|carbon[- ]reduction"
    r"|carbon[- ]aware\s+optimi[sz]ation\s+demonstrated"
    r"|real grid carbon|measured emissions",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(?:no|not|never|without|cannot|can't|isn't|doesn't|does not|refuses?|unsupported)\b", re.IGNORECASE
)


def unsupported_carbon_claims(text: str, label: dict[str, Any]) -> list[str]:
    """Claim phrases in ``text`` that ``label`` does not support (always ``[]`` when the label is real).

    A sentence that negates the phrase ("No carbon reduction is claimed.") is not a claim.
    """
    if label.get("is_real"):
        return []
    found: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if _NEGATION.search(sentence):
            continue
        found += [m.group(0).lower() for m in _CLAIMS.finditer(sentence)]
    return found
