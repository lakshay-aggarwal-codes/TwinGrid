"""Locate the registered source files (L0). Phase 2 is limited to the four files of the Phase 1 registry.

Unregistered CSVs (idle, 50/75/100 % load, aggregates, ...) are never opened here: asking for one is an error. This
module reuses the Phase 1 discovery/header code and does not repeat the existing local audit utility's job.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..guard import open_raw_bytes
from ..inventory import discover_csvs, read_header
from ..registry import DEFAULT_REGISTRY, ExpectedFile
from .errors import DiscoveryError


@dataclass(frozen=True)
class SourceFile:
    key: str
    filename: str
    path: Path
    raw_dir: Path
    relpath: str
    size_bytes: int
    expected: ExpectedFile
    columns: tuple[str, ...]
    detected_delimiter: str | None
    delimiter: str | None  # configured delimiter if given, else the detected one (None = ambiguous)
    bom: bool
    encoding_utf8: bool

    @property
    def timestamp_column(self) -> str:
        return self.expected.expected_first_column


def _header_with(path: Path, raw_dir: Path, delimiter: str) -> list[str]:
    with open_raw_bytes(path, raw_dir) as fh:
        line = fh.readline(1 << 20).decode("utf-8-sig", errors="replace").rstrip("\r\n")
    return next(csv.reader([line], delimiter=delimiter), [])


def discover_sources(
    raw_dir: Path,
    registry: tuple[ExpectedFile, ...] = DEFAULT_REGISTRY,
    keys: Iterable[str] | None = None,
    *,
    missing_ok: bool = False,
    delimiter: str = "",
) -> dict[str, SourceFile]:
    """{key: SourceFile} for the requested registered keys (default: all registered).

    ``delimiter`` (from ``reader.delimiter``) overrides detection; the header is then parsed with it."""
    root = Path(raw_dir)
    by_key = {e.key: e for e in registry}
    wanted = list(by_key) if keys is None else list(keys)
    unknown = [k for k in wanted if k not in by_key]
    if unknown:
        raise DiscoveryError(
            f"not registered: {unknown}; Phase 2 only loads the registered files {sorted(by_key)}. "
            "Other CSVs stay unregistered until local checks justify adding them."
        )
    if not root.is_dir():
        if missing_ok:
            return {}
        raise DiscoveryError("the raw dataset directory does not exist")
    by_name: dict[str, list[Path]] = {}
    for p in discover_csvs(root):
        by_name.setdefault(p.name.lower(), []).append(p)
    out: dict[str, SourceFile] = {}
    for key in wanted:
        exp = by_key[key]
        found = by_name.get(exp.filename.lower(), [])
        if len(found) > 1:
            raise DiscoveryError(f"{exp.filename!r} exists more than once under the raw directory: ambiguous")
        if not found:
            if missing_ok:
                continue
            raise DiscoveryError(f"registered file for {key!r} not found: {exp.filename!r}")
        path = found[0]
        header = read_header(path, root)
        resolved = delimiter or header["delimiter"]
        columns = tuple(_header_with(path, root, delimiter)) if delimiter else tuple(header["columns"])
        out[key] = SourceFile(
            key=key,
            filename=exp.filename,
            path=path,
            raw_dir=root,
            relpath=path.relative_to(root).as_posix(),
            size_bytes=path.stat().st_size,
            expected=exp,
            columns=columns,
            detected_delimiter=header["delimiter"],
            delimiter=resolved,
            bom=header["bom"],
            encoding_utf8=header["encoding_utf8"],
        )
    return out
