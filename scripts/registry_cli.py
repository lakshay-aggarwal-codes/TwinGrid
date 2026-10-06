#!/usr/bin/env python3
"""Operator tool for model lifecycle states in ``models/registry.json`` (T19, contract 10.4).

    list        show every artifact: status, kind, waiver, evaluation_ref
    promote     candidate -> promoted           (the ONLY way an artifact becomes loadable by the API)
    reject      candidate | promoted | quarantined -> rejected
    quarantine  candidate | promoted -> quarantined
    migrate     one-time conversion of a pre-T19 (manifest v1) registry to v2

This is the only code that changes an artifact's ``status``. Every transition appends one object
to that artifact's ``history[]``; existing history entries and every other artifact are copied
through byte for byte. Writes are atomic and keep the previous registry as ``registry.json.bak``.

Promotion refuses unless, right now: the manifest is well-formed; every file's SHA-256 and size
match; every file's format is loadable by the API (json / npz / keras -- so an SB3 zip cannot be
promoted); every compatibility field matches the running code or is covered by the artifact's
named ``compat_waiver``; and either an ``--evaluation-ref`` is given or a waiver is present.
"Compatible" is not "good": promotion does not look at model quality.

Audit. By default a row is written to the database ``audit_logs`` table when the database is
reachable, and skipped (with a note) when it is not. ``--audit`` REQUIRES the row: if it cannot be
written the command exits with status 3 and the registry is left unchanged. ``--no-audit`` skips
it. (If the registry write succeeds but the final DB commit then fails, the registry has changed;
the command says so and still exits 3.)

Exit status: 0 ok; 1 refused (rule violated, unknown id, ...); 2 usage; 3 required audit failed.

Examples:
    python scripts/registry_cli.py list
    python scripts/registry_cli.py quarantine ppo_optimizer-20260927T143232Z --reason "..." --audit
    python scripts/registry_cli.py promote forecaster-... --evaluation-ref run-2026-10-11 --reason "T26 sign-off"
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import model_registry as mr  # noqa: E402
from src import versions  # noqa: E402
from src.artifacts import loaders  # noqa: E402

EXIT_OK, EXIT_REFUSED, EXIT_AUDIT = 0, 1, 3
AUDIT_TIMEOUT_S = 5.0

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"promoted", "rejected", "quarantined"}),
    "promoted": frozenset({"rejected", "quarantined"}),
    "quarantined": frozenset({"rejected"}),
    "rejected": frozenset(),
    "retired": frozenset(),
}


class Refused(Exception):
    """A rule forbids the requested change (exit status 1)."""


class AuditUnavailable(Exception):
    """The audit row could not be written because the database was not usable (nothing applied)."""


class AuditCommitFailed(Exception):
    """The registry change was applied but the audit row's commit then failed."""


# ----------------------------------------------------------------------------- audit backend


def _db_backend(row: dict[str, Any], apply: Callable[[], None]) -> None:
    """Write ``row`` to ``audit_logs`` in a transaction that also covers ``apply()``.

    The row is flushed first, so an unreachable database fails BEFORE the registry is touched. If
    ``apply()`` raises, the row is rolled back and that error propagates unchanged. Raises
    AuditUnavailable if nothing was applied, AuditCommitFailed if ``apply()`` ran and the commit
    then failed.
    """
    state: dict[str, Any] = {"applied": False, "apply_error": None}

    def guarded_apply() -> None:
        try:
            apply()
        except BaseException as exc:
            state["apply_error"] = exc
            raise
        state["applied"] = True

    async def go() -> None:
        from database import get_session  # imported late: needs the API's DB dependencies
        from models.db_models import AuditLog

        async with get_session() as session:
            session.add(AuditLog(**row))
            await asyncio.wait_for(session.flush(), AUDIT_TIMEOUT_S)
            guarded_apply()

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001 - any DB / import failure means "audit not written"
        if state["apply_error"] is not None:
            raise state["apply_error"] from None  # the registry write itself failed: not an audit problem
        if state["applied"]:
            raise AuditCommitFailed(f"{type(exc).__name__}: {exc}") from exc
        raise AuditUnavailable(f"{type(exc).__name__}: {exc}") from exc


_audit_backend: Callable[[dict[str, Any], Callable[[], None]], None] = _db_backend


def apply_with_audit(mode: str, row: dict[str, Any], apply: Callable[[], None]) -> str:
    """Run ``apply`` (the registry write) with the requested audit behaviour.

    ``mode``: ``"auto"`` (audit if the DB is reachable), ``"require"`` or ``"off"``. Returns a
    one-line description of what happened to the audit. Raises AuditUnavailable /
    AuditCommitFailed for ``require``.
    """
    if mode == "off":
        apply()
        return "audit: skipped (--no-audit)"
    try:
        _audit_backend(row, apply)
        return "audit: row written"
    except AuditUnavailable as exc:
        if mode == "require":
            raise
        apply()
        return f"audit: SKIPPED, database not reachable ({exc})"
    except AuditCommitFailed:
        if mode == "require":
            raise
        return "audit: row NOT written (commit failed); registry was updated"


