"""Header-level inventory of the raw dataset directory.

Reads only the first line of each CSV (plus an optional streaming row count and optional SHA-256). It does NOT
parse timestamps, inspect duplicates, compute statistics or interpret values: that is Phase 2 (and the existing
``research/danish_aau/audit`` utility's job). Everything it reports about expectations is
"reported by the context document, unverified" -- see ``registry.py``.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from . import _reuse
from .guard import open_raw_bytes
from .registry import DEFAULT_REGISTRY, EXPECTATION_SOURCE, ExpectedFile, classify_column

_DELIMITERS = (",", ";", "\t", "|")
_MAX_HEADER_BYTES = 1 << 20


def discover_csvs(raw_dir: Path) -> list[Path]:
    """Every ``*.csv`` under ``raw_dir`` (recursive), sorted by relative path. Empty if the directory is absent."""
    root = Path(raw_dir)
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".csv"),
        key=lambda p: p.relative_to(root).as_posix(),
    )


def detect_delimiter(header_line: str) -> tuple[str | None, list[str]]:
    """(delimiter, columns). ``None`` when no candidate splits the line or two candidates tie (ambiguous)."""
    best: list[tuple[int, str]] = []
    for d in _DELIMITERS:
        try:
            fields = next(csv.reader([header_line], delimiter=d))
        except (csv.Error, StopIteration):
            continue
        best.append((len(fields), d))
    if not best:
        return None, []
    top = max(n for n, _ in best)
    winners = [d for n, d in best if n == top]
    if top <= 1 or len(winners) != 1:
        return None, [header_line]
    return winners[0], next(csv.reader([header_line], delimiter=winners[0]))


def read_header(path: Path, raw_dir: Path) -> dict[str, Any]:
    with open_raw_bytes(path, raw_dir) as fh:
        raw_line = fh.readline(_MAX_HEADER_BYTES)
    bom = raw_line.startswith(b"\xef\xbb\xbf")
    encoding_ok = True
    try:
        text = raw_line.decode("utf-8-sig")
    except UnicodeDecodeError:
        encoding_ok = False
        text = raw_line.decode("utf-8-sig", errors="replace")
    text = text.rstrip("\r\n")
    delimiter, columns = detect_delimiter(text) if text else (None, [])
    return {
        "bom": bom,
        "encoding_utf8": encoding_ok,
        "delimiter": delimiter,
        "delimiter_ambiguous": delimiter is None and bool(text),
        "columns": columns if delimiter else [],
        "n_columns": len(columns) if delimiter else 0,
    }


def count_data_rows(path: Path, raw_dir: Path) -> int:
    """Non-blank lines minus the header line. Streams the file; counts rows, does not parse them."""
    n = 0
    with open_raw_bytes(path, raw_dir) as fh:
        for line in fh:
            if line.strip():
                n += 1
    return max(n - 1, 0)


def _check(name: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "status": "match" if expected == actual else "mismatch",
    }


def _classification_summary(key: str, columns: list[str]) -> dict[str, Any]:
    kinds: Counter[str] = Counter()
    unclassified: list[str] = []
    unit_unconfirmed: list[str] = []
    for col in columns:
        spec = classify_column(key, col)
        if spec is None:
            unclassified.append(col)
            continue
        kinds[spec.kind] += 1
        if spec.kind != "timestamp" and spec.unit is None:
            unit_unconfirmed.append(col)
    return {
        "by_kind": dict(sorted(kinds.items())),
        "unclassified_count": len(unclassified),
        "unclassified_columns": unclassified[:20],
        "unit_unconfirmed_columns": unit_unconfirmed,
    }


def inspect_registered(
    expected: ExpectedFile,
    path: Path | None,
    raw_dir: Path,
    *,
    count_rows: bool,
    hash_file: bool,
    ambiguous: list[Path] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": expected.key,
        "filename": expected.filename,
        "expectation_source": EXPECTATION_SOURCE,
    }
    if ambiguous:
        entry.update(
            status="ambiguous",
            relpath=None,
            checks=[],
            note="the registered filename exists more than once under the raw directory",
        )
        entry["candidates"] = [p.relative_to(raw_dir).as_posix() for p in ambiguous]
        return entry
    if path is None:
        entry.update(status="missing", relpath=None, checks=[])
        return entry
    header = read_header(path, raw_dir)
    size = path.stat().st_size
    checks = [
        _check("size_bytes", expected.expected_size_bytes, size),
        _check("n_columns", expected.expected_n_columns, header["n_columns"]),
        _check("first_column", expected.expected_first_column, header["columns"][0] if header["columns"] else None),
    ]
    rows: int | None = None
    if count_rows:
        rows = count_data_rows(path, raw_dir)
        checks.append(_check("data_rows", expected.expected_rows, rows))
    entry.update(
        relpath=path.relative_to(raw_dir).as_posix(),
        size_bytes=size,
        header={k: v for k, v in header.items() if k != "columns"},
        data_rows=rows,
        sha256=str(_reuse.canonical().sha256_raw_file(path)) if hash_file else None,
        checks=checks,
        columns=_classification_summary(expected.key, header["columns"]),
        status="match" if all(c["status"] == "match" for c in checks) else "mismatch",
    )
    return entry


def inventory_raw(
    raw_dir: Path,
    registry: tuple[ExpectedFile, ...] = DEFAULT_REGISTRY,
    *,
    count_rows: bool = False,
    hash_files: bool = False,
) -> dict[str, Any]:
    """Inventory of ``raw_dir``: registered files checked against the reported expectations, other CSVs listed."""
    root = Path(raw_dir)
    exists = root.is_dir()
    csvs = discover_csvs(root)
    by_name: dict[str, list[Path]] = {}
    for p in csvs:
        by_name.setdefault(p.name.lower(), []).append(p)

    files: list[dict[str, Any]] = []
    registered_paths: set[Path] = set()
    for exp in registry:
        matches = by_name.get(exp.filename.lower(), [])
        if len(matches) > 1:
            files.append(inspect_registered(exp, None, root, count_rows=False, hash_file=False, ambiguous=matches))
            registered_paths.update(matches)
        elif matches:
            registered_paths.add(matches[0])
            files.append(inspect_registered(exp, matches[0], root, count_rows=count_rows, hash_file=hash_files))
        else:
            files.append(inspect_registered(exp, None, root, count_rows=False, hash_file=False))

    unregistered = []
    for p in csvs:
        if p in registered_paths:
            continue
        header = read_header(p, root)
        unregistered.append(
            {
                "relpath": p.relative_to(root).as_posix(),
                "size_bytes": p.stat().st_size,
                "n_columns": header["n_columns"],
                "delimiter": header["delimiter"],
                "note": "not audited; no expectations and no column classification",
            }
        )

    statuses = Counter(f["status"] for f in files)
    return {
        "raw_dir_exists": exists,
        "n_csv_found": len(csvs),
        "files": files,
        "unregistered_csv": unregistered,
        "summary": {
            "n_registered": len(files),
            "n_match": statuses["match"],
            "n_mismatch": statuses["mismatch"],
            "n_missing": statuses["missing"],
            "n_ambiguous": statuses["ambiguous"],
            "all_registered_match": exists and statuses["match"] == len(files),
            "rows_counted": count_rows,
            "files_hashed": hash_files,
        },
    }


def format_inventory(report: dict[str, Any]) -> str:
    """Plain-ASCII table for the console."""
    lines = []
    for f in report["files"]:
        lines.append(f"[{f['status'].upper():9}] {f['filename']}")
        for c in f.get("checks", []):
            if c["status"] != "match":
                lines.append(f"    {c['name']}: expected {c['expected']!r}, found {c['actual']!r}")
        cols = f.get("columns")
        if cols:
            kinds = ", ".join(f"{k}={v}" for k, v in cols["by_kind"].items())
            lines.append(f"    columns: {kinds}; unclassified={cols['unclassified_count']}")
    for u in report["unregistered_csv"]:
        lines.append(f"[UNREGISTERED] {u['relpath']} ({u['size_bytes']} bytes, {u['n_columns']} columns)")
    s = report["summary"]
    lines.append(
        f"summary: match={s['n_match']} mismatch={s['n_mismatch']} missing={s['n_missing']} ambiguous={s['n_ambiguous']} "
        f"unregistered={len(report['unregistered_csv'])}"
    )
    lines.append(
        "note: expectations come from the context document and are unverified; 'match' is not a data-quality verdict"
    )
    return "\n".join(lines)


__all__ = [
    "count_data_rows",
    "detect_delimiter",
    "discover_csvs",
    "format_inventory",
    "inventory_raw",
    "read_header",
]
