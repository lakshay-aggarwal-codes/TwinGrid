"""Registry of the four AAU files audited so far, and classification of their columns.

EVERY number here is an EXPECTATION REPORTED IN ``danish_aau_dataset_context.md`` (a hand-off summary of an earlier
local audit). It is not independently verified by this code. ``inventory`` compares the files actually found on the
user's machine against these expectations and reports match/mismatch; a mismatch means "the local file differs from
what the context document reported", not "the file is wrong".

Only the 25% load period and two supplementary files were audited. Other load-period files (50/75/100/idle) are
discovered and listed as UNREGISTERED; no expectation is invented for them.

Column classification never guesses: a column that matches no rule is reported as unclassified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import _reuse
from .provenance import ColumnSpec, Provenance, UnitBasis

EXPECTATION_SOURCE = "context_doc_reported_unverified"


@dataclass(frozen=True)
class ExpectedFile:
    key: str
    filename: str
    role: str
    expected_size_bytes: int
    expected_n_columns: int
    expected_first_column: str
    expected_rows: int
    expected_first_timestamp: str  # naive, as printed in the CSV; timezone NOT established
    expected_last_timestamp: str
    nominal_interval_s: int | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "filename": self.filename,
            "role": self.role,
            "expected_size_bytes": self.expected_size_bytes,
            "expected_n_columns": self.expected_n_columns,
            "expected_first_column": self.expected_first_column,
            "expected_rows": self.expected_rows,
            "expected_first_timestamp": self.expected_first_timestamp,
            "expected_last_timestamp": self.expected_last_timestamp,
            "nominal_interval_s": self.nominal_interval_s,
            "note": self.note,
            "expectation_source": EXPECTATION_SOURCE,
        }


DEFAULT_REGISTRY: tuple[ExpectedFile, ...] = (
    ExpectedFile(
        key="temperature_power_25",
        filename="AAU_temperature_and_power_use_25_percent_load_period.csv",
        role="primary: 3 rack-level power channels (W) + point temperature channels",
        expected_size_bytes=46_786_437,
        expected_n_columns=52,
        expected_first_column="Time [Date/Time]",
        expected_rows=90_902,
        expected_first_timestamp="2024-09-17 09:40:00",
        expected_last_timestamp="2024-09-18 10:55:00",
        nominal_interval_s=1,
        note="46 duplicate timestamp pairs with differing values (14 clusters); no policy validated",
    ),
    ExpectedFile(
        key="air_speed_25",
        filename="AAU_air_speed_25_percent_load_period.csv",
        role="16 anemometer channels (point velocity; NOT volumetric flow)",
        expected_size_bytes=2_926_941,
        expected_n_columns=17,
        expected_first_column="Time [Date/Time]",
        expected_rows=9_091,
        expected_first_timestamp="2024-09-17 09:40:00",
        expected_last_timestamp="2024-09-18 10:55:01",
        nominal_interval_s=10,
    ),
    ExpectedFile(
        key="surrounding_temperatures",
        filename="AAU_supplementary_surrounding_temperatures.csv",
        role="supplementary: outdoor and adjacent-room temperatures, 15-minute cadence",
        expected_size_bytes=156_859,
        expected_n_columns=7,
        expected_first_column="time",
        expected_rows=1_526,
        expected_first_timestamp="2024-09-16 16:45:00",
        expected_last_timestamp="2024-10-02 14:00:00",
        nominal_interval_s=900,
        note="4 missing Outdoor_temperature values; 101 observations inside the 25% window",
    ),
    ExpectedFile(
        key="ventilation",
        filename="AAU_supplementary_ventilation.csv",
        role="supplementary: damper and AHU values; ~66.7% empty by acquisition schedule",
        expected_size_bytes=225_183,
        expected_n_columns=7,
        expected_first_column="time",
        expected_rows=4_576,
        expected_first_timestamp="2024-09-16 16:45:00",
        expected_last_timestamp="2024-10-02 14:05:00",
        nominal_interval_s=None,
        note="populated observations are ~15 min apart; never fill the empty cells by default",
    ),
)


def registry_to_list(registry: tuple[ExpectedFile, ...] = DEFAULT_REGISTRY) -> list[dict[str, Any]]:
    return [e.to_dict() for e in registry]


def registry_sha256(registry: tuple[ExpectedFile, ...] = DEFAULT_REGISTRY) -> str:
    return str(_reuse.canonical().sha256_json(registry_to_list(registry)))


# --------------------------------------------------------------------------------------------------------------
# Column classification. Rules are anchored regexes; the first match wins; no match -> None (reported, not guessed).
# --------------------------------------------------------------------------------------------------------------

_POWER = re.compile(r"^Power Ch (\d+) \(W\)$")
_TEMP = re.compile(r"^Temperature mod (\d+) ch (\d+)$")
_VELOCITY = re.compile(r"^velocity (\d+)$")
_SURROUNDING = frozenset(
    {
        "Outdoor_temperature",
        "Room_adjacent_west_temperature",
        "Room_adjacent_east_temperature",
        "Room_above_west_temperature",
        "Room_above_east_temperature",
        "Room_below_temperature",
    }
)
_VENTILATION = frozenset(
    {
        "Room_damper_opening",
        "AHU_pressure_supply_duct",
        "AHU_pressure_extraction_duct",
        "AHU_fan_speed_supply",
        "AHU_fan_speed_extraction",
        "AHU_temperature_supply",
    }
)
_TIMESTAMP_NAMES = {
    "temperature_power": "Time [Date/Time]",
    "air_speed": "Time [Date/Time]",
    "surrounding_temperatures": "time",
    "ventilation": "time",
}


def file_family(key: str) -> str:
    """'temperature_power_25' -> 'temperature_power'; other keys are returned unchanged."""
    for family in ("temperature_power", "air_speed"):
        if key.startswith(family):
            return family
    return key


def classify_column(file_key: str, column: str) -> ColumnSpec | None:
    """Classification of ONE column of a registered file, or None when no documented rule covers it."""
    family = file_family(file_key)
    if column == _TIMESTAMP_NAMES.get(family):
        return ColumnSpec(
            column, "timestamp", None, None, UnitBasis.UNCONFIRMED, "naive date-time; timezone not established"
        )
    if family == "temperature_power":
        if _POWER.match(column):
            return ColumnSpec(
                column,
                "power",
                Provenance.MEASURED,
                "W",
                UnitBasis.CSV_HEADER,
                "rack-level PDU channel; channel-to-port/rack mapping unresolved",
            )
        if _TEMP.match(column):
            return ColumnSpec(
                column,
                "temperature",
                Provenance.MEASURED,
                "degC",
                UnitBasis.PAPER_CONTEXT,
                "PT100 point sensor; module/channel-to-location mapping unresolved",
            )
    elif family == "air_speed":
        if _VELOCITY.match(column):
            return ColumnSpec(
                column,
                "velocity",
                Provenance.MEASURED,
                "m/s",
                UnitBasis.PAPER_CONTEXT,
                "point air velocity (0-5 m/s anemometer); channel-to-coordinate mapping unresolved",
            )
    elif family == "surrounding_temperatures":
        if column in _SURROUNDING:
            return ColumnSpec(
                column,
                "boundary_temperature",
                Provenance.MEASURED,
                None,
                UnitBasis.UNCONFIRMED,
                "unit not stated by the header or the supplied reports; acquisition system undocumented",
            )
    elif family == "ventilation":
        if column in _VENTILATION:
            return ColumnSpec(
                column,
                "ventilation",
                Provenance.MEASURED,
                None,
                UnitBasis.UNCONFIRMED,
                "unit unconfirmed (do not assume percent/fraction/degrees/Pa/rpm); acquisition schedule undocumented",
            )
    return None
