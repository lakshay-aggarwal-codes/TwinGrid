"""Command line for the baselines (T28).

    python -m src.baselines.cli tune                 # tune all four on VALIDATION scenarios -> configs/baselines/*.json
    python -m src.baselines.cli run  --run-id baselines-v2 [--check-determinism]
    python -m src.baselines.cli verify baselines-v2 [--rerun] [--strict]

``tune`` reads the pre-registered evaluation config (``reports/policy_evaluation/PREREGISTRATION.json``),
builds the validation scenarios and hands ONLY those to the tuners. ``run`` and ``verify`` use the T24
framework (``src/repro``): the experiment is registered in-process, the five config files and the
pre-registration are hashed into ``reports/runs/<run_id>/manifest.json``, and ``verify --rerun``
re-executes the experiment and byte-compares ``results.json``.

Exit status: 0 ok; 1 a run/verification failed; 2 bad inputs or stale configs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PREREG = "reports/policy_evaluation/PREREGISTRATION.json"


def _eval_cfg(root: Path):
    from .. import policy_evaluation as pe

    return pe.load_preregistered_config((root / PREREG).parent)


def cmd_tune(args: argparse.Namespace, root: Path) -> int:
    import numpy as np

    from .. import policy_evaluation as pe
    from ..repro.canonical import canonical_dumps
    from ..repro.run import write_atomic
    from . import config as bcfg
    from . import evaluation, tuning

    eval_cfg = _eval_cfg(root)
    scenarios = pe.build_scenarios(eval_cfg)
    pe.assert_disjoint(eval_cfg, scenarios)
    validation = scenarios["validation"]  # the tuners never receive the test split
    curve, is_real = pe.load_diurnal_carbon_intensity()
    configs = tuning.tune_all(
        eval_cfg, validation, np.asarray(curve, dtype=float), carbon_is_real=is_real, progress=print
    )
    out = root / args.out
    for name, cfg in configs.items():
        bcfg.write_config(cfg, out / f"{name}.json")
        print(f"{name}: {cfg['status']}  {bcfg.describe_parameters(cfg)}")
    write_atomic(
        out / "evaluation.json",
        canonical_dumps(evaluation.evaluation_document(eval_cfg, directory=args.out, prereg=PREREG)).encode("ascii"),
    )
    print(f"wrote {args.out}/")
    return 0


def _request(args: argparse.Namespace, root: Path, argv: list[str]):
    from .. import policy_evaluation as pe
    from ..repro.run import RunRequest
    from . import config as bcfg

    eval_cfg = _eval_cfg(root)
    sc = pe.build_scenarios(eval_cfg)
    val_id, test_id = pe.scenario_set_id(sc["validation"]), pe.scenario_set_id(sc["test"])
    d = args.configs
    return RunRequest(
        experiment="baselines",
        config_paths=[f"{d}/evaluation.json", *[f"{d}/{n}.json" for n in bcfg.BASELINE_NAMES]],
        prereg=PREREG,
        scenario_set_id=pe.scenario_set_id(sc["validation"] + sc["test"]),
        split_id=f"validation={val_id};test={test_id}",
        run_id=args.run_id,
        check_determinism=args.check_determinism,
        argv=["python", "-m", "src.baselines.cli", *argv],
    )


def cmd_run(args: argparse.Namespace, root: Path, argv: list[str]) -> int:
    from ..repro.experiments import UnknownExperiment
    from ..repro.run import RunError, run
    from . import config as bcfg
    from . import evaluation

    evaluation.register(root)
    try:
        outcome = run(_request(args, root, argv), root)
    except (RunError, UnknownExperiment, bcfg.BaselineConfigError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if outcome.state != "completed":
        print(f"FAILED {outcome.run_id}: {outcome.error}", file=sys.stderr)
        return 1
    print(outcome.run_id)
    return 0


def cmd_verify(args: argparse.Namespace, root: Path) -> int:
    from ..repro.verify import verify_run
    from . import evaluation

    evaluation.register(root)
    rep = verify_run(root, args.run_id, rerun=args.rerun)
    for finding in rep.findings:
        print(finding)
    ok = rep.ok(strict=args.strict)
    print(f"{'PASS' if ok else 'FAIL'} {args.run_id}: {len(rep.failures)} failure(s), {len(rep.warnings)} warning(s)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tune", help="tune the baselines on validation scenarios")
    t.add_argument("--out", default="configs/baselines")
    r = sub.add_parser("run", help="evaluate on the test scenarios through the T24 run framework")
    r.add_argument("--configs", default="configs/baselines")
    r.add_argument("--run-id")
    r.add_argument("--check-determinism", action="store_true")
    v = sub.add_parser("verify", help="verify a baselines run (T24 verify, with the experiment registered)")
    v.add_argument("run_id")
    v.add_argument("--rerun", action="store_true")
    v.add_argument("--strict", action="store_true")
    args = p.parse_args(raw)
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    try:
        if args.command == "tune":
            return cmd_tune(args, root)
        if args.command == "run":
            return cmd_run(args, root, raw)
        return cmd_verify(args, root)
    except Exception as exc:  # noqa: BLE001 - stale configs and missing inputs are user errors, not crashes
        from . import config as bcfg

        if isinstance(exc, (bcfg.BaselineConfigError, FileNotFoundError, ValueError)):
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
