"""Deterministic discovery and header validation of the 16 expected CSVs (read-only, no data rows are parsed here)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..evaluation.data_layer.discovery import SourceFile, discover_sources
from ..evaluation.data_layer.errors import DiscoveryError
from ..evaluation.inventory import discover_csvs
from ..evaluation.registry import ExpectedFile
from .errors import AdapterDiscoveryError, AdapterSchemaError
from .schema import FILE_SPECS, FileSpec, column_meta, spec_for_filename, spec_for_key

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "datasets" / "danish-server-room-v5" / "manifest.json"


@dataclass(frozen=True)
class AdapterSource:
    spec: FileSpec
    source: SourceFile
    file_sha256: str | None  # manifest ``local_sha256`` (not recomputed here; Task 2 owns hashing)
    manifest_size_bytes: int | None

    @property
    def key(self) -> str:
        return self.spec.key


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, dict]:
    """{lower-case filename: manifest entry}. The file has a UTF-8 BOM, so it is read as utf-8-sig."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return {e["filename"].lower(): e for e in data["files"]}


def _validate_header(spec: FileSpec, columns: tuple[str, ...], src: SourceFile) -> None:
    problems: list[str] = []
    if src.detected_delimiter != ",":
        problems.append(f"delimiter is {src.detected_delimiter!r}, expected ','")
    if not src.encoding_utf8:
        problems.append("header is not valid UTF-8")
    dup = sorted({c for c in columns if columns.count(c) > 1})
    if dup:
        problems.append(f"duplicate header names {dup}")
    if not columns or columns[0] != spec.timestamp_column:
        problems.append(f"first column must be {spec.timestamp_column!r}, got {columns[:1]}")
    measured = set(columns) - {spec.timestamp_column}
    unexpected, missing = sorted(measured - spec.measurement_columns), sorted(spec.measurement_columns - measured)
    if unexpected:
        problems.append(f"unexpected column(s) {unexpected}")
    if missing:
        problems.append(f"missing column(s) {missing}")
    unclassified = sorted(c for c in measured & spec.measurement_columns if column_meta(spec, c) is None)
    if unclassified:
        problems.append(f"column(s) with no documented unit/meaning rule {unclassified}")
    if problems:
        raise AdapterSchemaError(f"{spec.filename}: " + "; ".join(problems))


def discover_all(
    raw_dir: Path,
    keys: list[str] | None = None,
    *,
    manifest_path: Path | None = DEFAULT_MANIFEST,
    strict: bool = True,
) -> dict[str, AdapterSource]:
    """{key: AdapterSource} in the fixed FILE_SPECS order. Raises on a missing/duplicate/unexpected CSV, a size that
    disagrees with the manifest, or a header that is not exactly the expected one. ``strict=False`` tolerates extra CSVs."""
    root = Path(raw_dir)
    if not root.is_dir():
        raise AdapterDiscoveryError("the raw dataset directory does not exist")
    wanted = [s.key for s in FILE_SPECS] if keys is None else list(keys)
    for k in wanted:
        spec_for_key(k)  # KeyError for unknown keys
    manifest = load_manifest(manifest_path) if manifest_path is not None else {}
    if manifest:
        listed = {n for n in manifest if n.endswith(".csv")}
        expected = {s.filename.lower() for s in FILE_SPECS}
        if listed != expected:
            raise AdapterDiscoveryError(
                f"manifest CSV list differs from the adapter schema: only in manifest {sorted(listed - expected)}, "
                f"only in schema {sorted(expected - listed)}"
            )
    seen: dict[str, list[Path]] = {}
    for p in discover_csvs(root):
        seen.setdefault(p.name.lower(), []).append(p)
    extra = sorted(n for n in seen if spec_for_filename(n) is None)
    if extra and strict:
        raise AdapterDiscoveryError(f"unexpected CSV file(s) in the raw directory: {extra}")
    registry: list[ExpectedFile] = []
    for k in wanted:
        s = spec_for_key(k)
        entry = manifest.get(s.filename.lower())
        registry.append(
            ExpectedFile(
                k,
                s.filename,
                s.family,
                int(entry["size_bytes"]) if entry else 0,
                s.n_columns,
                s.timestamp_column,
                0,
                "",
                "",
                s.nominal_interval_s,
                note="rows/timestamps not asserted by the adapter (Task 4 owns the profile)",
            )
        )
    try:
        found = discover_sources(root, tuple(registry), wanted, delimiter="")
    except DiscoveryError as exc:
        raise AdapterDiscoveryError(str(exc)) from None
    out: dict[str, AdapterSource] = {}
    for k in wanted:
        s, sf = spec_for_key(k), found[k]
        entry = manifest.get(s.filename.lower())
        if entry and int(entry["size_bytes"]) != sf.size_bytes:
            raise AdapterDiscoveryError(
                f"{s.filename}: size {sf.size_bytes} differs from the manifest {entry['size_bytes']}"
            )
        _validate_header(s, tuple(sf.columns), sf)
        out[k] = AdapterSource(
            s, sf, entry["local_sha256"].lower() if entry else None, int(entry["size_bytes"]) if entry else None
        )
    return out
