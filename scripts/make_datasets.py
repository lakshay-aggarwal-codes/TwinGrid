#!/usr/bin/env python3
"""Regenerate the leakage-safe datasets v2 from hashed inputs (T25, roadmap sections 11 and 13.3).

    python scripts/make_datasets.py --plan-only                 # what WOULD be generated; needs no inputs
    python scripts/make_datasets.py --register-inputs           # hash cleaned inputs -> data/cleaned/MANIFEST.json
    python scripts/make_datasets.py                             # generate; output: data/datasets/<dataset_id>/

Inputs: data/cleaned/weather_open_meteo.csv and data/cleaned/water_stress_aqueduct.csv, each checked against
data/cleaned/MANIFEST.json (sha256). A missing input is an ERROR. ``--allow-synthetic-weather`` /
``--allow-synthetic-water-stress`` substitute synthetic data and record it as ``synthetic_inputs`` in the manifest.

Output ``data/datasets/<dataset_id>/``: train.csv, val.csv, test.csv, events.csv, scenarios.csv, manifest.json.
``dataset_id`` is the SHA-256 of the canonical manifest, which holds the hashes of every output file, the split and
scenario config ids, the input hashes, the preprocessing statistics (fit on train only, ``fit_split_id`` recorded) and
the software environment. Same configs + same inputs + same environment => same id.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import data_generator as gen  # noqa: E402
from src import data_pipeline as dp  # noqa: E402

FLOAT_FORMAT = "%.6f"
DATASETS_DIR = REPO_ROOT / "data" / "datasets"
MANIFEST_SCHEMA = 1


def _write_csv(df: pd.DataFrame, path: Path) -> dict[str, Any]:
    df.to_csv(path, index=False, float_format=FLOAT_FORMAT, lineterminator="\n")
    return {"sha256": dp.sha256_file(path), "rows": int(len(df))}


def plan(split_cfg: dict[str, Any], scenario_cfg: dict[str, Any]) -> dict[str, Any]:
    scenarios = dp.build_scenarios(split_cfg, scenario_cfg)
    per_split = {s: sum(1 for sc in scenarios if sc.split == s) for s in dp.SPLITS}
    events = dp.planned_event_counts(split_cfg, scenario_cfg)
    rows = scenario_cfg["days_per_scenario"] * 24 * 60 // scenario_cfg["interval_minutes"]
    return {
        "split_id": split_cfg["split_id"],
        "scenario_set_id": scenario_cfg["scenario_set_id"],
        "cells": {s: len(split_cfg["cells"][s]) for s in dp.SPLITS},
        "scenarios": per_split,
        "rows": {s: n * rows for s, n in per_split.items()},
        "planned_events": events,
        "min_test_events": scenario_cfg.get("min_test_events"),
    }


def build_dataset(
    split_cfg: dict[str, Any],
    scenario_cfg: dict[str, Any],
    *,
    out_dir: Path = DATASETS_DIR,
    weather_path: Path = gen.CLEANED_WEATHER_PATH,
    water_stress_path: Path = gen.CLEANED_WATER_STRESS_PATH,
    registry_path: Path = dp.CLEANED_MANIFEST_PATH,
    allow_synthetic_weather: bool = False,
    allow_synthetic_water_stress: bool = False,
) -> tuple[str, Path]:
    """Generate the dataset and return ``(dataset_id, directory)``. Raises on any missing input or leakage."""
    scenarios = dp.build_scenarios(split_cfg, scenario_cfg)
    planned = dp.planned_event_counts(split_cfg, scenario_cfg)
    minimum = int(scenario_cfg.get("min_test_events", 0))
    if planned["test"] < minimum:
        raise dp.DatasetConfigError(
            f"the configs plan {planned['test']} test events, fewer than {minimum}: raise the injection counts "
            "or scenarios_per_cell in configs/scenarios, do not lower the threshold"
        )

    # ---- inputs: required, hash-checked; synthetic only when explicitly allowed (and then recorded)
    synthetic: set[str] = set()
    input_paths: list[Path] = []
    weather = None
    if Path(weather_path).is_file() or not allow_synthetic_weather:
        input_paths.append(Path(weather_path))
        weather = gen.load_cleaned_weather(Path(weather_path))
    baseline = None
    if Path(water_stress_path).is_file() or not allow_synthetic_water_stress:
        input_paths.append(Path(water_stress_path))
        baseline = gen.load_water_stress_baseline(split_cfg.get("country", "India"), Path(water_stress_path))
    inputs = dp.verify_cleaned_inputs(input_paths, Path(registry_path)) if input_paths else []

    # ---- generate every scenario
    frames: dict[str, list[pd.DataFrame]] = {s: [] for s in dp.SPLITS}
    event_frames: list[pd.DataFrame] = []
    city_cache: dict[str, Any] = {}
    physics_version = None
    for scenario in scenarios:
        df, events, used = gen.generate_scenario(
            scenario,
            split_cfg,
            scenario_cfg,
            weather=weather,
            water_stress_baseline=baseline,
            allow_synthetic_weather=allow_synthetic_weather,
            allow_synthetic_water_stress=allow_synthetic_water_stress,
            _city_cache=city_cache,
        )
        synthetic.update(used)
        physics_version = physics_version or df.attrs["physics_version"]
        frames[scenario.split].append(df)
        event_frames.append(events)
    data = {s: pd.concat(frames[s], ignore_index=True) for s in dp.SPLITS}
    events = pd.concat(event_frames, ignore_index=True)

    # ---- leakage checks on the REALISED data
    membership = pd.concat([d[["scenario_id", "split", "city", "month_block"]] for d in data.values()])
    dp.assert_membership_disjoint(membership)
    rows_per_scenario = {sid: (0, int(n)) for sid, n in membership.groupby("scenario_id").size().items()}
    dp.assert_events_within_scenarios(events, rows_per_scenario)
    n_test_events = int((events["split"] == "test").sum())
    if n_test_events < minimum:
        raise dp.DatasetConfigError(f"only {n_test_events} test events were generated (< {minimum})")
    seen = pd.concat([data["train"], data["val"]])
    test = data["test"]
    if not set(test["city"]) - set(seen["city"]) or not set(test["month_block"]) - set(seen["month_block"]):
        raise dp.DatasetConfigError("test lacks an unseen city or an unseen month-block")
    if not set(test["regime"]) - set(seen["regime"]):
        raise dp.DatasetConfigError("test lacks a held-out workload regime")

    # ---- preprocessing: fit on TRAIN rows only
    fit_split_id = f"{split_cfg['split_id']}#train"
    preprocessing = dp.fit_preprocessing(data["train"], fit_split_id=fit_split_id)

    # ---- write, hash, id
    out_dir = Path(out_dir)
    staging = out_dir / f".staging-{split_cfg['split_id'][:12]}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    files = {f"{s}.csv": _write_csv(data[s], staging / f"{s}.csv") for s in dp.SPLITS}
    files["events.csv"] = _write_csv(events, staging / "events.csv")
    scenario_table = pd.DataFrame([sc.as_dict() for sc in scenarios])
    files["scenarios.csv"] = _write_csv(scenario_table, staging / "scenarios.csv")

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generator_version": gen.GENERATOR_VERSION,
        "physics_version": physics_version,
        "split_id": split_cfg["split_id"],
        "scenario_set_id": scenario_cfg["scenario_set_id"],
        "inputs": inputs,
        "synthetic_inputs": sorted(synthetic),
        "files": files,
        "scenarios": {s: int((scenario_table["split"] == s).sum()) for s in dp.SPLITS},
        "events": {
            "per_split": {s: int((events["split"] == s).sum()) for s in dp.SPLITS},
            "per_type": {t: int(n) for t, n in events["type"].value_counts().sort_index().items()},
        },
        "preprocessing": preprocessing,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
    }
    ident = dp.dataset_id(manifest)
    manifest["dataset_id"] = ident
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    final = out_dir / ident
    if final.exists():
        if dp.sha256_file(final / "manifest.json") != dp.sha256_file(staging / "manifest.json"):
            raise dp.DatasetConfigError(f"{final} exists with a different manifest")
        shutil.rmtree(staging)
    else:
        staging.rename(final)
    return ident, final


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", type=Path, default=dp.DEFAULT_SPLIT_PATH)
    ap.add_argument("--scenarios", type=Path, default=dp.DEFAULT_SCENARIO_PATH)
    ap.add_argument("--out", type=Path, default=DATASETS_DIR)
    ap.add_argument("--plan-only", action="store_true", help="print the plan implied by the configs; read no data")
    ap.add_argument("--register-inputs", action="store_true", help="write data/cleaned/MANIFEST.json from the files")
    ap.add_argument("--allow-synthetic-weather", action="store_true")
    ap.add_argument("--allow-synthetic-water-stress", action="store_true")
    args = ap.parse_args(argv)

    split_cfg = dp.load_split_config(args.split)
    scenario_cfg = dp.load_scenario_config(args.scenarios)

    if args.plan_only:
        print(json.dumps(plan(split_cfg, scenario_cfg), indent=2, sort_keys=True))
        return 0
    if args.register_inputs:
        manifest = dp.register_cleaned_inputs([gen.CLEANED_WEATHER_PATH, gen.CLEANED_WATER_STRESS_PATH])
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    ident, directory = build_dataset(
        split_cfg,
        scenario_cfg,
        out_dir=args.out,
        allow_synthetic_weather=args.allow_synthetic_weather,
        allow_synthetic_water_stress=args.allow_synthetic_water_stress,
    )
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    print(f"dataset_id {ident}\n{directory}")
    print(json.dumps({"events": manifest["events"], "synthetic_inputs": manifest["synthetic_inputs"]}, indent=2))
    if manifest["synthetic_inputs"]:
        print("WARNING: this dataset contains SYNTHETIC inputs (see synthetic_inputs); it is not a real-input dataset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
