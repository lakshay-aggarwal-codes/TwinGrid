"""Stage pipeline.

A stage is a small object with ``name`` and ``run(ctx) -> dict``. The returned dict must contain
``status`` in {"ok", "warn", "failed"}; everything else is the stage's own report, written to
``<run_dir>/stage_<name>.json``. Later phases add stages by calling ``register_stage``; the runner, the raw-data
guard and the manifest do not change.

Exit semantics (used by the CLI): 0 = every stage ok (or warn without --strict); 2 = a stage failed, a stage
raised, or the raw dataset directory changed during the run.
"""

from __future__ import annotations

import hashlib
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from . import _reuse
from .config import EvalConfig
from .guard import RawDataGuard, RawDataModified
from .manifest import build_manifest, write_manifest
from .paths import ensure_output_dir_safe
from .registry import DEFAULT_REGISTRY, ExpectedFile

RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


@dataclass
class RunContext:
    config: EvalConfig
    config_path: str
    repo_root: Path
    raw_dir: Path
    raw_dir_source: str
    run_dir: Path
    run_id: str
    registry: tuple[ExpectedFile, ...] = DEFAULT_REGISTRY
    count_rows: bool = False
    strict: bool = False
    shared: dict[str, Any] = field(default_factory=dict)  # stage -> stage report, for later stages
    data_config_path: str = ""  # Phase 2: optional path of the data-layer config (empty = config/data.toml)


class Stage(Protocol):
    name: str

    def run(self, ctx: RunContext) -> dict[str, Any]: ...


_STAGES: dict[str, Stage] = {}


def register_stage(stage: Stage) -> None:
    _STAGES[stage.name] = stage


def unregister_stage(name: str) -> None:
    _STAGES.pop(name, None)


def available_stages() -> list[str]:
    return sorted(_STAGES)


def make_run_id(config: EvalConfig, now: datetime) -> str:
    return f"{now:%Y%m%dT%H%M%SZ}_{config.sha256[:8]}"


def run_pipeline(
    ctx: RunContext, stage_names: list[str], argv: list[str], *, now: datetime | None = None
) -> tuple[dict[str, Any], int]:
    """Run ``stage_names`` in order. Returns (manifest, exit_code). The manifest is written even on failure."""
    unknown = [n for n in stage_names if n not in _STAGES]
    if unknown:
        raise KeyError(f"unknown stage(s) {unknown}; available: {available_stages()}")
    if not RUN_ID.match(ctx.run_id):
        raise ValueError("run id must match [A-Za-z0-9_.-]{1,96}")
    ensure_output_dir_safe(ctx.run_dir, ctx.raw_dir, ctx.repo_root)
    if ctx.run_dir.exists() and any(ctx.run_dir.iterdir()):
        raise FileExistsError(
            f"run directory {ctx.run_dir.name!r} already exists and is not empty; choose another --run-id"
        )
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    created = now or datetime.now(timezone.utc)
    canonical = _reuse.canonical()

    stage_records: list[dict[str, Any]] = []
    status = "ok"
    guard = RawDataGuard(ctx.raw_dir)
    try:
        with guard:
            for name in stage_names:
                try:
                    report = dict(_STAGES[name].run(ctx))
                    st = report.get("status", "failed")
                    if st not in ("ok", "warn", "failed"):
                        report["status"], st = "failed", "failed"
                        report["error"] = "stage returned an invalid status"
                except Exception as exc:  # noqa: BLE001 - recorded, then the pipeline stops
                    st = "failed"
                    report = {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=5),
                    }
                if st == "warn" and ctx.strict:
                    report["status"], st = "failed", "failed"
                    report["strict_note"] = "warning treated as failure by --strict"
                ctx.shared[name] = report
                report_bytes = canonical.canonical_bytes(report)
                (ctx.run_dir / f"stage_{name}.json").write_bytes(report_bytes)
                stage_records.append(
                    {
                        "name": name,
                        "status": st,
                        "report_file": f"stage_{name}.json",
                        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                    }
                )
                if st == "failed":
                    status = "failed"
                    break
                if st == "warn" and status == "ok":
                    status = "warn"
    except RawDataModified as exc:
        status = "failed_raw_data_modified"
        stage_records.append({"name": "raw_data_guard", "status": "failed", "diff": exc.diff})

    inventory = ctx.shared.get("preflight", {}).get("inventory")
    if inventory is None:  # a run without preflight still records the (header-only) facts about its inputs
        from .inventory import inventory_raw

        inventory = inventory_raw(ctx.raw_dir, ctx.registry, count_rows=False, hash_files=False)
    manifest = build_manifest(
        config=ctx.config,
        config_path=ctx.config_path,
        raw_dir=ctx.raw_dir,
        raw_dir_source=ctx.raw_dir_source,
        inventory=inventory,
        stages=stage_records,
        status=status,
        run_id=ctx.run_id,
        created_utc=created,
        argv=argv,
        repo_root=ctx.repo_root,
        registry=ctx.registry,
    )
    write_manifest(ctx.run_dir, manifest)
    return manifest, (0 if status in ("ok", "warn") else 2)
