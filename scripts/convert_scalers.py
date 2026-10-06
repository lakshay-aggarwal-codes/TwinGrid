#!/usr/bin/env python3
"""One-shot T19 migration: legacy ``scaler.joblib`` -> ``scaler.json`` + quarantine of pickles.

For each of

    models/anomaly/scaler.joblib
    models/forecaster/scaler.joblib

this script (1) checks the file's SHA-256 against the value the registry recorded for it (or one
you pass with ``--sha256 PATH=HEX`` after confirming the file yourself) BEFORE unpickling it,
(2) converts the fitted scaler to ``scaler.json`` (StandardScaler / MinMaxScaler only; any other
type stops the whole run with exit status 2 and changes nothing), (3) proves the JSON scaler
transforms 10 000 random rows identically (<= 1e-12) to the pickled one, then (4) moves the
joblib to ``models/_legacy/``. Any other ``*.joblib`` / ``*.pkl`` still under ``models/`` is moved
to ``models/_legacy/`` unconverted, because nothing is allowed to load it any more.

It is the only code that ever unpickles one of these files (through
``loaders.load_legacy_joblib_for_conversion``), and it does so once. It changes no model weights.

Re-running is safe: converted scalers are skipped; a legacy file already present in
``models/_legacy`` with identical content simply causes the stale original to be removed (this is
how the change is applied to a checkout that already contains the converted files).

Exit status: 0 ok; 1 a check failed (nothing partially applied for that file); 2 unsupported
scaler type.

    python scripts/convert_scalers.py --dry-run
    python scripts/convert_scalers.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from src import model_registry as mr  # noqa: E402
from src.artifacts import loaders, scaler_io  # noqa: E402

TARGET_DIRS = ("models/anomaly", "models/forecaster")
LEGACY_DIR = "models/_legacy"
EQUIVALENCE_ROWS = 10_000
EQUIVALENCE_TOLERANCE = 1e-12

LEGACY_README = """# models/_legacy

