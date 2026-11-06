"""The ``prepare`` stage: build the L1 TimeIndex of each registered file, apply the declared L2 policies in plan form,
stream every measurement column once to prove the reader, cross-check against the recorded findings, and write
auditable sidecars (time index, duplicate table, exclusion ledgers, provenance) under the RUN directory only.

It writes NO copy of the measurement values, performs no comparison, imports nothing from ``src``, and never writes under
the raw dataset directory (all paths go through ``safe_output_path``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from ..paths import DANISH_AAU_DIR
from ..runner import RunContext
from .channels import resolve_channels
from .config import DataConfig, load_data_config, resolve_duplicate_policy
from .discovery import discover_sources
from .errors import DataConfigError, DataLayerError
from .observations import ObservationStream
from .policies import DerivedView
from .provenance import ProvenanceLog, safe_output_path
from .reader import AauCsvReader
from .validation import EXPECTATION_SOURCE, cross_check, summarize_checks
from .vocabulary import TimestampState

DEFAULT_DATA_CONFIG = DANISH_AAU_DIR / "config" / "data.toml"

LAYER_MODEL = {
    "L0": "immutable raw CSV files (never opened for writing; fingerprinted before/after by the raw-data guard)",
    "L1": "original read-only observations: every row, source order, original values, TimeIndex annotations",
    "L2": "policy-controlled derived view: declared policies + exclusion ledgers; never replaces L1",
    "L3": "TwinGrid simulated series: separate namespace; meets L1/L2 only inside an alignment result (Phase 2 defines the container only)",
}


def _display(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _stream_check(reader: AauCsvReader, data_cfg: DataConfig) -> dict[str, Any]:
    """Stream every measurement column once (nothing is kept) to prove pass 2 on this file."""
    stream = ObservationStream.open(reader, reader.channels.measurement_columns)
    last_row, contiguous, n_nan = 0, True, 0
    for chunk in stream.iter_chunks():
        rows = chunk["_src_row"].to_numpy()
        contiguous &= bool(rows[0] == last_row + 1 and np.all(np.diff(rows) == 1))
        last_row = int(rows[-1])
        n_nan += int(chunk[list(stream.columns)].isna().to_numpy().sum())
    d = reader.diagnostics
    ts_col = reader.channels.timestamp_column
    streamed = list(stream.columns)
    return {
        "status": "ok",
        # Pass 2 compared the timestamp column and exactly these columns with the digests stored by pass 1.
        "content_integrity_verified_columns": len(streamed),
        "content_integrity_unverified_columns": [c for c in reader.source.columns if c != ts_col and c not in streamed],
        "rows_streamed": d["rows_streamed"],
        "chunks": d["chunks"],
        "chunksize": data_cfg.reader.chunksize,
        "src_rows_contiguous_in_source_order": contiguous and last_row == reader.require_index().n_rows,
        "n_nan_cells_after_conversion": n_nan,
        "non_numeric_cells": d["non_numeric_cells"],
        "non_numeric_by_column": d["non_numeric_by_column"],
        "first_non_numeric": d["first_non_numeric"],
    }


_KINDS = (
    ("time_index_", "time_index"),
    ("duplicate_groups_", "duplicate_groups"),
    ("exclusion_ledger_", "exclusion_ledger"),
    ("provenance_", "provenance"),
)


def describe_artifacts(run_dir: Path, names: list[str]) -> list[dict[str, Any]]:
    """Relative path, byte size and SHA-256 of every generated sidecar, sorted by path. Only files this stage wrote
    under the RUN directory are described; the raw dataset is never hashed as a generated artifact."""
    out = []
    for name in sorted(set(names)):
        path = run_dir / name
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        kind = next((k for prefix, k in _KINDS if name.startswith(prefix)), "other")
        out.append({"path": name, "kind": kind, "size_bytes": path.stat().st_size, "sha256": h.hexdigest()})
    return out


def _prepare_file(
    ctx: RunContext, data_cfg: DataConfig, source, duplicate_policy: str, outputs: list[str]
) -> dict[str, Any]:
    channels = resolve_channels(source, data_cfg)
    reader = AauCsvReader(source, channels, data_cfg)
    index = reader.build_time_index()
    window = reader.window_ns((data_cfg.window.start, data_cfg.window.end))
    entry: dict[str, Any] = {
        "relpath": source.relpath,
        "delimiter": reader.delimiter,
        "timestamp_column": channels.timestamp_column,
        "n_measurement_columns": len(channels.measurement_columns),
        "unclassified_measurement_columns": [
            c for c in channels.measurement_columns if not channels.info(c).classified
        ][:20],
        "time_index": index.summary(window),
    }
    if ctx.config.dataset.is_synthetic_fixture:
        entry["cross_check"] = {
            "status": "not_checked",
            "reason": "synthetic fixture: recorded findings describe the real files",
        }
    else:
        checks = cross_check(index, window)
        entry["cross_check"] = {
            "expectation_source": EXPECTATION_SOURCE,
            "summary": summarize_checks(checks),
            "checks": checks,
        }

    stream = ObservationStream.open(reader, columns=())
    view = DerivedView(
        ObservationStream.open(reader, columns=()),
        duplicate_policy,
        data_cfg.policies.empty_rows,
        data_cfg.policies.approved_sensitivity,
    )
    entry["l2_view"] = view.report()

    log = ProvenanceLog()
    log.add(stream.derivation_record())
    for record in view.derivation_records():
        log.add(record)

    if data_cfg.reader.verify_stream:
        try:
            entry["stream_check"] = _stream_check(reader, data_cfg)
        except DataLayerError as exc:
            entry["stream_check"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    run_dir = ctx.run_dir
    key = source.key
    if data_cfg.output.write_time_index:
        p = safe_output_path(run_dir / f"time_index_{key}.csv", ctx.raw_dir)
        index.to_frame().to_csv(p, index=False, lineterminator="\n")
        outputs.append(p.name)
    if data_cfg.output.write_duplicate_ledger and index.dup_group.max(initial=-1) >= 0:
        p = safe_output_path(run_dir / f"duplicate_groups_{key}.csv", ctx.raw_dir)
        index.duplicate_rows_frame().to_csv(p, index=False, lineterminator="\n")
        outputs.append(p.name)
    for ledger in view.ledgers:
        if ledger.count:
            p = ledger.write_csv(run_dir / f"exclusion_ledger_{key}_{ledger.policy_id}.csv", ctx.raw_dir)
            outputs.append(p.name)
    p = log.write_json(run_dir / f"provenance_{key}.json", ctx.raw_dir)
    outputs.append(p.name)
    return entry


def run_prepare(ctx: RunContext) -> dict[str, Any]:
    cfg_path = Path(ctx.data_config_path) if ctx.data_config_path else DEFAULT_DATA_CONFIG
    if not cfg_path.is_absolute():
        cfg_path = ctx.repo_root / cfg_path
    try:
        data_cfg = load_data_config(cfg_path)
        duplicate_policy, policy_note = resolve_duplicate_policy(data_cfg, ctx.config.policies.duplicate_timestamps)
    except DataConfigError as exc:
        return {"status": "failed", "problems": exc.problems}
    report: dict[str, Any] = {
        "status": "ok",
        "phase": 2,
        "layers": LAYER_MODEL,
        "data_config": _display(cfg_path, ctx.repo_root),
        "data_config_sha256": data_cfg.sha256,
        "timestamp_state": {
            "state": TimestampState.NAIVE_UNSPECIFIED.value,
            "phase1_declared_timezone": ctx.config.timestamps.timezone,
            "timezone_applied": False,
            "note": "timestamps are naive_unspecified; no timezone assumed and no UTC conversion; elapsed-time alignment only",
        },
        "policies": {
            "duplicates": duplicate_policy,
            "empty_rows": data_cfg.policies.empty_rows,
            "approved_sensitivity": list(data_cfg.policies.approved_sensitivity),
            "approved_bucket_reducers": list(data_cfg.policies.approved_bucket_reducers),
            "interpolation": "none",
            "note": policy_note,
        },
        "files": {},
        "missing_files": [],
        "outputs": [],
        "problems": [],
    }
    if not ctx.raw_dir.is_dir():
        report.update(status="failed", problems=["raw dataset directory does not exist"])
        return report
    sources = discover_sources(ctx.raw_dir, ctx.registry, missing_ok=True, delimiter=data_cfg.reader.delimiter)
    report["missing_files"] = [e.key for e in ctx.registry if e.key not in sources]
    if report["missing_files"]:
        report["status"] = "warn"
        report["problems"].append(f"registered file(s) not found: {report['missing_files']}")
    mismatches = 0
    for key, source in sources.items():
        try:
            entry = _prepare_file(ctx, data_cfg, source, duplicate_policy, report["outputs"])
        except DataLayerError as exc:
            report["files"][key] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            report["status"] = "failed"
            report["problems"].append(f"{key}: {exc}")
            continue
        entry["status"] = "ok"
        if entry.get("stream_check", {}).get("status") == "failed":
            entry["status"] = "failed"
            report["status"] = "failed"
            report["problems"].append(f"{key}: stream check failed")
        mismatches += entry["cross_check"].get("summary", {}).get("mismatch", 0)
        report["files"][key] = entry
    report["outputs"] = sorted(set(report["outputs"]))
    report["artifacts"] = describe_artifacts(ctx.run_dir, report["outputs"])
    if mismatches and report["status"] == "ok":
        report["status"] = "warn"
    if mismatches:
        report["problems"].append(
            f"{mismatches} cross-check value(s) differ from the recorded findings (reported, unverified)"
        )
    return report