def _audit_row(action: str, model_id: str, actor: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": actor[:64],
        "action": f"model_{action}"[:64],
        "resource_type": "model_artifact",
        "resource_id": model_id[:64],
        "details": details,
    }


# ----------------------------------------------------------------------------- transitions


def _find(entries: list[dict[str, Any]], model_id: str) -> int:
    matches = [i for i, e in enumerate(entries) if e.get("model_id") == model_id]
    if not matches:
        raise Refused(f"no artifact with model_id {model_id!r} (see: registry_cli.py list)")
    return matches[-1]


def _preflight_for_promotion(entry: dict[str, Any], evaluation_ref: str | None) -> None:
    if entry.get("manifest_version") != mr.MANIFEST_VERSION:
        raise Refused("not a manifest v2 entry; migrate the registry first")
    problems = mr.validate_manifest(entry)
    if problems:
        raise Refused("invalid manifest: " + "; ".join(problems))
    try:
        mr.check_integrity(entry, list(entry["files"]))
    except mr.ModelUnavailableError as exc:
        raise Refused(f"integrity: {exc.reason}") from None
    for rel, info in entry["files"].items():
        fmt = info.get("format")
        if fmt not in loaders.ALLOWED_FORMATS["api"]:
            raise Refused(f"{rel}: format {fmt!r} is not loadable by the API process, so it cannot be promoted")
        if mr.format_for_path(rel) != fmt:
            raise Refused(f"{rel}: recorded format {fmt!r} does not match the file name")
    try:
        blocking, _waived = loaders.evaluate_compat(entry)
    except mr.ModelUnavailableError as exc:
        raise Refused(exc.reason) from None
    if blocking:
        field, expected, actual = blocking[0]
        raise Refused(
            f"incompatible: {field} is {actual!r} in the manifest but {expected!r} in the running code "
            f"({len(blocking)} field(s) not covered by a waiver)"
        )
    if not evaluation_ref and not entry.get("evaluation_ref") and not entry.get("compat_waiver"):
        raise Refused("promotion needs --evaluation-ref (the run that evaluated this model) or a compat_waiver")


def transition(
    entries: list[dict[str, Any]],
    model_id: str,
    to_status: str,
    *,
    actor: str,
    reason: str,
    evaluation_ref: str | None = None,
) -> list[dict[str, Any]]:
    """The new artifact list after moving ``model_id`` to ``to_status``. Pure: ``entries`` is not
    modified, and every entry other than ``model_id`` is returned unchanged. The target's old
    ``history`` items are carried over untouched and exactly one is appended."""
    if not reason.strip():
        raise Refused("--reason is required")
    index = _find(entries, model_id)
    entry = entries[index]
    current = entry.get("status")
    if to_status not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise Refused(f"cannot move {model_id} from {current!r} to {to_status!r}")
    if to_status == "promoted":
        _preflight_for_promotion(entry, evaluation_ref)
    history = list(entry["history"])
    history.append(mr.history_entry(len(history), to_status_action(to_status), current, to_status, actor, reason))
    updated = {**entry, "status": to_status, "status_reason": reason, "history": history}
    if evaluation_ref:
        updated["evaluation_ref"] = evaluation_ref
    out = list(entries)
    out[index] = updated
    return out


def to_status_action(to_status: str) -> str:
    return {"promoted": "promote", "rejected": "reject", "quarantined": "quarantine"}[to_status]


def _registry_digest(entries: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(mr.registry_document(entries), sort_keys=True).encode()).hexdigest()


def cmd_transition(args: argparse.Namespace, to_status: str) -> int:
    actor = args.actor or getpass.getuser()
    document = mr.read_registry_document()
    if document.get("registry_version") != mr.REGISTRY_VERSION:
        raise Refused("the registry is not v2; run: registry_cli.py migrate")
    entries = document["artifacts"]
    old = entries[_find(entries, args.model_id)]
    new_entries = transition(
        entries,
        args.model_id,
        to_status,
        actor=actor,
        reason=args.reason,
        evaluation_ref=getattr(args, "evaluation_ref", None),
    )
    row = _audit_row(
        to_status_action(to_status),
        args.model_id,
        actor,
        {
            "from": old.get("status"),
            "to": to_status,
            "reason": args.reason,
            "evaluation_ref": getattr(args, "evaluation_ref", None),
            "registry_sha256_after": _registry_digest(new_entries),
        },
    )
    if args.dry_run:
        print(f"dry run: {args.model_id}: {old.get('status')} -> {to_status} (nothing written)")
        return EXIT_OK
    note = apply_with_audit(args.audit_mode, row, lambda: mr.write_registry(new_entries))
    print(f"{args.model_id}: {old.get('status')} -> {to_status}")
    print(note)
    return EXIT_OK


