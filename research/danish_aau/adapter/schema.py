"""The explicit file/column schema of Danish AAU v5 (16 CSVs). Nothing here is inferred from the data.

Authority: manifest file names; Task 3 identity evidence and Task 4 profile (column counts: 52 / 17 / 7 / 7); column
meaning and units come ONLY from ``evaluation.registry.classify_column`` (header-stated W, paper-stated degC and m/s,
unit not established for the supplementary files). Header ORDER is recorded, not asserted: the expected set is exact,
the timestamp column must come first. No rack, tier, sensor id or mapping is assigned here (Task 13).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..evaluation.registry import classify_column

DATASET_ID = "danish-aau-v5"
TS_FORMAT = "%Y-%m-%d %H:%M:%S"
ROW_NUMBERING = (
    "data_row_ordinal_excluding_header"  # contract section 8; confirmed against the Task 6 runner (see tests)
)

# kind (classify_column) -> contract measurand; kinds without a contract measurand stay None ("not_established")
MEASURAND_BY_KIND = {"temperature": "temperature", "power": "power", "velocity": "air_speed"}


def _temp_power_columns() -> tuple[str, ...]:
    power = tuple(f"Power Ch {n} (W)" for n in (1, 2, 3))
    temps = tuple(f"Temperature mod {m} ch {c}" for m in range(1, 9) for c in range(1, 9 if m <= 4 else 5))
    return power + temps  # 3 + 32 + 16 = 51 measurement columns


_AIR = tuple(f"velocity {n}" for n in range(1, 17))
_SURR = (
    "Outdoor_temperature",
    "Room_adjacent_west_temperature",
    "Room_adjacent_east_temperature",
    "Room_above_west_temperature",
    "Room_above_east_temperature",
    "Room_below_temperature",
)
_VENT = (
    "Room_damper_opening",
    "AHU_pressure_supply_duct",
    "AHU_pressure_extraction_duct",
    "AHU_fan_speed_supply",
    "AHU_fan_speed_extraction",
    "AHU_temperature_supply",
)


@dataclass(frozen=True)
class FileSpec:
    key: str
    filename: str
    family: str  # temperature_power | air_speed | surrounding_temperatures | ventilation
    timestamp_column: str
    measurement_columns: frozenset[str]
    nominal_interval_s: int | None  # descriptive only; never used to resample

    @property
    def n_columns(self) -> int:
        return 1 + len(self.measurement_columns)


def _tp(key: str, name: str) -> FileSpec:
    return FileSpec(key, name, "temperature_power", "Time [Date/Time]", frozenset(_temp_power_columns()), 1)


def _air(key: str, name: str) -> FileSpec:
    return FileSpec(key, name, "air_speed", "Time [Date/Time]", frozenset(_AIR), 10)


_PERIODS = (
    ("", ""),
    ("_idle_1", "_idle_period_1"),
    ("_25", "_25_percent_load_period"),
    ("_50", "_50_percent_load_period"),
    ("_75", "_75_percent_load_period"),
    ("_100", "_100_percent_load_period"),
    ("_idle_2", "_idle_period_2"),
)

FILE_SPECS: tuple[FileSpec, ...] = (
    *(_tp(f"temperature_power{k}", f"AAU_temperature_and_power_use{n}.csv") for k, n in _PERIODS),
    *(_air(f"air_speed{k}", f"AAU_air_speed{n}.csv") for k, n in _PERIODS),
    FileSpec(
        "surrounding_temperatures",
        "AAU_supplementary_surrounding_temperatures.csv",
        "surrounding_temperatures",
        "time",
        frozenset(_SURR),
        900,
    ),
    FileSpec("ventilation", "AAU_supplementary_ventilation.csv", "ventilation", "time", frozenset(_VENT), None),
)

_BY_KEY = {s.key: s for s in FILE_SPECS}
_BY_NAME = {s.filename.lower(): s for s in FILE_SPECS}


def spec_for_key(key: str) -> FileSpec:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown file key {key!r}; known: {sorted(_BY_KEY)}") from None


def spec_for_filename(name: str) -> FileSpec | None:
    return _BY_NAME.get(name.lower())


@dataclass(frozen=True)
class ColumnMeta:
    column: str
    kind: str
    measurand: str | None  # contract measurand, or None = not_established
    unit: str  # 'degC' | 'W' | 'm/s' | 'not_established'
    unit_basis: str


def column_meta(spec: FileSpec, column: str) -> ColumnMeta | None:
    """Classification of one measurement column, or None when no documented rule covers it (=> rejected)."""
    c = classify_column(spec.key, column)
    if c is None or c.kind == "timestamp":
        return None
    return ColumnMeta(column, c.kind, MEASURAND_BY_KIND.get(c.kind), c.unit or "not_established", c.unit_basis.value)