Pickle-based files (`*.joblib`, `*.pkl`) moved here by `scripts/convert_scalers.py` (T19).
Nothing in the project loads files from this directory and the API process cannot load them at
all (contract 10.2: formats are limited to json, npz and keras). They are kept only so the
conversion can be rolled back. Do not load them; delete them once the rollback window has passed.
"""


class ConversionError(RuntimeError):
    pass


def _rel(path: Path) -> str:
    return path.resolve().relative_to(mr.PROJECT_ROOT.resolve()).as_posix()


def _recorded_sha(rel: str) -> str | None:
    try:
        entries = mr.read_registry()
    except (OSError, ValueError):
        return None
    for entry in reversed(entries):
        info = (entry.get("files") or {}).get(rel)
        if isinstance(info, dict) and info.get("sha256"):
            return str(info["sha256"])
    return None


def _parse_sha_args(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        rel, sep, digest = item.partition("=")
        if not sep or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise SystemExit(f"--sha256 expects PATH=<64 hex chars>, got {item!r}")
        out[rel.replace("\\", "/")] = digest.lower()
    return out


def prove_equivalent(original, restored, *, seed: int = 20260419) -> float:
    """Largest absolute difference between the two scalers on EQUIVALENCE_ROWS random rows."""
    rng = np.random.default_rng(seed)
    n = int(original.n_features_in_)
    scale = 1.0
    if hasattr(original, "data_range_"):
        scale = float(np.max(np.abs(np.asarray(original.data_range_, dtype=np.float64)))) or 1.0
    rows = rng.normal(size=(EQUIVALENCE_ROWS, n)) * scale
    worst = float(np.max(np.abs(original.transform(rows) - restored.transform(rows))))
    worst = max(worst, float(np.max(np.abs(original.inverse_transform(rows) - restored.inverse_transform(rows)))))
    return worst


def _move_to_legacy(path: Path, dry_run: bool) -> str:
    models_dir = mr.PROJECT_ROOT / "models"
    dest = mr.PROJECT_ROOT / LEGACY_DIR / path.resolve().relative_to(models_dir.resolve())
    if dest.exists():
        if mr.sha256_file(dest) != mr.sha256_file(path):
            raise ConversionError(f"{_rel(dest)} already exists with different content; resolve by hand")
        action = "remove stale original (identical copy already in _legacy)"
        if not dry_run:
            path.unlink()
    else:
        action = "move to " + _rel(dest)
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))
    return action


def run(*, dry_run: bool, sha_overrides: dict[str, str]) -> int:
    loaders.enter_training_profile()
    root = mr.PROJECT_ROOT
    plan: list[tuple[Path, Path, str, str]] = []  # (joblib, json, json text, expected sha)

    # Phase 1: load + convert + prove, for every target, before touching anything.
    for directory in TARGET_DIRS:
        joblib_path = root / directory / "scaler.joblib"
        json_path = root / directory / "scaler.json"
        if not joblib_path.exists():
            print(
                f"skip {directory}: no scaler.joblib ({'scaler.json present' if json_path.exists() else 'nothing to do'})"
            )
            continue
        rel = f"{directory}/scaler.joblib"
        expected = sha_overrides.get(rel) or _recorded_sha(rel)
        if not expected:
            print(
                f"FAIL {rel}: no recorded sha256 and none given with --sha256; refusing to unpickle it", file=sys.stderr
            )
            return 1
        try:
            original = loaders.load_legacy_joblib_for_conversion(joblib_path, expected_sha256=expected)
            text = scaler_io.dumps_scaler(original)
        except scaler_io.UnsupportedScalerError as exc:
            print(f"STOP {rel}: {exc}. Nothing was changed.", file=sys.stderr)
            return 2
        except (mr.ModelUnavailableError, scaler_io.ScalerFormatError) as exc:
            print(f"FAIL {rel}: {getattr(exc, 'reason', exc)}", file=sys.stderr)
            return 1
        restored = scaler_io.loads_scaler(text)
        worst = prove_equivalent(original, restored)
        if worst > EQUIVALENCE_TOLERANCE:
            print(f"FAIL {rel}: JSON scaler differs from the pickled one by {worst:.3e}", file=sys.stderr)
            return 1
        print(f"ok   {rel}: {type(original).__name__}, {original.n_features_in_} features, max diff {worst:.1e}")
        plan.append((joblib_path, json_path, text, expected))

    # Phase 2: apply.
    for joblib_path, json_path, text, _expected in plan:
        if json_path.exists() and json_path.read_text(encoding="utf-8") != text:
            print(
                f"FAIL {_rel(json_path)} exists with different content; remove it or resolve by hand", file=sys.stderr
            )
            return 1
        if not dry_run and not json_path.exists():
            scaler_io.dump_scaler_json(scaler_io.loads_scaler(text), json_path)
        print(f"{'would write' if dry_run else 'wrote'} {_rel(json_path)}")
        print(f"{'would ' if dry_run else ''}{_move_to_legacy(joblib_path, dry_run)}   [{_rel(joblib_path)}]")

    models_dir = root / "models"
    legacy_root = (root / LEGACY_DIR).resolve()
    planned = {joblib_path.resolve() for joblib_path, *_ in plan}  # still on disk in a dry run
    strays = sorted(
        p
        for pattern in ("*.joblib", "*.pkl", "*.pickle")
        for p in models_dir.rglob(pattern)
        if legacy_root not in p.resolve().parents and p.resolve() not in planned
    )
    for stray in strays:
        print(
            f"{'would ' if dry_run else ''}{_move_to_legacy(stray, dry_run)}   [{_rel(stray)}] (not converted: unreferenced)"
        )

    if not dry_run and (plan or strays):
        readme = root / LEGACY_DIR / "README.md"
        readme.parent.mkdir(parents=True, exist_ok=True)
        if not readme.exists():
            readme.write_text(LEGACY_README, encoding="utf-8")
    print("dry run: nothing written" if dry_run else "done")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    parser.add_argument(
        "--sha256",
        action="append",
        default=[],
        metavar="PATH=HEX",
        help="expected SHA-256 of a legacy joblib (project-relative path), for files the registry does not cover",
    )
    args = parser.parse_args(argv)
    try:
        return run(dry_run=args.dry_run, sha_overrides=_parse_sha_args(args.sha256))
    except ConversionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    os.umask(0o022)
    raise SystemExit(main())
