"""Shared vocabulary of the four-layer data model.

  L0  immutable raw files on disk (never opened for writing; fingerprinted by the Phase 1 guard)
  L1  original read-only observations: every row, original order, original values, plus index annotations
  L2  policy-controlled DERIVED observations: a declared policy applied to L1, with an exclusion ledger
  L3  TwinGrid SIMULATED series: a separate namespace; Phase 2 only defines the container (no simulator, no ``src``)

L1/L2 and L3 meet ONLY inside an ``AlignmentResult`` whose columns are namespaced ``target__*`` / ``source__*``.
"""

from __future__ import annotations

from enum import Enum

from ..provenance import Provenance  # Phase 1 vocabulary: measured / estimated / derived / simulated

__all__ = [
    "AlignStatus",
    "AlignmentStrategy",
    "Completeness",
    "Layer",
    "OrderFlag",
    "ParseStatus",
    "PolicyId",
    "Provenance",
    "TimeBasis",
    "TimestampState",
]


class Layer(str, Enum):
    L0_RAW = "L0"
    L1_OBSERVED = "L1"
    L2_DERIVED = "L2"
    L3_SIMULATED = "L3"


class TimestampState(str, Enum):
    """What is known about the timezone of a timestamp. Phase 2 only ever uses NAIVE_UNSPECIFIED."""

    NAIVE_UNSPECIFIED = "naive_unspecified"


class TimeBasis(str, Enum):
    NAIVE_WALLCLOCK = "naive_wallclock"  # parsed naive timestamps, compared as written; needs a shared clock id
    ELAPSED = "elapsed_from_origin"  # seconds since each series' own origin; offsets must be declared
    TZ_AWARE = "tz_aware"  # refused in Phase 2: needs an approved, documentary TimeMapping


class ParseStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    ERROR = "parse_error"


class OrderFlag(str, Enum):
    FIRST = "first"  # first parseable timestamp in source order
    OK = "ok"  # not earlier than the previous parseable timestamp (equal is a duplicate, not a violation)
    BACKWARD = "backward"  # earlier than the previous parseable timestamp (ordering violation)
    UNPARSED = "unparsed"  # the timestamp did not parse; no ordering statement is made


class Completeness(str, Enum):
    FULL = "FULL"  # every expected measurement field populated
    PARTIAL = "PARTIAL"  # at least one, but not all
    EMPTY = "EMPTY"  # none populated (kept in L1, not a valid measurement observation)


class AlignmentStrategy(str, Enum):
    EXACT = "exact"
    NEAREST = "nearest"
    BACKWARD_ASOF = "backward_asof"
    BUCKET = "bucket"


class AlignStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"


class PolicyId:
    KEEP_ALL_ORDERED = "keep_all_ordered"  # primary duplicate policy: nothing is removed
    EXCLUDE_AMBIGUOUS = "exclude_ambiguous"  # sensitivity policy: needs explicit approval, full ledger
    EXCLUDE_EMPTY_ROWS = "exclude_empty_rows"  # EMPTY rows are not valid measurement observations
    KEEP_EMPTY_FLAGGED = "keep_empty_flagged"
    STABLE_TIME_ORDER = "stable_time_order"  # sorted derived view; permutation recorded

    DUPLICATE_POLICIES = (KEEP_ALL_ORDERED, EXCLUDE_AMBIGUOUS)
    EMPTY_POLICIES = (EXCLUDE_EMPTY_ROWS, KEEP_EMPTY_FLAGGED)
