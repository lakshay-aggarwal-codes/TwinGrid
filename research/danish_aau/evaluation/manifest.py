"""Run manifest: what was run, on what, with which code, and what the run does NOT claim.

The manifest has a DETERMINISTIC CORE (config hash, registry hash, input fingerprints, code revision, evaluation
source fingerprint, harness version). The source fingerprint (``fingerprint.py``) hashes the relative path and content
of every evaluation source/config/doc file, tracked or untracked, so editing any of them changes the core hash. Two runs with the same config, inputs and code have the same ``manifest_core_sha256`` regardless of
when/where they ran; timestamps, argv and platform live outside the core. ``verify_manifest`` re-derives the core
hash, the config hash and (when the raw directory is available) the input fingerprints.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import HARNESS_PHASE, HARNESS_VERSION, _reuse, fingerprint
from .config import EvalConfig
from .guard import snapshot
from .paths import REPO_ROOT
from .registry import DEFAULT_REGISTRY, ExpectedFile, registry_sha256

MANIFEST_SCHEMA = "twingrid.aau_eval.manifest/2"
MANIFEST_NAME = "manifest.json"

CLAIMS = {
    "calibrated": False,
    "validated_against_real_data": False,
    "notice": (
        "Phases 1-2 harness (offline data engineering). No comparison, metric, calibration or validation has been produced. TwinGrid physics v2 is "
        "uncalibrated; timestamp overlap is not validation."
    ),
}


def inputs_from_inventory(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic, machine-independent fingerprints of the registered files that were found."""
    out = []
    for f in inventory["files"]:
        if f.get("relpath"):
            entry: dict[str, Any] = {"key": f["key"], "relpath": f["relpath"], "size_bytes": f["size_bytes"]}
            if f.get("sha256"):
                entry["sha256"] = f["sha256"]
            out.append(entry)
    return sorted(out, key=lambda e: e["key"])


def manifest_core(
    config: EvalConfig,
    inputs: list[dict[str, Any]],
    code_revision: str,
    registry: tuple[ExpectedFile, ...],
    source_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "harness_version": HARNESS_VERSION,
        "phase": HARNESS_PHASE,
        "config_sha256": config.sha256,
        "registry_sha256": registry_sha256(registry),
        "inputs": inputs,
        "code_revision": code_revision,
        "evaluation_source_fingerprint": source_fingerprint,
    }


CORE_KEYS = (
    "schema",
    "harness_version",
    "phase",
    "config_sha256",
    "registry_sha256",
    "inputs",
    "code_revision",
    "evaluation_source_fingerprint",
)


def core_hash(core: dict[str, Any]) -> str:
    return str(_reuse.canonical().sha256_json(core))


