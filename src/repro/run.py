"""Run lifecycle: ``reports/runs/<run_id>/{manifest.json,status.json,results.json,tables/,figures/,REPORT.md}``.

Order of events (contract section 11):

1. every input is hashed (configs, dataset manifest, pre-registration, lock file, artifacts) and the
   code revision (+dirty) is recorded;
2. the run directory is created exclusively; ``manifest.json`` is written with ``result_sha256 = null``
   and ``status.json`` says ``running``;
3. the experiment runs with explicit, per-stream ``numpy.random.Generator`` objects; the global
   numpy/random state must be untouched afterwards; optionally it runs twice and the canonical
   results must be identical (determinism canary);
4. ``results.json`` is written in canonical form, its SHA-256 goes into the manifest;
5. tables, figures and ``REPORT.md`` are generated *from results.json* by ``report.py``;
6. ``status.json`` becomes ``completed`` (or ``failed`` with the error; the directory is kept).

A dirty tree is recorded (``dirty = true``) and the run still executes -- that is what development
needs -- but such a run can never support a promotion (``promotion.py``).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from . import DETERMINISM_LEVEL, RESULTS_SCHEMA, RUN_MANIFEST_VERSION, env, experiments, report
from .canonical import (
    DEFAULT_SIG_DIGITS,
    canonical_bytes,
    round_sig,
    sha256_bytes,
    sha256_input_file,
    sha256_raw_file,
)
from .rng import RngFactory, forbid_global_rng

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
STATES = ("running", "completed", "failed")
LOCK_FILE = "requirements.lock"
_ABS_PATH_IN_TEXT = re.compile(r"(?:[A-Za-z]:\\[^\s'\"]+|/(?:[\w.-]+/)+[\w.-]*)")
REQUIRED_MANIFEST_FIELDS = (
    "manifest_version", "run_id", "experiment", "started_at_utc", "command", "code_revision", "dirty",
    "dirty_diff_sha256", "code_revision_source", "lock_path", "lock_sha256", "platform", "config_files",
    "primary_config", "dataset_manifest_path", "dataset_manifest_sha256", "physics_version", "physics_params_hash",
    "environment_version", "observation_schema_hash", "action_schema_hash", "action_semantics_version",
    "reward_version", "safety_envelope_version", "input_cadence_s", "scenario_set_id", "split_id", "seeds",
    "artifacts", "prereg_path", "prereg_sha256", "result_sha256", "determinism", "results_schema",
)  # fmt: skip


class RunError(RuntimeError):
    """The run could not be started or completed (message is safe to print)."""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` so a reader never sees a partial file (temp file + ``os.replace``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def scrub_message(text: str, limit: int = 500) -> str:
    """An error message with absolute paths removed (manifests and status files carry none)."""
    return _ABS_PATH_IN_TEXT.sub("<path>", text)[:limit]


# ----------------------------------------------------------------------------- request / outcome


@dataclass
class RunRequest:
    experiment: str
    config_paths: Sequence[str]
    seeds: Sequence[int] | None = None
    dataset_manifest: str | None = None
    prereg: str | None = None
    artifacts: Sequence[str] = ()
    scenario_set_id: str | None = None
    split_id: str | None = None
    run_id: str | None = None
    runs_dir: str = env.RUNS_SUBDIR
    check_determinism: bool = False
    require_clean: bool = False
    float_sig_digits: int = DEFAULT_SIG_DIGITS
    argv: Sequence[str] = field(default_factory=tuple)


@dataclass
class RunOutcome:
    run_id: str
    run_dir: Path
    state: str
    error: str | None = None


# ----------------------------------------------------------------------------- inputs


def _hash_input(rel: str, root: Path, what: str, *, text: bool = True) -> str:
    path = env.resolve_in_root(rel, root)
    if not path.is_file():
        raise RunError(f"{what} {rel} does not exist")
    return sha256_input_file(path) if text else sha256_raw_file(path)


def _relative_input(path: str, root: Path, what: str) -> str:
    try:
        return env.to_relative(path, root)
    except env.PathOutsideRoot:
        raise RunError(
            f"{what} {Path(path).name} is outside the project root; copy it into the repository first"
        ) from None


def _load_registry_entries(root: Path) -> list[dict[str, Any]]:
    path = root / "models" / "registry.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RunError("models/registry.json is missing or unreadable, so --artifact cannot be resolved") from None
    return data["artifacts"] if isinstance(data, dict) else data


def resolve_artifacts(model_ids: Sequence[str], root: Path) -> list[dict[str, Any]]:
    """Registry entries for ``model_ids`` with the SHA-256 of each file on disk NOW; the disk hash must
    equal the registry's. Status is recorded as information, not enforced (evaluation also runs on candidates)."""
    if not model_ids:
        return []
    entries = _load_registry_entries(root)
    out = []
    for model_id in sorted(set(model_ids)):
        entry = next((e for e in reversed(entries) if e.get("model_id") == model_id), None)
        if entry is None:
            raise RunError(f"artifact {model_id!r} is not in models/registry.json")
        files: dict[str, str] = {}
        for rel, info in sorted((entry.get("files") or {}).items()):
            actual = _hash_input(rel, root, f"artifact file of {model_id}", text=False)
            if info.get("sha256") != actual:
                raise RunError(f"artifact {model_id}: {rel} differs from the registry hash; refusing to run on it")
            files[rel] = actual
        if not files:
            raise RunError(f"artifact {model_id!r} lists no files")
        out.append({"model_id": model_id, "status": entry.get("status"), "files": files})
    return out


