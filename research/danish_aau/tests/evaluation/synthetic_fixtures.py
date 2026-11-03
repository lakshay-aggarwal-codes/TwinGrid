"""SYNTHETIC test fixtures. Nothing here is Danish AAU data; values come from fixed formulas, no randomness.

The files reuse the real registered FILENAMES and the documented column-name PATTERNS so the harness code paths are
exercised, but the module/channel numbering of temperature columns is invented for the fixture (the real mapping is
unresolved), and row counts/sizes are tiny. Tests built on these prove the code behaves as designed on
well-formed and deliberately malformed inputs; they say nothing about the real dataset.
"""

from __future__ import annotations

from pathlib import Path

from research.danish_aau.evaluation.registry import DEFAULT_REGISTRY, ExpectedFile

TEMP_COLUMNS = [f"Temperature mod {m} ch {c}" for m in range(1, 7) for c in range(1, 9)]  # 48 synthetic names
POWER_COLUMNS = [f"Power Ch {i} (W)" for i in (1, 2, 3)]
MAIN_HEADER = ["Time [Date/Time]", *POWER_COLUMNS, *TEMP_COLUMNS]  # 52 columns, like the real file's count
AIR_HEADER = ["Time [Date/Time]", *[f"velocity {i}" for i in range(1, 17)]]  # 17 columns
SURROUNDING_HEADER = [
    "time",
    "Outdoor_temperature",
    "Room_adjacent_west_temperature",
    "Room_adjacent_east_temperature",
    "Room_above_west_temperature",
    "Room_above_east_temperature",
    "Room_below_temperature",
]
VENTILATION_HEADER = [
    "time",
    "Room_damper_opening",
    "AHU_pressure_supply_duct",
    "AHU_pressure_extraction_duct",
    "AHU_fan_speed_supply",
    "AHU_fan_speed_extraction",
    "AHU_temperature_supply",
]


def write_csv(
    path: Path,
    header: list[str],
    rows: list[list[object]],
    *,
    delimiter: str = ",",
    bom: bool = False,
    newline: str = "\n",
    trailing_blank_lines: int = 0,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [delimiter.join(header)] + [delimiter.join(str(v) for v in r) for r in rows]
    text = newline.join(lines) + newline + newline * trailing_blank_lines
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return path


def _stamp(i: int, step_s: int = 1) -> str:
    total = i * step_s
    return f"2024-09-17 09:{40 + total // 60:02d}:{total % 60:02d}"


def _rows(header: list[str], n: int, step_s: int = 1) -> list[list[object]]:
    return [
        [_stamp(i, step_s)] + [round(20.0 + 0.01 * (j + 1) * (i + 1), 3) for j in range(len(header) - 1)]
        for i in range(n)
    ]


def make_dataset(raw_dir: Path, n_rows: int = 6) -> tuple[ExpectedFile, ...]:
    """Write four small files with the registered names; return a registry whose expectations MATCH them."""
    specs = {
        "temperature_power_25": MAIN_HEADER,
        "air_speed_25": AIR_HEADER,
        "surrounding_temperatures": SURROUNDING_HEADER,
        "ventilation": VENTILATION_HEADER,
    }
    expected: list[ExpectedFile] = []
    for base in DEFAULT_REGISTRY:
        header = specs[base.key]
        path = write_csv(raw_dir / base.filename, header, _rows(header, n_rows))
        expected.append(
            ExpectedFile(
                key=base.key,
                filename=base.filename,
                role="SYNTHETIC FIXTURE",
                expected_size_bytes=path.stat().st_size,
                expected_n_columns=len(header),
                expected_first_column=header[0],
                expected_rows=n_rows,
                expected_first_timestamp=_stamp(0),
                expected_last_timestamp=_stamp(n_rows - 1),
                nominal_interval_s=base.nominal_interval_s,
            )
        )
    return tuple(expected)


FIXTURE_CONFIG_TOML = """
schema_version = 1
[run]
name = "fixture"
[dataset]
raw_dir = {raw_dir!r}
is_synthetic_fixture = true
[timestamps]
timezone = {timezone!r}
timezone_basis = {basis!r}
[policies]
duplicate_timestamps = {duplicates!r}
"""


def write_config(path: Path, raw_dir: Path, *, declared: bool = False) -> Path:
    path.write_text(
        FIXTURE_CONFIG_TOML.format(
            raw_dir=str(raw_dir).replace("\\", "/"),
            timezone="Europe/Copenhagen" if declared else "undeclared",
            basis="synthetic test declaration" if declared else "",
            duplicates="keep_all_ordered" if declared else "undeclared",
        ),
        encoding="utf-8",
    )
    return path
