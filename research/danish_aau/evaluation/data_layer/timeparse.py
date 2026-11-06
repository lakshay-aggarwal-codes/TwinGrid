"""Explicit-format parsing of NAIVE timestamps. Nothing is inferred and no timezone is attached or converted.

The original text is never altered; this module only derives an int64 nanosecond value ("as written", treated as a
naive wall clock) and a status per row. Text that does not match one of the configured formats exactly is
``parse_error``; an empty/blank cell is ``empty``; text that ends in a timezone designator (Z, +02:00, -0500, UTC) is
``tz_suffix_rejected`` whatever the format says: no timezone is inferred, converted or silently dropped.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

NAT_NS = int(np.iinfo(np.int64).min)
OK, EMPTY, ERROR, TZ_SUFFIX = 0, 1, 2, 3
STATUS_NAMES = {OK: "ok", EMPTY: "empty", ERROR: "parse_error", TZ_SUFFIX: "tz_suffix_rejected"}

# A timezone designator after a time component: literal Z, a numeric offset (+02, +02:00, -0500) or UTC/GMT. Checked on the
# TEXT, independently of the configured format, so a format with a literal trailing "Z" can never smuggle a zone in as a
# naive value. Date-only text ("2024-09-17") has no time component and is not affected.
TZ_SUFFIX_RE = re.compile(r"\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?\s*(?:[Zz]|[+\-]\d{2}(?::?\d{2})?|UTC|GMT)$")


def parse_naive_timestamps(
    texts: pd.Series, formats: tuple[str, ...], strip: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """(ns, status): int64 nanoseconds (NAT_NS where not ok) and an int8 status per row."""
    clean = texts.astype(object).map(lambda v: "" if v is None else str(v))
    if strip:
        clean = clean.str.strip()
    n = len(clean)
    ns = np.full(n, NAT_NS, dtype=np.int64)
    empty = (clean == "").to_numpy()
    tz = clean.map(lambda v: bool(TZ_SUFFIX_RE.search(v))).to_numpy(dtype=bool) & ~empty
    remaining = ~empty & ~tz
    for fmt in formats:
        idx = np.flatnonzero(remaining)
        if idx.size == 0:
            break
        parsed = pd.to_datetime(clean.iloc[idx], format=fmt, errors="coerce", exact=True)
        good = parsed.notna().to_numpy()
        if good.any():
            values = parsed.to_numpy(dtype="datetime64[ns]").astype(np.int64)
            ns[idx[good]] = values[good]
            remaining[idx[good]] = False
    status = np.where(empty, EMPTY, np.where(tz, TZ_SUFFIX, np.where(remaining, ERROR, OK))).astype(np.int8)
    return ns, status


def ns_to_text(ns: int) -> str:
    return pd.Timestamp(int(ns)).strftime("%Y-%m-%d %H:%M:%S")


def parse_one(text: str, formats: tuple[str, ...]) -> int | None:
    ns, status = parse_naive_timestamps(pd.Series([text]), formats)
    return int(ns[0]) if status[0] == OK else None