def _lineage() -> dict[str, Any]:
    keys = (
        "physics_version", "physics_params_hash", "environment_version", "observation_schema_hash",
        "action_schema_hash", "action_semantics_version", "reward_version", "safety_envelope_version", "input_cadence_s",
    )  # fmt: skip
    try:
        from src import versions

        values = versions.running_compat_values()
        return {k: values[k] for k in keys}
    except Exception as exc:  # noqa: BLE001 - recorded, never silent
        return {**{k: None for k in keys}, "lineage_error": f"{type(exc).__name__}"}


def resolve_seeds(request: RunRequest, config: dict[str, Any]) -> list[int]:
    raw = list(request.seeds) if request.seeds else config.get("seeds")
    if (
        not isinstance(raw, list)
        or not raw
        or not all(isinstance(s, int) and not isinstance(s, bool) and s >= 0 for s in raw)
    ):
        raise RunError(
            "seeds must be given (--seed N, repeatable, or a 'seeds' list in the config) as non-negative integers"
        )
    if len(set(raw)) != len(raw):
        raise RunError("seeds must be distinct")
    return [int(s) for s in raw]


def build_manifest(request: RunRequest, root: Path, run_id: str, started_at: str, seeds: list[int]) -> dict[str, Any]:
    if not request.config_paths:
        raise RunError("at least one --config file is required")
    config_files: dict[str, str] = {}
    for p in request.config_paths:
        rel = _relative_input(p, root, "config file")
        config_files[rel] = _hash_input(rel, root, "config file")
    dataset_rel = (
        _relative_input(request.dataset_manifest, root, "dataset manifest") if request.dataset_manifest else None
    )
    prereg_rel = _relative_input(request.prereg, root, "pre-registration") if request.prereg else None
    lock = root / LOCK_FILE
    state = env.code_state(root)
    return {
        "manifest_version": RUN_MANIFEST_VERSION,
        "run_id": run_id,
        "experiment": request.experiment,
        "started_at_utc": started_at,
        "command": env.scrub_argv(list(request.argv), root),
        **state,
        "lock_path": LOCK_FILE if lock.is_file() else None,
        "lock_sha256": sha256_input_file(lock) if lock.is_file() else None,
        "platform": env.platform_info(),
        "config_files": config_files,
        "primary_config": next(iter(config_files)),
        "dataset_manifest_path": dataset_rel,
        "dataset_manifest_sha256": _hash_input(dataset_rel, root, "dataset manifest") if dataset_rel else None,
        **_lineage(),
        "scenario_set_id": request.scenario_set_id,
        "split_id": request.split_id,
        "seeds": seeds,
        "artifacts": resolve_artifacts(request.artifacts, root),
        "prereg_path": prereg_rel,
        "prereg_sha256": _hash_input(prereg_rel, root, "pre-registration") if prereg_rel else None,
        "result_sha256": None,
        "determinism": {
            "level": DETERMINISM_LEVEL,
            "float_sig_digits": request.float_sig_digits,
            "checked_in_run": bool(request.check_determinism),
        },
        "results_schema": RESULTS_SCHEMA,
    }


# ----------------------------------------------------------------------------- execution


