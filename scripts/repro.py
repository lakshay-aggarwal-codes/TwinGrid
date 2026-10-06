#!/usr/bin/env python3
"""Reproducibility checks for runs under ``reports/runs`` (T24, contract section 11).

    python scripts/repro.py verify <run_id> [--rerun] [--strict]
    python scripts/repro.py promotable <run_id>
    python scripts/repro.py list

``verify`` recomputes the SHA-256 of every recorded input (configs, dataset manifest, pre-registration,
lock file, artifacts), compares the code revision and version constants, checks that ``results.json``
still hashes to the manifest, and regenerates REPORT.md, tables/ and figures/ from ``results.json`` and
byte-compares them. ``--rerun`` also re-executes the experiment and compares the results (level L1:
same machine and environment). Platform differences are warnings; ``--strict`` makes warnings failures.

Exit status: 0 ok; 1 verification failed / not promotable; 2 usage error or unknown run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.repro import env  # noqa: E402
from src.repro.promotion import promotion_eligibility  # noqa: E402
from src.repro.run import RunError, read_json, run_dir_for  # noqa: E402
from src.repro.verify import verify_run  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    p.add_argument("--runs-dir", default=env.RUNS_SUBDIR)
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify", help="re-check a run")
    v.add_argument("run_id")
    v.add_argument("--rerun", action="store_true", help="also re-execute the experiment and compare results.json")
    v.add_argument("--strict", action="store_true", help="treat warnings as failures")
    pm = sub.add_parser("promotable", help="exit 0 only if the run is complete and from a non-dirty tree")
    pm.add_argument("run_id")
    sub.add_parser("list", help="list runs")
    return p


def cmd_verify(args: argparse.Namespace, root: Path) -> int:
    try:
        run_dir = run_dir_for(root, args.run_id, args.runs_dir)
    except (RunError, env.PathOutsideRoot) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not run_dir.is_dir():
        print(f"ERROR: no run directory for {args.run_id}", file=sys.stderr)
        return 2
    rep = verify_run(root, args.run_id, runs_dir=args.runs_dir, rerun=args.rerun)
    for finding in rep.findings:
        print(finding)
    ok = rep.ok(strict=args.strict)
    print(f"{'PASS' if ok else 'FAIL'} {args.run_id}: {len(rep.failures)} failure(s), {len(rep.warnings)} warning(s)")
    return 0 if ok else 1


def cmd_promotable(args: argparse.Namespace, root: Path) -> int:
    eligible, reasons = promotion_eligibility(root, args.run_id, args.runs_dir)
    if eligible:
        print(f"PROMOTABLE {args.run_id}")
        return 0
    for reason in reasons:
        print(f"NOT PROMOTABLE: {reason}")
    return 1


def cmd_list(args: argparse.Namespace, root: Path) -> int:
    runs = env.resolve_in_root(args.runs_dir, root)
    if not runs.is_dir():
        print("no runs")
        return 0
    for d in sorted(p for p in runs.iterdir() if p.is_dir()):
        try:
            m, s = read_json(d / "manifest.json"), read_json(d / "status.json")
            print(f"{d.name}\t{s.get('state')}\tdirty={m.get('dirty')}\t{m.get('code_revision')}")
        except (OSError, ValueError):
            print(f"{d.name}\tunreadable")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    return {"verify": cmd_verify, "promotable": cmd_promotable, "list": cmd_list}[args.command](args, root)


if __name__ == "__main__":
    raise SystemExit(main())
