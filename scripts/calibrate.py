#!/usr/bin/env python3
"""Calibrate physics v2 against YOUR measured facility telemetry (roadmap Task 23).

    python scripts/calibrate.py --tidy-csv facility.csv --dataset-id HALL-A-2026Q3 --cadence-s 300 --out calibration_report.json
    python scripts/calibrate.py --selftest            # synthetic parameter recovery; proves the pipeline, calibrates nothing

``facility.csv`` columns: ts (ISO-8601 WITH timezone), channel, value, unit, quality.
Channels / units: utilisation fraction | outside_temp_c degC | humidity_pct percent | chw_requested_c degC |
it_power_kw kW | t_in_c degC | t_out_c degC | cooling_power_kw kW | cooling_mode enum (free_air, closed_loop, evaporative, hybrid).

The pre-registration is written BEFORE the fit, next to the report, and reused (verified, never rewritten) on re-runs.
Raw files stay local: the report stores the dataset id and the file's SHA-256 only.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration import calibrate, from_tidy_rows, make_preregistration  # noqa: E402
from src.calibration.synthetic import synthetic_dataset  # noqa: E402
from src.physics.params import DEFAULT_PHYSICS_PARAMS  # noqa: E402


def _selftest(out: Path) -> dict:
    truth = dataclasses.replace(
        DEFAULT_PHYSICS_PARAMS, max_it_power_kw=620.0, idle_power_fraction=0.35, cop_closed_loop=5.2, tau_air_min=14.0
    )
    data = synthetic_dataset(truth, days=6, seed=1)
    pre = make_preregistration(data)
    rep = calibrate(data, pre, max_iter=25)
    print("synthetic recovery (truth -> fitted):")
    for name in ("max_it_power_kw", "idle_power_fraction", "cop_closed_loop", "tau_air_min"):
        print(f"  {name:22s} {getattr(truth, name):>9.4g} -> {rep['parameters'][name]['fitted']:.4g}")
    return {"preregistration": pre, "report": rep}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tidy-csv", type=Path)
    ap.add_argument("--dataset-id")
    ap.add_argument("--cadence-s", type=float)
    ap.add_argument("--out", type=Path, default=Path("calibration_report.json"))
    ap.add_argument("--prereg", type=Path, help="pre-registration file; created if missing, verified if present")
    ap.add_argument("--n-boot", type=int, default=0, help="block-bootstrap resamples (days) for parameter intervals")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        out = _selftest(a.out)
        a.out.write_text(json.dumps(out, indent=2, allow_nan=False), encoding="utf-8")
        print(f"label: {out['report']['label']}\nwrote {a.out}")
        return 0

    if not (a.tidy_csv and a.dataset_id and a.cadence_s):
        ap.error("--tidy-csv, --dataset-id and --cadence-s are required (or use --selftest)")
    sha = hashlib.sha256(a.tidy_csv.read_bytes()).hexdigest()
    with a.tidy_csv.open(newline="", encoding="utf-8") as fh:
        data = from_tidy_rows(csv.DictReader(fh), dataset_id=a.dataset_id, cadence_s=a.cadence_s)
    print("schema report:", json.dumps(data.report, indent=2))

    prereg_path = a.prereg or a.out.with_suffix(".prereg.json")
    if prereg_path.exists():
        pre = json.loads(prereg_path.read_text(encoding="utf-8"))
        print(f"using existing pre-registration {prereg_path}")
    else:
        pre = make_preregistration(data)
        prereg_path.write_text(json.dumps(pre, indent=2, allow_nan=False), encoding="utf-8")
        print(f"wrote pre-registration {prereg_path} (sha256 {pre['sha256'][:16]}...)")

    rep = calibrate(data, pre, n_boot=a.n_boot)
    rep["input_file_sha256"] = sha
    rep["import_report"] = data.report
    a.out.write_text(json.dumps(rep, indent=2, allow_nan=False), encoding="utf-8")
    print(f"verdict: {rep['verdict']}\nlabel:   {rep['label']}\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
