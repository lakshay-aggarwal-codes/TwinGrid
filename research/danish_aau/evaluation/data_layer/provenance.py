"""Provenance records and exclusion ledgers for every derived operation.

A ``DerivationRecord`` states: which source file(s) and rows, which transformation, which policy id, which relevant
configuration (embedded and hashed), how many rows were excluded (and the ledger's hash), and what the output is
(layer, provenance label, shape). Records and ledgers are canonical-JSON/CSV serialisable, and writing is confined to
safe locations: never inside the raw dataset directory, never under a production path.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .. import _reuse
from ..paths import UnsafeOutputPath, ensure_output_dir_safe
from .errors import UnsafeDerivedPath
from .vocabulary import Layer, Provenance


def _sha(obj: Any) -> str:
    return str(_reuse.canonical().sha256_json(obj))


def row_summary(src_rows: np.ndarray | list[int]) -> dict[str, Any]:
    rows = np.asarray(src_rows, dtype=np.int64)
    return {
        "count": int(rows.size),
        "min": int(rows.min()) if rows.size else None,
        "max": int(rows.max()) if rows.size else None,
        "sha256": _sha([int(r) for r in rows]),
    }


@dataclass
class ExclusionLedger:
    """Every row a policy removed from a view, with the reason. Empty ledger = nothing was excluded."""

    policy_id: str
    file_key: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, src_row: int, reason: str, **detail: Any) -> None:
        self.entries.append(
            {
                "file_key": self.file_key,
                "src_row": int(src_row),
                "reason": reason,
                "policy_id": self.policy_id,
                **detail,
            }
        )

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def excluded_rows(self) -> set[int]:
        return {e["src_row"] for e in self.entries}

    def summary(self) -> dict[str, Any]:
        reasons: dict[str, int] = {}
        for e in self.entries:
            reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
        return {
            "policy_id": self.policy_id,
            "file_key": self.file_key,
            "n_excluded": self.count,
            "by_reason": reasons,
            "sha256": _sha(self.entries),
        }

    def write_csv(self, path: Path, raw_dir: Path) -> Path:
        path = safe_output_path(path, raw_dir)
        keys = ["file_key", "src_row", "reason", "policy_id"]
        extra = sorted({k for e in self.entries for k in e} - set(keys))
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[*keys, *extra], lineterminator="\n")
            w.writeheader()
            w.writerows(self.entries)
        return path


@dataclass(frozen=True)
class DerivationRecord:
    operation: str
    policy_id: str | None
    transformation: str
    source_files: tuple[str, ...]
    source_rows: dict[str, Any]
    config: dict[str, Any]
    exclusions: dict[str, Any] | None
    output: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d = {
            "operation": self.operation,
            "policy_id": self.policy_id,
            "transformation": self.transformation,
            "source_files": list(self.source_files),
            "source_rows": self.source_rows,
            "config": self.config,
            "config_sha256": _sha(self.config),
            "exclusions": self.exclusions,
            "output": self.output,
        }
        d["record_sha256"] = _sha(d)
        return d


def output_descriptor(layer: Layer, provenance: Provenance, n_rows: int, columns: list[str]) -> dict[str, Any]:
    return {"layer": layer.value, "provenance": provenance.value, "n_rows": int(n_rows), "columns": list(columns)}


class ProvenanceLog:
    """Ordered list of DerivationRecords for one run/file."""

    def __init__(self) -> None:
        self.records: list[DerivationRecord] = []

    def add(self, record: DerivationRecord) -> DerivationRecord:
        self.records.append(record)
        return record

    def to_list(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.records]

    def write_json(self, path: Path, raw_dir: Path) -> Path:
        path = safe_output_path(path, raw_dir)
        path.write_bytes(_reuse.canonical().canonical_bytes({"records": self.to_list()}))
        return path


def safe_output_path(path: Path, raw_dir: Path) -> Path:
    """Resolve a derived-output file path, refusing the raw dataset directory and production paths."""
    target = Path(path).resolve()
    try:
        ensure_output_dir_safe(target.parent, Path(raw_dir))
        ensure_output_dir_safe(target, Path(raw_dir))
    except UnsafeOutputPath as exc:
        raise UnsafeDerivedPath(str(exc)) from None
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