# ----------------------------------------------------------------------------- list


def cmd_list(args: argparse.Namespace) -> int:
    document = mr.read_registry_document()
    entries = document["artifacts"]
    if args.status:
        entries = [e for e in entries if e.get("status") == args.status]
    if args.json:
        print(json.dumps(entries, indent=2))
        return EXIT_OK
    print(f"registry_version {document.get('registry_version')}, {len(entries)} artifact(s)")
    for e in entries:
        waiver = e.get("compat_waiver")
        flag = f"  WAIVER {waiver.get('name')} (expires after {waiver.get('expires_after_task')})" if waiver else ""
        print(
            f"{e.get('model_id', e.get('name'))}\n    kind={e.get('kind')} status={e.get('status')} "
            f"evaluation_ref={e.get('evaluation_ref')} code_revision={e.get('code_revision')}{flag}"
        )
        if e.get("status_reason"):
            print(f"    reason: {e['status_reason']}")
    return EXIT_OK


# ----------------------------------------------------------------------------- migrate (v1 -> v2)

LEGACY_WAIVER_TASK = "T26"


def _legacy_split_id(kind: str, v1: dict[str, Any]) -> str | None:
    if kind == "anomaly":
        m = re.search(r"rows (\d+):(\d+) train, (\d+):(\d+) held out", str(v1.get("data_source", "")))
        if m:
            return f"chronological:train=rows[{m[1]}:{m[2]}],heldout=rows[{m[3]}:{m[4]}]"
    if kind == "forecaster" and "train_ratio" in (v1.get("params") or {}):
        return f"chronological:train_ratio={v1['params']['train_ratio']}"
    return None


def _quarantine_reason(v1: dict[str, Any]) -> str:
    metrics = v1.get("metrics") or {}
    pue = metrics.get("pue_improvement_mean_pct")
    pue_text = (
        f"mean PUE improvement {pue:+.2f}% vs the rule baseline (worse, not better)"
        if pue is not None
        else "no PUE result recorded"
    )
    return (
        f"physics legacy-0; environment, reward and safety-envelope versions were never recorded (unversioned); "
        f"{pue_text}; never evaluated under the T8 decision gate; SB3 zip is not loadable by the API process"
    )


def migrate_entry(v1: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """A manifest-v2 entry for a manifest-v1 ``v1`` entry, from the files on disk now.

    Nothing is guessed: fields that were not recorded at training time are null. Model files must
    still match the hashes v1 recorded (the migration never blesses a file that changed); the
    ``scaler.joblib`` -> ``scaler.json`` swap is the one allowed difference.
    """
    name, version = str(v1["name"]), str(v1["version"])
    kind = mr.infer_kind(name)
    files: dict[str, dict[str, Any]] = {}
    for rel, info in (v1.get("files") or {}).items():
        if rel.endswith("scaler.joblib"):
            rel_new = rel[: -len("scaler.joblib")] + "scaler.json"
            if not (mr.PROJECT_ROOT / rel_new).is_file():
                raise Refused(f"{name}: {rel_new} is missing; run scripts/convert_scalers.py first")
            files.update(mr.file_digests([rel_new]))
            continue
        path = mr.PROJECT_ROOT / rel
        if not path.is_file():
            raise Refused(f"{name}: {rel} is missing")
        digest = mr.file_digests([rel])[rel]
        if digest["sha256"] != info.get("sha256"):
            raise Refused(f"{name}: {rel} no longer matches the hash recorded at training time; not migrating")
        files[rel] = digest
    if not files:
        raise Refused(f"{name}: v1 entry lists no files")

    revision = v1.get("git_sha")
    code_revision = revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision) else None
    params = v1.get("params") or {}
    lineage = {field: None for field in versions.COMPAT_FIELDS}
    lineage["physics_version"] = v1.get("physics_version")
    lineage["input_cadence_s"] = (
        versions.INPUT_CADENCE_S
    )  # 5-minute telemetry / env step, as in the code that trained it

    if kind == "ppo":
        status, waiver = "quarantined", None
        reason = _quarantine_reason(v1)
    else:
        status = "promoted"
        reason = "migrated from manifest v1 under a named compatibility waiver"
        waiver = {
            "name": f"legacy-0-physics-until-{LEGACY_WAIVER_TASK}",
            "fields": ["physics_version", "physics_params_hash"],
            "reason": (
                f"{name} was trained on data produced under physics legacy-0 and its physics parameters were "
                f"not recorded; it is re-validated or retrained under the current physics in {LEGACY_WAIVER_TASK}"
            ),
            "expires_after_task": LEGACY_WAIVER_TASK,
        }
    trained_at = v1.get("trained_at") or mr.now_utc()
    return {
        "model_id": f"{name}-{version}",
        "name": name,
        "kind": kind,
        "status": status,
        "status_reason": reason,
        "created_at_utc": trained_at,
        "code_revision": code_revision,
        **lineage,
        "training_config": mr.training_config_block(params),
        "seeds": params.get("seeds"),
        "dataset_id": v1.get("dataset_id"),
        "dataset_manifest_sha256": None,
        "scenario_set_id": None,
        "split_id": _legacy_split_id(kind, v1),
        "package_versions": v1.get("key_package_versions"),
        "files": files,
        "evaluation_ref": None,
        "compat_waiver": waiver,
        "history": [
            {
                "seq": 0,
                "at_utc": trained_at,
                "action": "logged",
                "from": None,
                "to": "candidate",
                "actor": "legacy-training",
                "reason": "recorded by the training run (manifest v1)",
            },
            mr.history_entry(1, "migrate", "candidate", status, actor, reason),
        ],
        "version": version,
        "trained_at": trained_at,
        "metrics": v1.get("metrics", {}),
        "data_source": v1.get("data_source"),
        "params": params,
        "python": v1.get("python"),
        "manifest_version": mr.MANIFEST_VERSION,
        "migrated_from_manifest_version": v1.get("manifest_version", 0),
        "relative_path": v1.get("relative_path") or v1.get("artifact_path"),
        "artifact_path": v1.get("relative_path") or v1.get("artifact_path"),
        "sha256": mr.aggregate_sha256(files),
        "size": sum(f["size"] for f in files.values()),
        "git_sha": v1.get("git_sha", "unknown"),
        "dataset_sha256": v1.get("dataset_sha256"),
    }


