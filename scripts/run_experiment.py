#!/usr/bin/env python3
"""Run a registered experiment into ``reports/runs/<run_id>/`` (T24, contract section 11).

    python scripts/run_experiment.py --experiment toy --config src/repro/toy_config.json
    python scripts/run_experiment.py --experiment toy --config src/repro/toy_config.json \\
        --seed 1 --seed 2 --run-id toy-demo --check-determinism

Every input is hashed into ``manifest.json`` (configs, dataset manifest, pre-registration, lock file,
model artifacts), the code revision is recorded (a dirty tree sets ``dirty = true`` and forbids
promotion), randomness comes only from explicit ``numpy.random.Generator`` streams, and tables,
figures and REPORT.md are generated from ``results.json``. Verify later with
``python scripts/repro.py verify <run_id>``.

Exit status: 0 completed; 1 failed (recorded in status.json); 2 bad inputs (nothing written).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.repro import env, experiments  # noqa: E402
from src.repro.run import RunError, RunRequest, run  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--experiment", required=True, help=f"one of: {', '.join(experiments.names())}")
    p.add_argument(
        "--config",
        action="append",
        required=True,
        metavar="PATH",
        help="config JSON (repeatable; the first is primary)",
    )
    p.add_argument(
        "--seed",
        action="append",
        type=int,
        metavar="N",
        help="seed (repeatable); default: 'seeds' in the primary config",
    )
    p.add_argument("--dataset-manifest", metavar="PATH", help="dataset MANIFEST file whose sha256 is recorded")
    p.add_argument("--prereg", metavar="PATH", help="pre-registration file whose sha256 is recorded")
    p.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="MODEL_ID",
        help="registry model_id the run evaluates (repeatable)",
    )
    p.add_argument("--scenario-set-id")
    p.add_argument("--split-id")
    p.add_argument("--run-id", help="explicit run id (default: <experiment>-<UTC time>-<config/seed digest>)")
    p.add_argument("--runs-dir", default=env.RUNS_SUBDIR, help="output root, inside the repository")
    p.add_argument(
        "--check-determinism", action="store_true", help="execute twice and fail unless the results are identical"
    )
    p.add_argument("--require-clean", action="store_true", help="refuse to run on a dirty working tree")
    p.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw)
    request = RunRequest(
        experiment=args.experiment,
        config_paths=args.config,
        seeds=args.seed,
        dataset_manifest=args.dataset_manifest,
        prereg=args.prereg,
        artifacts=args.artifact,
        scenario_set_id=args.scenario_set_id,
        split_id=args.split_id,
        run_id=args.run_id,
        runs_dir=args.runs_dir,
        check_determinism=args.check_determinism,
        require_clean=args.require_clean,
        argv=["scripts/run_experiment.py", *raw],
    )
    try:
        outcome = run(request, Path(args.root))
    except (RunError, experiments.UnknownExperiment, env.PathOutsideRoot) as exc:
        print(f"ERROR: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    if outcome.state != "completed":
        print(f"FAILED {outcome.run_id}: {outcome.error}", file=sys.stderr)
        return 1
    from src.repro.run import read_json

    manifest = read_json(outcome.run_dir / "manifest.json")
    if manifest["dirty"]:
        print(
            f"note: dirty/unverifiable working tree ({manifest['code_revision_source']}); this run can never support a promotion",
            file=sys.stderr,
        )
    print(outcome.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