def build_manifest(
    *,
    config: EvalConfig,
    config_path: str,
    raw_dir: Path,
    raw_dir_source: str,
    inventory: dict[str, Any],
    stages: list[dict[str, Any]],
    status: str,
    run_id: str,
    created_utc: datetime,
    argv: list[str],
    repo_root: Path,
    registry: tuple[ExpectedFile, ...] = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    env = _reuse.repro_env()
    code = env.code_state(repo_root)
    inputs = inputs_from_inventory(inventory)
    source = fingerprint.compute(repo_root)
    core = manifest_core(config, inputs, str(code["code_revision"]), registry, source["sha256"])
    try:
        raw_rel = env.to_relative(raw_dir, repo_root)
    except Exception:  # noqa: BLE001 - outside the repo: record the folder name only, never an absolute path
        raw_rel = "<outside-repo>/" + Path(raw_dir).name
    return {
        **core,
        "determinism": {"manifest_core_sha256": core_hash(core)},
        "source_files": source["files"],
        "source_fingerprint_scheme": source["scheme"],
        "run": {"run_id": run_id, "created_utc": created_utc.isoformat(timespec="seconds"), "status": status},
        "config": config.portable_dict(),
        "config_path": config_path,
        "dataset": {
            "raw_dir": raw_rel,
            "raw_dir_source": raw_dir_source,
            "data_kind": "synthetic_fixture" if config.dataset.is_synthetic_fixture else "reported_real_dataset",
            "expectation_source": "context_doc_reported_unverified",
            "summary": inventory["summary"],
        },
        "readiness": config.readiness(),
        "stages": stages,
        "claims": dict(CLAIMS),
        "code": {k: code[k] for k in ("dirty", "dirty_diff_sha256", "code_revision_source")},
        "argv": env.scrub_argv(list(argv), repo_root),
        "platform": env.platform_info(),
    }


def write_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    path = Path(run_dir) / MANIFEST_NAME
    path.write_bytes(_reuse.canonical().canonical_bytes(manifest))
    return path


def _res(name: str, status: str, detail: str = "") -> dict[str, str]:
    return {"check": name, "status": status, "detail": detail}


def _stage_reports_check(manifest: dict[str, Any], run_dir: Path) -> dict[str, str]:
    """Each stage report written next to the manifest must still hash to the value recorded when it was written."""
    bad = []
    checked = 0
    for st in manifest.get("stages", []):
        if "report_sha256" not in st:
            continue
        f = run_dir / st.get("report_file", "")
        checked += 1
        if not f.is_file():
            bad.append(f"{st['report_file']}: missing")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != st["report_sha256"]:
            bad.append(f"{st['report_file']}: content changed")
    if bad:
        return _res("stage_reports_unchanged", "fail", "; ".join(bad))
    return _res(
        "stage_reports_unchanged",
        "pass" if checked else "skipped",
        "" if checked else "no stage report hashes recorded",
    )


def _artifacts_check(manifest: dict[str, Any], run_dir: Path) -> dict[str, str]:
    """Every generated sidecar listed by a stage report must exist with the recorded size and SHA-256, and the run directory
    must contain nothing else except the manifest and the stage reports named in it (detects modified, missing, added)."""
    expected = {MANIFEST_NAME}
    problems: list[str] = []
    n = 0
    for st in manifest.get("stages", []):
        report_file = st.get("report_file")
        if not report_file:
            continue
        expected.add(report_file)
        f = run_dir / report_file
        if not f.is_file():
            continue  # reported by stage_reports_unchanged
        try:
            report = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for art in report.get("artifacts") or []:
            rel = str(art.get("path", ""))
            if not rel or rel.startswith(("/", "\\")) or ".." in rel.split("/") or ":" in rel:
                problems.append(f"{rel!r}: not a safe relative path")
                continue
            expected.add(rel)
            n += 1
            target = run_dir / rel
            if not target.is_file():
                problems.append(f"{rel}: missing")
            elif target.stat().st_size != art.get("size_bytes"):
                problems.append(f"{rel}: size {target.stat().st_size} != {art.get('size_bytes')}")
            elif hashlib.sha256(target.read_bytes()).hexdigest() != art.get("sha256"):
                problems.append(f"{rel}: content changed")
    present = {p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file()}
    problems += [f"{rel}: added (not listed by any stage report)" for rel in sorted(present - expected)]
    if problems:
        return _res("artifacts_unchanged", "fail", "; ".join(problems))
    return _res("artifacts_unchanged", "pass", f"{n} generated artifact(s) verified")


def verify_manifest(path: Path, raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> list[dict[str, str]]:
    """Re-derive what can be re-derived. Status per check: pass | fail | skipped."""
    results: list[dict[str, str]] = []
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [_res("manifest_readable", "fail", str(exc))]
    results.append(_res("manifest_readable", "pass"))
    results.append(
        _res("schema", "pass" if manifest.get("schema") == MANIFEST_SCHEMA else "fail", str(manifest.get("schema")))
    )

    try:
        core = {k: manifest[k] for k in CORE_KEYS}
        ok = core_hash(core) == manifest["determinism"]["manifest_core_sha256"]
        results.append(
            _res("core_hash", "pass" if ok else "fail", "" if ok else "stored core hash does not match its fields")
        )
    except (KeyError, TypeError) as exc:
        results.append(_res("core_hash", "fail", f"missing field {exc}"))

    try:
        recomputed = str(_reuse.canonical().sha256_json(manifest["config"]))
        ok = recomputed == manifest["config_sha256"]
        results.append(
            _res("config_hash", "pass" if ok else "fail", "" if ok else "stored config differs from config_sha256")
        )
    except (KeyError, TypeError) as exc:
        results.append(_res("config_hash", "fail", f"missing field {exc}"))

    try:
        stored_files = manifest["source_files"]
        consistent = fingerprint.fingerprint_of(stored_files) == manifest["evaluation_source_fingerprint"]
        results.append(
            _res(
                "source_fingerprint_consistent",
                "pass" if consistent else "fail",
                "" if consistent else "source_files do not hash to evaluation_source_fingerprint",
            )
        )
        try:
            diff = fingerprint.diff_files(stored_files, fingerprint.hash_source_files(Path(repo_root)))
        except (fingerprint.FingerprintError, OSError) as exc:
            results.append(_res("source_unchanged", "fail", str(exc)))
        else:
            changed = [f"{k}: {', '.join(v[:5])}" for k, v in diff.items() if v]
            results.append(
                _res(
                    "source_unchanged",
                    "fail" if changed else "pass",
                    "evaluation source differs since the run - " + "; ".join(changed) if changed else "",
                )
            )
    except (KeyError, TypeError) as exc:
        results.append(_res("source_fingerprint_consistent", "fail", f"missing field {exc}"))

    results.append(_stage_reports_check(manifest, Path(path).parent))
    results.append(_artifacts_check(manifest, Path(path).parent))

    claims = manifest.get("claims", {})
    honest = claims.get("calibrated") is False and claims.get("validated_against_real_data") is False
    results.append(
        _res(
            "claims_not_overstated",
            "pass" if honest else "fail",
            "" if honest else "manifest claims calibration/validation",
        )
    )

    if raw_dir is None or not Path(raw_dir).is_dir():
        results.append(_res("inputs_unchanged", "skipped", "raw dataset directory not available"))
    else:
        stamps = snapshot(Path(raw_dir))
        bad = []
        for entry in manifest.get("inputs", []):
            stamp = stamps.get(entry["relpath"])
            if stamp is None:
                bad.append(f"{entry['relpath']}: missing")
            elif stamp.size != entry["size_bytes"]:
                bad.append(f"{entry['relpath']}: size {stamp.size} != {entry['size_bytes']}")
            elif entry.get("sha256"):
                actual = str(_reuse.canonical().sha256_raw_file(Path(raw_dir) / entry["relpath"]))
                if actual != entry["sha256"]:
                    bad.append(f"{entry['relpath']}: sha256 differs")
        results.append(_res("inputs_unchanged", "fail" if bad else "pass", "; ".join(bad)))
    return results