def execute_experiment(
    name: str,
    config: dict[str, Any],
    seeds: list[int],
    *,
    digits: int = DEFAULT_SIG_DIGITS,
    check_determinism: bool = False,
) -> dict[str, Any]:
    """Run the registered experiment and return the validated, rounded results object.

    Raises if the global RNG was used, if the output is not valid results, or (with
    ``check_determinism``) if a second execution does not give byte-identical canonical results.
    """
    fn = experiments.get(name)

    def once() -> dict[str, Any]:
        with forbid_global_rng():
            raw = fn(json.loads(json.dumps(config)), list(seeds), RngFactory())
        results = round_sig(raw, digits)
        report.validate_results(results)
        if results["experiment"] != name:
            raise RunError(f"experiment returned results labelled {results['experiment']!r}, expected {name!r}")
        if results["seeds"] != list(seeds):
            raise RunError("experiment results do not record the seeds it was given")
        return results

    first = once()
    if check_determinism:
        second = once()
        if canonical_bytes(first) != canonical_bytes(second):
            raise RunError(
                "experiment is not deterministic: two executions with the same config and seeds gave different results"
            )
    return first


def _make_run_id(request: RunRequest, config_sha: str, seeds: list[int], started_at: str) -> str:
    if request.run_id is not None:
        if not RUN_ID_RE.match(request.run_id):
            raise RunError("run id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
        return request.run_id
    stamp = started_at.replace("-", "").replace(":", "")
    tag = sha256_bytes((config_sha + ",".join(map(str, seeds))).encode())[:8]
    return f"{request.experiment}-{stamp}-{tag}"


def _write_status(
    run_dir: Path, run_id: str, state: str, started: str, error: str | None = None, clock: Callable[[], str] = now_utc
) -> None:
    now = clock()
    status = {
        "run_id": run_id,
        "state": state,
        "started_at_utc": started,
        "updated_at_utc": now,
        "finished_at_utc": now if state in ("completed", "failed") else None,
        "error": error,
    }
    write_atomic(run_dir / "status.json", canonical_bytes(status))


def run(request: RunRequest, root: Path = env.PROJECT_ROOT, *, clock: Callable[[], str] = now_utc) -> RunOutcome:
    """Execute a run end to end. Raises RunError for problems found BEFORE the run directory exists
    (bad inputs, dirty tree with ``require_clean``, id clash); anything after that is recorded as
    ``failed`` in ``status.json`` and returned in the outcome."""
    root = Path(root).resolve()
    if not request.experiment:
        raise RunError("an experiment name is required")
    experiments.get(request.experiment)  # unknown -> UnknownExperiment before anything is written
    started = clock()
    first_cfg = _relative_input(request.config_paths[0], root, "config file") if request.config_paths else None
    if first_cfg is None:
        raise RunError("at least one --config file is required")
    config_path = env.resolve_in_root(first_cfg, root)
    if not config_path.is_file():
        raise RunError(f"config file {first_cfg} does not exist")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except ValueError:
        raise RunError(f"config file {first_cfg} is not valid JSON") from None
    if not isinstance(config, dict):
        raise RunError("the primary config must be a JSON object")
    seeds = resolve_seeds(request, config)
    run_id = _make_run_id(request, sha256_input_file(config_path), seeds, started)
    runs_root = env.resolve_in_root(env.to_relative(request.runs_dir, root), root)
    run_dir = runs_root / run_id
    manifest = build_manifest(request, root, run_id, started, seeds)
    if request.require_clean and manifest["dirty"]:
        raise RunError(
            f"the working tree is dirty ({manifest['code_revision_source']}); commit first or drop --require-clean"
        )
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise RunError(f"run directory {run_id} already exists; run ids are never reused") from None

    write_atomic(run_dir / "manifest.json", canonical_bytes(manifest))
    _write_status(run_dir, run_id, "running", started, clock=clock)
    try:
        results = execute_experiment(
            request.experiment,
            config,
            seeds,
            digits=request.float_sig_digits,
            check_determinism=request.check_determinism,
        )
        results_bytes = canonical_bytes(results)
        write_atomic(run_dir / "results.json", results_bytes)
        manifest["result_sha256"] = sha256_bytes(results_bytes)
        write_atomic(run_dir / "manifest.json", canonical_bytes(manifest))
        for rel, text in report.render_all(results).items():
            write_atomic(run_dir / rel, text.encode("utf-8"))
        _write_status(run_dir, run_id, "completed", started, clock=clock)
        return RunOutcome(run_id, run_dir, "completed")
    except Exception as exc:  # noqa: BLE001 - every failure is recorded in status.json
        message = f"{type(exc).__name__}: {scrub_message(str(exc))}"
        _write_status(run_dir, run_id, "failed", started, error=message, clock=clock)
        (run_dir / "error.txt").write_text(scrub_message(traceback.format_exc(), 6000), encoding="utf-8")
        return RunOutcome(run_id, run_dir, "failed", message)


# ----------------------------------------------------------------------------- reading runs


def run_dir_for(root: Path, run_id: str, runs_dir: str = env.RUNS_SUBDIR) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise RunError("run id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
    return env.resolve_in_root(runs_dir, root) / run_id


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
