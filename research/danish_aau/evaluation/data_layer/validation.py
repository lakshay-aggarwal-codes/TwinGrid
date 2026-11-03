"""Cross-check of what the data layer computes against the RECORDED audit findings (context document).

This does not repeat the dataset audit: it compares the TimeIndex results to the expected values, as a consistency
check on the reader. Most expectations are "reported, unverified" (the earlier audit). The ventilation population patterns
and completeness counts are LOCALLY VERIFIED: they come from the reviewer's inspection of the real CSV (4,576 rows in exactly
three disjoint populated-column patterns), not from this code having read it. A mismatch is a finding to report, not an
error, and nothing here is a data-quality verdict.

Correction: the earlier version of this module expected FULL 1,525 / PARTIAL 1 / EMPTY 3,050 and treated "101
observations" as 101 FULL ventilation rows. Both were wrong. No ventilation row has all six fields populated, and the
damper-only observation at 2024-09-16 16:47:00 is one example of the largest pattern, not the only partial row.
"""

from __future__ import annotations

from typing import Any

from .time_index import TimeIndex

EXPECTATION_SOURCE = "context_doc_recorded_audit_unverified"

EXPECTED_AUDIT: dict[str, dict[str, Any]] = {
    "temperature_power_25": {
        "n_rows": 90_902,
        "first_row_text": "2024-09-17 09:40:00",
        "last_row_text": "2024-09-18 10:55:00",
        "n_timestamp_parse_errors": 0,
        "n_timestamp_tz_suffix_rejected": 0,
        "n_ordering_violations": 0,
        "delta_seconds_counts": {"0.0": 46, "1.0": 90_810, "2.0": 45},
        "n_duplicate_groups": 46,
        "n_duplicate_rows": 92,
        "n_conflicting_duplicate_groups": 46,
        "n_missing_cells": 0,
    },
    "air_speed_25": {
        "n_rows": 9_091,
        "first_row_text": "2024-09-17 09:40:00",
        "last_row_text": "2024-09-18 10:55:01",
        "n_timestamp_parse_errors": 0,
        "n_timestamp_tz_suffix_rejected": 0,
        "n_ordering_violations": 0,
        "delta_seconds_counts": {"9.0": 37, "10.0": 9_015, "11.0": 38},
        "n_duplicate_groups": 0,
        "n_missing_cells": 0,
    },
    "surrounding_temperatures": {
        "n_rows": 1_526,
        "first_row_text": "2024-09-16 16:45:00",
        "last_row_text": "2024-10-02 14:00:00",
        "n_timestamp_parse_errors": 0,
        "n_timestamp_tz_suffix_rejected": 0,
        "n_ordering_violations": 0,
        "delta_seconds_counts": {"900.0": 1_525},
        "n_duplicate_groups": 0,
        "missing_by_column": {"Outdoor_temperature": 4},
        "in_window_rows": 101,
    },
    "ventilation": {
        "n_rows": 4_576,
        "first_row_text": "2024-09-16 16:45:00",
        "last_row_text": "2024-10-02 14:05:00",
        "n_timestamp_parse_errors": 0,
        "n_timestamp_tz_suffix_rejected": 0,
        "n_ordering_violations": 0,
        "delta_seconds_counts": {"120.0": 1_525, "180.0": 1_525, "600.0": 1_523, "720.0": 1, "780.0": 1},
        "n_duplicate_groups": 0,
        # Per-column missing counts as reported by the earlier audit (preserved unchanged).
        "missing_by_column": {
            "Room_damper_opening": 3_050,
            "AHU_pressure_supply_duct": 3_051,
            "AHU_pressure_extraction_duct": 3_051,
            "AHU_fan_speed_supply": 3_051,
            "AHU_fan_speed_extraction": 3_051,
            "AHU_temperature_supply": 3_051,
        },
        # Locally verified: every one of the 4,576 rows is PARTIAL (no row has all six fields, none has zero).
        "completeness_counts": {"FULL": 0, "PARTIAL": 4_576, "EMPTY": 0},
        # Locally verified: exactly three populated-column signatures, row counts only (no first/last rows were recorded).
        # The census is descriptive: it does not say the patterns are simultaneous or follow a shared schedule.
        "population_patterns": [
            {"populated_columns": ["Room_damper_opening"], "n_rows": 1_526},
            {
                "populated_columns": ["AHU_fan_speed_supply", "AHU_fan_speed_extraction", "AHU_temperature_supply"],
                "n_rows": 1_525,
            },
            {"populated_columns": ["AHU_pressure_supply_duct", "AHU_pressure_extraction_duct"], "n_rows": 1_525},
        ],
    },
}
LOCALLY_VERIFIED_EXPECTATIONS = {("ventilation", "completeness_counts"), ("ventilation", "population_patterns")}


def _check(name: str, expected: Any, actual: Any, kind: str = "reported") -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "status": "match" if expected == actual else "mismatch",
        "expected_kind": kind,
    }


def _normalise_patterns(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order-independent form of a pattern census: sorted columns, row counts; positions and ids are not compared."""
    items = [{"populated_columns": sorted(p["populated_columns"]), "n_rows": p["n_rows"]} for p in patterns]
    return sorted(items, key=lambda i: (i["populated_columns"], i["n_rows"]))


def cross_check(index: TimeIndex, window_ns: tuple[int, int] | None) -> list[dict[str, Any]]:
    """Compare the TimeIndex summary with the recorded findings for that file (empty list if none are recorded)."""
    expected = EXPECTED_AUDIT.get(index.file_key)
    if not expected:
        return []
    summary = index.summary(window_ns)
    checks = []
    for key, want in expected.items():
        kind = "locally_verified_by_reviewer" if (index.file_key, key) in LOCALLY_VERIFIED_EXPECTATIONS else "reported"
        if key == "missing_by_column":
            checks.append(_check(key, want, {k: summary["missing_by_column"].get(k, 0) for k in want}, kind))
        elif key == "population_patterns":
            checks.append(
                _check(key, _normalise_patterns(want), _normalise_patterns(summary["population_patterns"]), kind)
            )
        elif key == "in_window_rows" and window_ns is None:
            checks.append(
                {"name": key, "expected": want, "actual": None, "status": "not_checked", "expected_kind": kind}
            )
        else:
            checks.append(_check(key, want, summary.get(key), kind))
    return checks


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, int]:
    out = {"match": 0, "mismatch": 0, "not_checked": 0}
    for c in checks:
        out[c["status"]] += 1
    return out
