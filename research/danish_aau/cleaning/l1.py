"""L1 file set (Task 9 layer L1): deterministic text files plus a manifest with SHA-256s. FORMAT PROPOSAL (Task 9 left it to
Task 12; the owner approves it).

Layout (relative to the L1 directory)::

    observations/<column_slug>.tsv   one file per Tier 1 column, one line per stored second, ascending by naive second
    ledger/<file_stem>.tsv           one line per raw row of the source file, ascending by source row
    l1_manifest.json                 sha256 / bytes / rows of every file above, counts, protocol and code hashes

Observation line (tab separated, header first)::

    ts_text  value_ticks  state  quality  reason_code  disposition  group_size  first_row_ordinal

``value_ticks`` is the integer number of resolution steps (0.01 degC, 0.1 W); empty when the cell is missing.
``state`` is ``observed`` or ``missing``; ``quality`` is ``ok`` / ``flagged`` (empty when missing). ``disposition`` is the
record-level protocol disposition (``flagged`` for a flagged cell). ``first_row_ordinal`` is the lowest source row of the
group (contract 1.0.0 row lineage C-5). No timezone, no UTC, no float formatting: output depends only on the inputs, so a
rerun is byte-identical (UTF-8, LF, no timestamps, no absolute paths, no platform text).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .catalogue import (
    FLAG_TEXT,
    REASON_TEXT,
    ROW_DISPOSITIONS,
)
from .ledger import _reason_for
from .resolve import CleanResult
from .tier1 import column_slug

L1_FORMAT = "twingrid.danish_aau.l1/1"
OBS_HEADER = [
    "ts_text",
    "value_ticks",
    "state",
    "quality",
    "reason_code",
    "disposition",
    "group_size",
    "first_row_ordinal",
]
LEDGER_HEADER = ["row_ordinal", "ts_text", "disposition", "reason_code", "group_size", "first_row_ordinal"]


def code_sha256() -> str:
    """Hash of the cleaning package sources (LF-normalised, sorted by name)."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")):
        h.update(p.name.encode() + b"\x00" + p.read_bytes().replace(b"\r\n", b"\n") + b"\x00")
    return h.hexdigest()


def _write_tsv(path: Path, df: pd.DataFrame) -> tuple[str, int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep="\t", index=False, lineterminator="\n", na_rep="", encoding="utf-8")
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data), len(df)


def observation_frame(result: CleanResult, j: int) -> pd.DataFrame:
    valid = result.valid[:, j]
    flag = result.flag[:, j]
    reason = np.where(
        valid,
        np.where(flag > 0, [FLAG_TEXT.get(int(f), "") for f in flag], ""),
        [REASON_TEXT.get(int(r), "") for r in result.reason[:, j]],
    )
    disp = np.array([ROW_DISPOSITIONS[int(d)] for d in result.sec_disp], dtype=object)
    disp = np.where(flag > 0, "flagged", disp)
    quality = np.where(valid, np.where(flag > 0, "flagged", "ok"), "")
    ticks = pd.array(np.where(valid, result.ticks[:, j], 0), dtype="Int64")
    ticks[~valid] = pd.NA
    return pd.DataFrame(
        {
            "ts_text": result.ts_text.astype(str),
            "value_ticks": ticks,
            "state": np.where(valid, "observed", "missing"),
            "quality": quality,
            "reason_code": reason,
            "disposition": disp,
            "group_size": result.group_size,
            "first_row_ordinal": result.first_row,
        }
    )[OBS_HEADER]


def ledger_frame(result: CleanResult) -> pd.DataFrame:
    sec = result.row_sec.astype(np.int64)
    reasons = [(_reason_for(result, i) or "") for i in range(result.n_rows)]
    return pd.DataFrame(
        {
            "row_ordinal": result.row_ordinal,
            "ts_text": result.ts_text[sec].astype(str),
            "disposition": [ROW_DISPOSITIONS[int(d)] for d in result.row_disp],
            "reason_code": reasons,
            "group_size": result.group_size[sec],
            "first_row_ordinal": result.first_row[sec],
        }
    )[LEDGER_HEADER]


def write_l1(
    result: CleanResult,
    out_dir: Path,
    *,
    dataset_id: str,
    protocol_sha256: str,
    source_file_sha256: str | None,
    contract_version: str = "1.0.0",
) -> dict:
    out = Path(out_dir)
    files: dict[str, dict] = {}
    for j, col in enumerate(result.columns):
        rel = f"observations/{column_slug(col)}.tsv"
        sha, nbytes, rows = _write_tsv(out / rel, observation_frame(result, j))
        files[rel] = {"sha256": sha, "bytes": nbytes, "rows": rows, "column": col}
    stem = Path(result.file).stem
    rel = f"ledger/{stem}.tsv"
    sha, nbytes, rows = _write_tsv(out / rel, ledger_frame(result))
    files[rel] = {"sha256": sha, "bytes": nbytes, "rows": rows, "column": None}
    l1_sha = hashlib.sha256("\n".join(f"{p}\t{files[p]['sha256']}" for p in sorted(files)).encode()).hexdigest()
    manifest = {
        "l1_format": L1_FORMAT,
        "dataset_id": dataset_id,
        "contract_version": contract_version,
        "source_file": result.file,
        "source_file_sha256": source_file_sha256,
        "protocol_sha256": protocol_sha256,
        "cleaning_code_sha256": code_sha256(),
        "time_basis": "source_text_undeclared_tz",
        "raw_rows": result.n_rows,
        "unique_seconds": result.n_seconds,
        "window_first_text": str(result.ts_text[0]),
        "window_last_text": str(result.ts_text[-1]),
        "tier1_columns": list(result.columns),
        "resolutions": result.resolutions,
        "result_digest": result.digest(),
        "l1_sha256": l1_sha,
        "files": {p: files[p] for p in sorted(files)},
    }
    (out / "l1_manifest.json").write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return manifest


def verify_l1(out_dir: Path) -> list[str]:
    """Recompute every hash, size and row count against ``l1_manifest.json``. Empty list = verified."""
    out = Path(out_dir)
    manifest = json.loads((out / "l1_manifest.json").read_text(encoding="utf-8"))
    problems = []
    for rel, meta in manifest["files"].items():
        p = out / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
            continue
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            problems.append(f"sha256 mismatch {rel}")
        if len(data) != meta["bytes"]:
            problems.append(f"size mismatch {rel}")
        if data.count(b"\n") - 1 != meta["rows"]:
            problems.append(f"row count mismatch {rel}")
        if b"\r" in data:
            problems.append(f"CR found in {rel}")
    l1 = hashlib.sha256(
        "\n".join(f"{p}\t{manifest['files'][p]['sha256']}" for p in sorted(manifest["files"])).encode()
    ).hexdigest()
    if l1 != manifest["l1_sha256"]:
        problems.append("l1_sha256 does not match the file hashes")
    return problems
