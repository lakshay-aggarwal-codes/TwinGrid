"""Command-line interface.

    python research/danish_aau/run_evaluation.py <command> [options]      (works from any directory)
    python -m research.danish_aau.evaluation <command> [options]          (from the repository root)

Commands:  doctor | inventory | run | verify | show-config
Exit codes: 0 ok | 2 a check failed, bad configuration or bad usage | 3 --require-ready and declarations are missing.

All console output is plain ASCII (Windows consoles use legacy code pages). Files are written as UTF-8/ASCII.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import HARNESS_VERSION, _reuse
from .config import ConfigError, EvalConfig, load_config
from .inventory import format_inventory, inventory_raw
from .manifest import MANIFEST_NAME, verify_manifest
from .paths import (
    DEFAULT_CONFIG_PATH,
    PACKAGE_DIR,
    REPO_ROOT,
    UnsafeOutputPath,
    ensure_output_dir_safe,
    resolve_against_root,
    resolve_raw_dir,
)
from .runner import RunContext, available_stages, make_run_id, run_pipeline


def _out(text: str = "") -> None:
    sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="TOML config (default: config/default.toml)")
    p.add_argument(
        "--raw-dir", default=None, help="raw dataset directory (else $TWINGRID_AAU_RAW_DIR, config, default)"
    )
    p.add_argument("--repo-root", default=str(REPO_ROOT), help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aau-eval",
        description="Danish AAU v5 offline evaluation harness (Phases 1-2: foundation and data engineering)",
    )
    parser.add_argument("--version", action="version", version=HARNESS_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="check the environment, config, dataset location and isolation")
    _add_common(p)
    p.add_argument(
        "--require-dataset", action="store_true", help="a missing raw dataset directory is a FAIL, not a WARN"
    )
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("inventory", help="header-level inventory of the raw dataset directory (read-only)")
    _add_common(p)
    p.add_argument("--count-rows", action="store_true", help="stream each registered file to count data rows")
    p.add_argument("--hash", action="store_true", help="record SHA-256 of each registered file")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.add_argument(
        "--strict", action="store_true", help="exit 2 unless every registered file matches the reported expectations"
    )
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("run", help="run stages and write a run directory with a manifest")
    _add_common(p)
    p.add_argument(
        "--stage", action="append", default=None, help=f"stage to run (repeatable); available: {available_stages()}"
    )
    p.add_argument("--run-id", default=None)
    p.add_argument(
        "--data-config", default="", help="Phase 2 data-layer config for the prepare stage (default: config/data.toml)"
    )
    p.add_argument("--out-dir", default=None, help="output root (default: [output].root from the config)")
    p.add_argument("--count-rows", action="store_true")
    p.add_argument("--hash-inputs", action="store_true", help="override [integrity].hash_inputs = true")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures")
    p.add_argument(
        "--require-ready", action="store_true", help="exit 3 if timezone/duplicate policy are still undeclared"
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("verify", help="re-check a manifest (core hash, config hash, claims, raw inputs unchanged)")
    _add_common(p)
    p.add_argument("target", help="a run directory or a manifest.json")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("show-config", help="print the validated config, its SHA-256 and readiness")
    _add_common(p)
    p.set_defaults(func=cmd_show_config)
    return parser


def _load(args: argparse.Namespace) -> tuple[EvalConfig, Path, Any, Path]:
    repo_root = Path(args.repo_root).resolve()
    config_path = resolve_against_root(args.config, repo_root)
    config = load_config(config_path)
    raw = resolve_raw_dir(args.raw_dir, config.dataset.raw_dir, repo_root=repo_root)
    return config, config_path, raw, repo_root


def find_shadowing_modules(package_dir: Path) -> list[str]:
    """Python files in the evaluation tree whose module name is also a standard-library module (e.g. a stale ``types.py``)."""
    names = sys.stdlib_module_names
    return sorted(
        p.relative_to(package_dir).as_posix()
        for p in Path(package_dir).rglob("*.py")
        if p.stem in names and not (p.stem.startswith("__") and p.stem.endswith("__"))
    )


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.name


# ------------------------------------------------------------------------------------------------ doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    results: list[tuple[str, str, str]] = []

    def add(status: str, name: str, detail: str = "") -> None:
        results.append((status, name, detail))

    add("PASS" if sys.version_info >= (3, 11) else "FAIL", "python>=3.11 (tomllib)", sys.version.split()[0])
    repo_root = Path(args.repo_root).resolve()
    add(
        "PASS" if (repo_root / "src" / "digital_twin.py").is_file() else "FAIL",
        "repo root has src/digital_twin.py",
        repo_root.name,
    )
    for label, loader in (
        ("reuse src/repro/canonical.py", _reuse.canonical),
        ("reuse src/repro/env.py", _reuse.repro_env),
    ):
        try:
            loader()
            add("PASS", label)
        except _reuse.ReuseError as exc:
            add("FAIL", label, str(exc))
    add("PASS" if "src" not in sys.modules else "FAIL", "harness imported without the 'src' package")
    shadows = find_shadowing_modules(PACKAGE_DIR)
    add(
        "PASS" if not shadows else "FAIL",
        "no evaluation module shadows a standard-library module",
        ""
        if not shadows
        else f"{shadows}; delete the stale file(s), e.g. Remove-Item research\\danish_aau\\evaluation\\data_layer\\types.py",
    )

    config: EvalConfig | None = None
    try:
        config, config_path, raw, repo_root = _load(args)
        add("PASS", "config valid", _display_path(config_path, repo_root))
        ready = config.readiness()
        add(
            "PASS" if ready["ready_for_comparisons"] else "WARN",
            "declarations for comparisons (timezone, duplicate policy)",
            "complete" if ready["ready_for_comparisons"] else "; ".join(ready["blocking"]),
        )
        if config.timestamps.timezone not in ("undeclared", "UTC") and not config.timestamps.timezone.startswith(
            ("+", "-")
        ):
            try:
                import zoneinfo

                zoneinfo.ZoneInfo(config.timestamps.timezone)
                add("PASS", "timezone database knows the declared zone", config.timestamps.timezone)
            except Exception as exc:  # noqa: BLE001 - zoneinfo raises several types; Windows lacks tzdata by default
                add("WARN", "timezone database knows the declared zone", f"{type(exc).__name__}: pip install tzdata")
        raw_ok = raw.path.is_dir()
        add(
            "PASS" if raw_ok else ("FAIL" if args.require_dataset else "WARN"),
            f"raw dataset directory ({raw.source})",
            _display_path(raw.path, repo_root) + ("" if raw_ok else " -- not found"),
        )
        gi = repo_root / ".gitignore"
        ignored = gi.is_file() and "realData" in gi.read_text(encoding="utf-8", errors="replace")
        add("PASS" if ignored else "WARN", "realData/ is git-ignored")
        try:
            ensure_output_dir_safe(resolve_against_root(config.output.root, repo_root), raw.path, repo_root)
            add("PASS", "output root is safe", config.output.root)
        except UnsafeOutputPath as exc:
            add("FAIL", "output root is safe", str(exc))
    except ConfigError as exc:
        add("FAIL", "config valid", str(exc))

    for status, name, detail in results:
        _out(f"{status:4}  {name}" + (f": {detail}" if detail else ""))
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    warned = sum(1 for s, _, _ in results if s == "WARN")
    _out(f"doctor: {len(results) - failed - warned} pass, {warned} warn, {failed} fail")
    return 2 if failed else 0


# ------------------------------------------------------------------------------------------------ inventory
def cmd_inventory(args: argparse.Namespace) -> int:
    config, _, raw, _ = _load(args)
    report = inventory_raw(raw.path, count_rows=args.count_rows, hash_files=args.hash)
    if args.json:
        _out(_reuse.canonical().canonical_dumps(report).rstrip("\n"))
    else:
        _out(f"raw dir ({raw.source}): {raw.path.name} exists={report['raw_dir_exists']}")
        _out(format_inventory(report))
    if not report["raw_dir_exists"]:
        return 2
    return 2 if args.strict and not report["summary"]["all_registered_match"] else 0


# ------------------------------------------------------------------------------------------------ run
def cmd_run(args: argparse.Namespace) -> int:
    from . import stages  # noqa: F401  (importing registers the stages)

    config, config_path, raw, repo_root = _load(args)
    if args.hash_inputs:
        config = dataclasses.replace(config, integrity=dataclasses.replace(config.integrity, hash_inputs=True))
    now = datetime.now(timezone.utc)
    run_id = args.run_id or make_run_id(config, now)
    out_root = resolve_against_root(args.out_dir or config.output.root, repo_root)
    ctx = RunContext(
        config=config,
        config_path=_display_path(config_path, repo_root),
        repo_root=repo_root,
        raw_dir=raw.path,
        raw_dir_source=raw.source,
        run_dir=out_root / run_id,
        run_id=run_id,
        count_rows=args.count_rows,
        strict=args.strict,
        data_config_path=args.data_config,
    )
    manifest, code = run_pipeline(ctx, args.stage or ["preflight"], args._argv, now=now)
    _out(f"run {run_id}: {manifest['run']['status']}")
    _out(f"run directory: {_display_path(ctx.run_dir, repo_root)}")
    for st in manifest["stages"]:
        _out(f"  stage {st['name']}: {st['status']}")
    for stage_name, stage_report in ctx.shared.items():
        for problem in stage_report.get("problems", []):
            _out(f"  - [{stage_name}] {problem}")
    ready = manifest["readiness"]
    _out(
        "comparisons: "
        + (
            "declarations complete"
            if ready["ready_for_comparisons"]
            else "BLOCKED until declared -- " + "; ".join(ready["blocking"])
        )
    )
    _out(f"manifest core sha256: {manifest['determinism']['manifest_core_sha256']}")
    _out("claims: not calibrated, not validated (no comparison is produced in Phases 1-2)")
    if code == 0 and args.require_ready and not ready["ready_for_comparisons"]:
        return 3
    return code


# ------------------------------------------------------------------------------------------------ verify
def cmd_verify(args: argparse.Namespace) -> int:
    _, _, raw, repo_root = _load(args)
    target = Path(args.target)
    manifest_path = target / MANIFEST_NAME if target.is_dir() else target
    results = verify_manifest(manifest_path, raw.path, repo_root)
    for r in results:
        _out(f"{r['status'].upper():7} {r['check']}" + (f": {r['detail']}" if r["detail"] else ""))
    return 2 if any(r["status"] == "fail" for r in results) else 0


# ------------------------------------------------------------------------------------------------ show-config
def cmd_show_config(args: argparse.Namespace) -> int:
    config, _, raw, repo_root = _load(args)
    _out(
        json.dumps(
            {
                "config": config.to_dict(),
                "config_sha256": config.sha256,
                "readiness": config.readiness(),
                "raw_dir": _display_path(raw.path, repo_root),
                "raw_dir_source": raw.source,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args._argv = list(argv) if argv is not None else sys.argv[1:]
    try:
        return int(args.func(args))
    except ConfigError as exc:
        _out("configuration error:")
        for problem in exc.problems:
            _out(f"  - {problem}")
        return 2
    except (UnsafeOutputPath, FileExistsError, KeyError, ValueError) as exc:
        _out(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
