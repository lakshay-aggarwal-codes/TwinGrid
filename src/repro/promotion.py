"""Promotion eligibility (contract 11.2): a model may only be promoted on evidence from a NON-DIRTY run.

``promotion_eligibility`` is what a promotion step (``registry_cli promote --evaluation-ref <run_id>``,
wired up by a later task) calls. It is deliberately small: it checks the facts recorded by the run and
that ``results.json`` still hashes to what the manifest says; ``repro.py verify`` is the full audit.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import env
from .canonical import sha256_bytes
from .run import RunError, read_json, run_dir_for

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class NotPromotable(RuntimeError):
    def __init__(self, run_id: str, reasons: list[str]) -> None:
        super().__init__(f"run {run_id} cannot support a promotion: " + "; ".join(reasons))
        self.run_id = run_id
        self.reasons = reasons


def promotion_eligibility(root: Path, run_id: str, runs_dir: str = env.RUNS_SUBDIR) -> tuple[bool, list[str]]:
    """``(eligible, reasons_not_eligible)``."""
    reasons: list[str] = []
    try:
        run_dir = run_dir_for(root, run_id, runs_dir)
        manifest = read_json(run_dir / "manifest.json")
        status = read_json(run_dir / "status.json")
    except (RunError, env.PathOutsideRoot, OSError, ValueError):
        return False, ["run directory, manifest or status is missing or unreadable"]
    if status.get("state") != "completed":
        reasons.append(f"status is {status.get('state')!r}, not 'completed'")
    if manifest.get("dirty") is not False:
        reasons.append("the run was made from a dirty (or unverifiable) working tree")
    if not _SHA40.match(str(manifest.get("code_revision", ""))):
        reasons.append("no 40-hex code revision was recorded")
    recorded = manifest.get("result_sha256")
    try:
        actual = sha256_bytes((run_dir / "results.json").read_bytes().replace(b"\r\n", b"\n"))
    except OSError:
        actual = None
    if not recorded or actual != recorded:
        reasons.append("results.json is missing or does not match result_sha256")
    return not reasons, reasons


def require_promotable(root: Path, run_id: str, runs_dir: str = env.RUNS_SUBDIR) -> None:
    ok, reasons = promotion_eligibility(root, run_id, runs_dir)
    if not ok:
        raise NotPromotable(run_id, reasons)