def cmd_migrate(args: argparse.Namespace) -> int:
    actor = args.actor or getpass.getuser()
    document = mr.read_registry_document()
    if document.get("registry_version") == mr.REGISTRY_VERSION:
        print("registry is already v2; nothing to do")
        return EXIT_OK
    migrated = [migrate_entry(e, actor=actor) for e in document["artifacts"]]
    for e in migrated:
        print(
            f"{e['model_id']}: -> {e['status']}"
            + (f" (waiver {e['compat_waiver']['name']})" if e["compat_waiver"] else "")
        )
    if args.dry_run:
        print("dry run: nothing written")
        return EXIT_OK
    row = _audit_row(
        "registry_migrate",
        "registry",
        actor,
        {"artifacts": [e["model_id"] for e in migrated], "registry_sha256_after": _registry_digest(migrated)},
    )
    note = apply_with_audit(args.audit_mode, row, lambda: mr.write_registry(migrated))
    print(f"wrote registry v2 ({len(migrated)} artifacts); previous file kept as {mr.REGISTRY_PATH.name}.bak")
    print(note)
    return EXIT_OK


# ----------------------------------------------------------------------------- entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--actor", help="who is making the change (default: the OS user)")
        group = p.add_mutually_exclusive_group()
        group.add_argument(
            "--audit", dest="audit_mode", action="store_const", const="require", help="REQUIRE the DB audit row"
        )
        group.add_argument(
            "--no-audit", dest="audit_mode", action="store_const", const="off", help="skip the DB audit row"
        )
        p.set_defaults(audit_mode="auto")
        p.add_argument("--dry-run", action="store_true", help="check and show the change; write nothing")

    ls = sub.add_parser("list", help="show artifacts and their status")
    ls.add_argument("--status", choices=mr.STATUSES)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    for name, status in (("promote", "promoted"), ("reject", "rejected"), ("quarantine", "quarantined")):
        p = sub.add_parser(name, help=f"move an artifact to {status}")
        p.add_argument("model_id")
        p.add_argument("--reason", required=True, help="why (recorded in history[] and the audit row)")
        if name == "promote":
            p.add_argument("--evaluation-ref", help="id of the evaluation run that justifies promotion")
        common(p)
        p.set_defaults(func=lambda a, s=status: cmd_transition(a, s))

    mg = sub.add_parser("migrate", help="convert a pre-T19 (manifest v1) registry to v2")
    common(mg)
    mg.set_defaults(func=cmd_migrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except AuditUnavailable as exc:
        print(f"AUDIT FAILED: {exc}. The registry was NOT changed.", file=sys.stderr)
        return EXIT_AUDIT
    except AuditCommitFailed as exc:
        print(f"AUDIT FAILED after the registry was written: {exc}. The registry HAS changed.", file=sys.stderr)
        return EXIT_AUDIT
    except (OSError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
