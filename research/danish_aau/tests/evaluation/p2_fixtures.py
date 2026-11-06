"""SYNTHETIC helpers for the Phase 2 tests. No Danish AAU data is used or needed.

``build_reader`` writes a CSV with a REGISTERED filename (so discovery accepts it) from exact raw text rows, then returns a
reader whose pass 1 has run. Column names follow the documented patterns but the numbers are invented.
"""

from __future__ import annotations

from pathlib import Path

import synthetic_fixtures as fx

from research.danish_aau.evaluation.data_layer.channels import resolve_channels
from research.danish_aau.evaluation.data_layer.config import DataConfig, parse_data_config
from research.danish_aau.evaluation.data_layer.discovery import discover_sources
from research.danish_aau.evaluation.data_layer.reader import AauCsvReader
from research.danish_aau.evaluation.registry import DEFAULT_REGISTRY

FILENAME = {e.key: e.filename for e in DEFAULT_REGISTRY}
MAIN_KEY, VENT_KEY, SURR_KEY = "temperature_power_25", "ventilation", "surrounding_temperatures"
MAIN_HEADER = ["Time [Date/Time]", "Power Ch 1 (W)", "Power Ch 2 (W)", "Temperature mod 1 ch 1"]
VENT_HEADER = ["time", *fx.VENTILATION_HEADER[1:]]
VENT_COLUMNS = fx.VENTILATION_HEADER[1:]
VENT_CFG = {"files": {VENT_KEY: {"measurement_columns": VENT_COLUMNS}}}


def ts(second: int, minute: int = 40) -> str:
    return f"2024-09-17 09:{minute:02d}:{second:02d}"


def make_cfg(chunksize: int = 50_000, **sections) -> DataConfig:
    raw = {"reader": {"chunksize": chunksize, **sections.pop("reader", {})}, **sections}
    return parse_data_config(raw)


def write_source(raw_dir: Path, key: str, header: list[str], rows: list[list[str]], **kw) -> Path:
    return fx.write_csv(raw_dir / FILENAME[key], header, rows, **kw)


def build_reader(
    tmp_path: Path,
    key: str,
    header: list[str],
    rows: list[list[str]],
    *,
    chunksize: int = 50_000,
    cfg: DataConfig | None = None,
    build_index: bool = True,
    **csv_kw,
) -> tuple[AauCsvReader, Path]:
    raw = tmp_path / "raw_p2"
    write_source(raw, key, header, rows, **csv_kw)
    cfg = cfg or make_cfg(chunksize, **(VENT_CFG if key == VENT_KEY else {}))
    source = discover_sources(raw, DEFAULT_REGISTRY, [key], delimiter=cfg.reader.delimiter)[key]
    reader = AauCsvReader(source, resolve_channels(source, cfg), cfg)
    if build_index:
        reader.build_time_index()
    return reader, raw


def main_rows(n: int, *, start: int = 0) -> list[list[str]]:
    return [[ts(start + i), f"{100 + i}.0", f"{200 + i}.0", f"{20 + i / 10:.1f}"] for i in range(n)]


def build_reader_from_text(
    tmp_path: Path,
    key: str,
    text: str | bytes,
    *,
    chunksize: int = 50_000,
    cfg: DataConfig | None = None,
    build_index: bool = True,
):
    """Like build_reader but the exact file bytes are given (blank lines, CRLF, BOM, odd delimiters)."""
    raw = tmp_path / "raw_p2"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / FILENAME[key]).write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    cfg = cfg or make_cfg(chunksize, **(VENT_CFG if key == VENT_KEY else {}))
    source = discover_sources(raw, DEFAULT_REGISTRY, [key], delimiter=cfg.reader.delimiter)[key]
    reader = AauCsvReader(source, resolve_channels(source, cfg), cfg)
    if build_index:
        reader.build_time_index()
    return reader, raw


def frame_of(reader: AauCsvReader, columns=None, **kw):
    from research.danish_aau.evaluation.data_layer.observations import ObservationStream

    return ObservationStream.open(reader, columns, **kw).to_frame(confirm=True)


# 11 rows: ts2 appears at rows 3 and 9 (IDENTICAL values, non-adjacent, row 9 is a backward step);
#          ts3 appears at rows 4 and 5 (CONFLICTING values, adjacent).
DUP_ROWS = [
    [ts(0), "100.0", "200.0", "20.0"],
    [ts(1), "101.0", "201.0", "20.1"],
    [ts(2), "102.0", "202.0", "20.2"],
    [ts(3), "103.0", "203.0", "20.3"],
    [ts(3), "103.5", "203.5", "20.35"],
    [ts(4), "104.0", "204.0", "20.4"],
    [ts(5), "105.0", "205.0", "20.5"],
    [ts(6), "106.0", "206.0", "20.6"],
    [ts(2), "102.0", "202.0", "20.2"],
    [ts(7), "107.0", "207.0", "20.7"],
    [ts(8), "108.0", "208.0", "20.8"],
]
