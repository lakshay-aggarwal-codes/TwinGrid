"""Tier 1 column selection (37 rack-labelled temperature probes + 3 power channels).

This is a COLUMN SELECTION for cleaning, not an identity mapping: no rack, sensor id or mapping is assigned here
(Task 13 owns identity). The selection is the 51 measurement columns of the temperature/power files minus the 11
cooling-unit / room probes that the Task 3 identity evidence labels as facility-level (Task 7 Tier 2). A test checks it
against the Task 6 runner register and the adapter schema.
"""

from __future__ import annotations

import re

from ..adapter.schema import spec_for_key

POWER_COLUMNS = tuple(f"Power Ch {n} (W)" for n in (1, 2, 3))

# Cooling-unit and room probes (Task 3 source-image labels: Back cooling window/wall, Gradient 1-5, Cooling wall/window
# front L/R). They are Tier 2: register-only, never cleaned into L1 observations by this task.
NOT_TIER1_TEMPERATURE_COLUMNS = (
    "Temperature mod 3 ch 1",
    "Temperature mod 3 ch 2",
    "Temperature mod 4 ch 1",
    "Temperature mod 4 ch 2",
    "Temperature mod 4 ch 3",
    "Temperature mod 4 ch 4",
    "Temperature mod 4 ch 5",
    "Temperature mod 8 ch 1",
    "Temperature mod 8 ch 2",
    "Temperature mod 8 ch 3",
    "Temperature mod 8 ch 4",
)


def _all_temperature_columns() -> tuple[str, ...]:
    return tuple(f"Temperature mod {m} ch {c}" for m in range(1, 9) for c in range(1, 9 if m <= 4 else 5))


RACK_PROBE_COLUMNS = tuple(c for c in _all_temperature_columns() if c not in NOT_TIER1_TEMPERATURE_COLUMNS)
TIER1_COLUMNS = POWER_COLUMNS + RACK_PROBE_COLUMNS  # 3 + 37 = 40, fixed order

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def column_slug(column: str) -> str:
    """Deterministic file-name stem for a source column, e.g. 'Power Ch 1 (W)' -> 'power_ch_1_w'."""
    s = _SLUG_RE.sub("_", column.lower()).strip("_")
    if not s:
        raise ValueError(f"column {column!r} has no usable file-name stem")
    return s


def check_selection() -> None:
    """Raise if the selection is not a 3 + 37 subset of the adapter's temperature/power columns."""
    cols = spec_for_key("temperature_power").measurement_columns
    if len(POWER_COLUMNS) != 3 or len(RACK_PROBE_COLUMNS) != 37 or len(TIER1_COLUMNS) != 40:
        raise ValueError("Tier 1 must be 3 power + 37 rack-probe columns")
    if not set(TIER1_COLUMNS) <= cols or len(set(TIER1_COLUMNS)) != 40:
        raise ValueError("Tier 1 columns must be 40 distinct columns of the temperature/power schema")
    if len({column_slug(c) for c in TIER1_COLUMNS}) != 40:
        raise ValueError("column slugs must be unique")
