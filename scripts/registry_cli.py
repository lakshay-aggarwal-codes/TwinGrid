#!/usr/bin/env python3
"""Model registry transitions (T30; roadmap 10.3, 10.4, 13.5). The ONLY place a model's ``status`` changes.

    python scripts/registry_cli.py list
    python scripts/registry_cli.py promote    <model_id> --run reports/runs/<run_id>
    python scripts/registry_cli.py reject     <model_id> --run reports/runs/<run_id> --reason "..."
    python scripts/registry_cli.py quarantine <model_id> --reason "..."
    python scripts/registry_cli.py retire     <model_id> --reason "..."

Statuses: ``candidate, promoted, quarantined, rejected, retired``; only ``promoted`` loads in the API.

* ``promote`` refuses unless EVERY check passes: candidate in status ``candidate`` · evaluation run completed and its
  ``results.json`` hash matches its manifest · the pre-registration hash is the locked one AND the one the run used ·
  clean tree (40-hex ``code_revision``, not dirty) · outcome A with every criterion met and ``promotable`` · the
  files in the registry entry are the files that were evaluated and still match their recorded sha256 · the candidate
  is compatible with the running system (10.2 step 2: every field must be present and equal; a field whose running
  value cannot be determined counts as a failure) and carries no ``compat_waiver``. All failures are listed.
* ``reject`` moves a ``candidate`` to ``quarantined`` with a mandatory reason and the run id (10.3: a rejected
  artifact is quarantined, never silently kept loadable).
* Every transition appends to ``history[]``; earlier entries are never altered (checked before every write). The file
  is replaced atomically (``os.replace``, previous contents kept in ``.bak``).
* Each transition also tries to write a DB audit row (``audit_logs``); if the database is unreachable the transition
  still happens and the history entry records ``audit.written = false`` with the reason.
* If no candidate qualifies the recorded result is "no promotable policy".
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import eval_policies as ep  # noqa: E402  (scripts/eval_policies.py)

REGISTRY_PATH = REPO_ROOT / "models" / "registry.json"
STATUSES = ("candidate", "promoted", "quarantined", "rejected", "retired")
# action -> (allowed from-statuses, resulting status)
TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "promote": (("candidate",), "promoted"),
    "reject": (("candidate",), "quarantined"),
    "quarantine": (("candidate", "promoted"), "quarantined"),
    "retire": (("promoted",), "retired"),
}
# Fields that must equal the running values (10.2 step 2).
COMPAT_FIELDS = (
    "physics_version",
    "physics_params_hash",
    "environment_version",
    "observation_schema_hash",
    "action_schema_hash",
    "action_semantics_version",
    "reward_version",
    "safety_envelope_version",
    "input_cadence_s",
)


class RegistryError(RuntimeError):
    """A transition was refused. ``failures`` lists every reason."""

    def __init__(self, message: str, failures: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.failures = list(failures)


# ----------------------------------------------------------------------------- registry file
def load_registry(path: Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise RegistryError(f"{path} is not a JSON list of objects")
    return data


def write_registry_atomic(path: Path, entries: list[dict[str, Any]]) -> None:
    """Temp file in the same directory, fsync, copy of the old file to ``.bak``, then ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(entries, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def find_entry(entries: Sequence[Mapping[str, Any]], model_id: str) -> int:
    hits = [i for i, e in enumerate(entries) if e.get("model_id") == model_id]
    if not hits:
        raise RegistryError(f"no registry entry with model_id {model_id!r}")
    if len(hits) > 1:
        raise RegistryError(f"model_id {model_id!r} is not unique in the registry")
    return hits[0]


def assert_history_unaltered(old: Sequence[Mapping[str, Any]], new: Sequence[Mapping[str, Any]]) -> None:
    """The history of every entry may only grow: its old items must be a byte-identical prefix of the new ones."""
    if len(new) != len(old):
        raise RegistryError("a transition may not add or remove registry entries")
    for before, after in zip(old, new, strict=True):
        h0, h1 = before.get("history", []), after.get("history", [])
        if h1[: len(h0)] != h0:
            raise RegistryError(f"history of {before.get('model_id')!r} was altered")


# ----------------------------------------------------------------------------- compatibility (10.2 step 2)
def running_compat_values() -> dict[str, Any]:
    """The values of the running system for ``COMPAT_FIELDS``. A field this tree cannot determine is ``None``, and
    ``None`` never equals anything: promotion fails closed until T19/T27 provide the values."""
    values: dict[str, Any] = {f: None for f in COMPAT_FIELDS}
    try:
        from src import versions

        values["physics_version"] = versions.PHYSICS_VERSION
    except Exception:
        pass
    try:  # the shipped environment's spaces: hashes of observation / action schema
        import hashlib

        from src.optimizer import DataCentreEnv

        env = DataCentreEnv(seed=0)

        def space_hash(space: Any) -> str:
            doc = {"shape": list(space.shape), "low": [float(x) for x in space.low.ravel()],
                   "high": [float(x) for x in space.high.ravel()]}  # fmt: skip
            return hashlib.sha256(ep.canonical_json(doc).encode()).hexdigest()

        values["observation_schema_hash"] = space_hash(env.observation_space)
        values["action_schema_hash"] = space_hash(env.action_space)
        env.close()
    except Exception:
        pass
    return values


def check_compat(entry: Mapping[str, Any], running: Mapping[str, Any]) -> list[str]:
    failures = []
    if entry.get("compat_waiver"):
        failures.append("compat_waiver present: a waived candidate cannot be promoted")
    for field in COMPAT_FIELDS:
        have, want = entry.get(field), running.get(field)
        if want is None:
            failures.append(f"compat {field}: running value unavailable (cannot verify)")
        elif have is None:
            failures.append(f"compat {field}: candidate manifest lacks it")
        elif have != want:
            failures.append(f"compat {field}: candidate {have!r} != running {want!r}")
    return failures


# ----------------------------------------------------------------------------- promotion checks
def _load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def file_hashes_of_entry(entry: Mapping[str, Any], root: Path) -> tuple[dict[str, str], list[str]]:
    """basename -> recorded sha256 for the entry's files, plus problems (missing file, recorded != actual)."""
    out: dict[str, str] = {}
    problems: list[str] = []
    for rel, meta in (entry.get("files") or {}).items():
        recorded = meta.get("sha256") if isinstance(meta, Mapping) else None
        out[Path(rel).name] = str(recorded)
        path = Path(root) / rel
        if not path.is_file():
            problems.append(f"file {rel} is missing")
        elif recorded and ep.sha256_file(path) != recorded:
            problems.append(f"file {rel} no longer matches its recorded sha256")
    return out, problems


def promotion_failures(
    entry: Mapping[str, Any],
    run_dir: Path,
    *,
    running: Mapping[str, Any] | None = None,
    verify_prereg: Callable[[], Mapping[str, Any]] | None = None,
    root: Path = REPO_ROOT,
) -> list[str]:
    """Every reason ``entry`` may not be promoted on the evidence in ``run_dir`` (empty list = promotable)."""
    failures: list[str] = []
    run_dir = Path(run_dir)
    if entry.get("status") != "candidate":
        failures.append(f"status is {entry.get('status')!r}, not 'candidate'")

    needed = ("status.json", "manifest.json", "results.json", "decision.json")
    missing = [n for n in needed if not (run_dir / n).is_file()]
    if missing:
        return failures + [f"run is incomplete: missing {missing}"]
    status, manifest, results, decision = (_load(run_dir / n) for n in needed)

    if status.get("status") != "completed":
        failures.append(f"run status is {status.get('status')!r}, not 'completed'")
    if ep.sha256_file(run_dir / "results.json") != manifest.get("result_sha256"):
        failures.append("results.json does not match the hash in manifest.json")
    if decision.get("result_sha256") != manifest.get("result_sha256"):
        failures.append("decision.json was not produced from this results.json")
    if results.get("decision", {}).get("outcome") != decision.get("outcome"):
        failures.append("decision.json disagrees with results.json")

    try:
        locked = (verify_prereg or ep.verify_prereg)()
        locked_sha = locked["preregistration_sha256"]
        for label, value in (
            ("manifest", manifest.get("prereg_sha256")),
            ("results", results.get("prereg_sha256")),
            ("decision", decision.get("prereg_sha256")),
        ):
            if value != locked_sha:
                failures.append(f"pre-registration hash mismatch: {label} has {value}, locked is {locked_sha}")
    except ep.EvalProtocolError as exc:
        failures.append(f"pre-registration cannot be verified: {exc}")

    rev = str(manifest.get("code_revision", ""))
    if manifest.get("dirty") is not False or not re.fullmatch(r"[0-9a-f]{40}", rev):
        failures.append(f"run is not from a clean tree (code_revision={rev!r}, dirty={manifest.get('dirty')!r})")
    if not ep.manifest_is_complete(manifest):
        failures.append("run manifest is incomplete")

    if decision.get("outcome") != "A":
        failures.append(f"outcome is {decision.get('outcome')!r}, not 'A'")
    failed = [c["id"] for c in decision.get("criteria", []) if not c.get("passed")]
    failed += [g["id"] for g in decision.get("gates", []) if not g.get("passed")]
    if failed:
        failures.append(f"criteria/gates not met: {failed}")
    if not decision.get("criteria"):
        failures.append("decision records no criteria")
    if decision.get("promotable") is not True or decision.get("registry_action") != "promote":
        failures.append("decision.json does not say promote")

    if decision.get("model_id") not in (None, entry.get("model_id")):
        failures.append(f"run evaluated model {decision.get('model_id')!r}, not {entry.get('model_id')!r}")
    evaluated = decision.get("candidate_files") or {}
    have, problems = file_hashes_of_entry(entry, root)
    failures += problems
    if not evaluated:
        failures.append("the run recorded no candidate files")
    elif {k: v for k, v in have.items() if k in evaluated} != evaluated or set(have) != set(evaluated):
        failures.append("the registry entry's files are not the files that were evaluated")

    failures += check_compat(entry, running if running is not None else running_compat_values())
    return failures


# ----------------------------------------------------------------------------- audit row
def write_audit_row(action: str, model_id: str, details: Mapping[str, Any]) -> dict[str, Any]:
    """Best effort: one ``audit_logs`` row. Returns ``{"written": bool, "reason": str | None}``; never raises."""
    if not os.getenv("DATABASE_URL", "").strip():
        return {"written": False, "reason": "DATABASE_URL not set"}

    async def _write() -> None:
        from api.services.audit_service import log_action
        from database import get_session

        async with get_session() as session:
            await log_action(
                session, action=f"model_registry.{action}", resource_type="model", resource_id=model_id,
                details=dict(details),
            )  # fmt: skip

    try:
        asyncio.run(asyncio.wait_for(_write(), timeout=10))
        return {"written": True, "reason": None}
    except Exception as exc:  # unreachable DB, missing drivers, missing table...
        return {"written": False, "reason": f"{type(exc).__name__}"}


# ----------------------------------------------------------------------------- transitions
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def transition(
    action: str,
    model_id: str,
    *,
    registry_path: Path = REGISTRY_PATH,
    run_dir: Path | None = None,
    reason: str | None = None,
    actor: str | None = None,
    running: Mapping[str, Any] | None = None,
    verify_prereg: Callable[[], Mapping[str, Any]] | None = None,
    audit: Callable[[str, str, Mapping[str, Any]], dict[str, Any]] | None = None,
    root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Apply one registry transition or raise RegistryError. Returns the updated entry."""
    if action not in TRANSITIONS:
        raise RegistryError(f"unknown action {action!r}")
    allowed_from, to_status = TRANSITIONS[action]
    entries = load_registry(registry_path)
    idx = find_entry(entries, model_id)
    entry = entries[idx]
    current = entry.get("status")
    if current not in allowed_from:
        raise RegistryError(f"cannot {action} a model whose status is {current!r} (allowed from {list(allowed_from)})")
    if action in ("reject", "quarantine", "retire") and not (reason and reason.strip()):
        raise RegistryError(f"{action} requires a reason")

    run_id = None
    prereg_sha = None
    if action == "promote":
        if run_dir is None:
            raise RegistryError("promote needs --run <evaluation run directory>")
        failures = promotion_failures(entry, Path(run_dir), running=running, verify_prereg=verify_prereg, root=root)
        if failures:
            raise RegistryError(f"promotion refused ({len(failures)} problem(s))", failures)
    if run_dir is not None:
        run_id = Path(run_dir).name
        if (Path(run_dir) / "manifest.json").is_file():
            prereg_sha = _load(Path(run_dir) / "manifest.json").get("prereg_sha256")
    if action == "reject":
        if run_dir is None or not (Path(run_dir) / "decision.json").is_file():
            raise RegistryError("reject needs --run <evaluation run directory> with a decision.json")

    event = {
        "at_utc": _now(),
        "action": action,
        "from": current,
        "to": to_status,
        "reason": reason,
        "run_id": run_id,
        "prereg_sha256": prereg_sha,
        "actor": actor or getpass.getuser(),
    }
    event["audit"] = (audit or write_audit_row)(action, model_id, {k: v for k, v in event.items() if k != "audit"})

    updated = dict(entry)
    updated["status"] = to_status
    if action in ("promote", "reject") and run_id:
        updated["evaluation_ref"] = run_id
    if action in ("reject", "quarantine"):
        updated["quarantine_reason"] = reason
    updated["history"] = list(entry.get("history", [])) + [event]

    new_entries = list(entries)
    new_entries[idx] = updated
    assert_history_unaltered(entries, new_entries)
    write_registry_atomic(Path(registry_path), new_entries)
    return updated


def decide_from_run(
    model_id: str, run_dir: Path, *, registry_path: Path = REGISTRY_PATH, **kwargs: Any
) -> tuple[str, dict[str, Any] | None]:
    """Apply the run's decision: promote if the run says so and every check passes, otherwise reject (-> quarantined)
    with the reasons. Returns ``("promote" | "reject" | "none", entry)``; ``"none"`` when the run evaluated no
    candidate (result "no promotable policy" and nothing to transition)."""
    decision = _load(Path(run_dir) / "decision.json")
    if decision.get("outcome") == "NOT_EVALUATED":
        return "none", None
    try:
        return "promote", transition("promote", model_id, registry_path=registry_path, run_dir=run_dir, **kwargs)
    except RegistryError as exc:
        reason = f"{decision.get('result', ep.NO_PROMOTABLE)}: outcome {decision.get('outcome')}; " + "; ".join(
            exc.failures or [str(exc)]
        )
        return "reject", transition(
            "reject", model_id, registry_path=registry_path, run_dir=run_dir, reason=reason[:1000], **kwargs
        )


# ----------------------------------------------------------------------------- CLI
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in TRANSITIONS:
        p = sub.add_parser(name)
        p.add_argument("model_id")
        p.add_argument("--run", type=Path)
        p.add_argument("--reason")
    d = sub.add_parser("decide", help="promote if the run qualifies, otherwise reject (quarantine) with the reasons")
    d.add_argument("model_id")
    d.add_argument("--run", type=Path, required=True)
    args = ap.parse_args(argv)

    try:
        if args.cmd == "list":
            for e in load_registry(args.registry):
                print(f"{e.get('model_id', '-'):<40} {e.get('name', '-'):<20} {e.get('status', '(no status)')}")
            return 0
        if args.cmd == "decide":
            action, entry = decide_from_run(args.model_id, args.run, registry_path=args.registry)
            print(f"{action}: {entry['status'] if entry else ep.NO_PROMOTABLE}")
            return 0
        entry = transition(args.cmd, args.model_id, registry_path=args.registry, run_dir=args.run, reason=args.reason)
        print(f"{args.model_id}: {entry['history'][-1]['from']} -> {entry['status']}")
        return 0
    except RegistryError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        for failure in exc.failures:
            print(f"  - {failure}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
