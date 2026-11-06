"""Owner-run, READ-ONLY check of Task 12 on the REAL files. Writes an aggregate JSON only (no row values, no raw rows).

    python -m research.danish_aau.cleaning.local_run --raw .\\realData\\danish-server-room-v5\\raw --out ..\\task12_local_run.json

What it does (nothing is written inside the raw folder; RawDataGuard raises if any raw file changes):
  A  index-only profile of all 16 CSVs through the Task 11 adapter: rows, first/last timestamp text, repeated-timestamp
     groups and extra rows, cadence (step histogram, large steps with the timestamp texts at both ends), compared with
     the Task 4 table. Differences are listed, never hidden.
  B  cleaning of the full temperature/power file (and, with --include-periods, the six period files) with the locked
     protocol: one disposition per raw row, ledger reconciliation, comparison with the Task 6 ledger (all 51 columns),
     and the TIER 1 numbers (37 rack probes + 3 power channels) that the Task 15 loader will verify against.
  C  how many cells the flatline flag WOULD mark at the protocol run length (reported only, never applied).
No timezone or UTC logic anywhere; timestamps stay naive source text.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from ..adapter.reader import AdapterReader
from ..adapter.schema import FILE_SPECS
from ..adapter.source import DEFAULT_MANIFEST, discover_all
from ..evaluation.guard import RawDataGuard
from ..protocol.lock import verify as verify_lock
from ..protocol.protocol import load_protocol, protocol_sha256
from .cadence import cadence_profile
from .config import CleanConfig
from .flags import apply_flags, flatline_report
from .l1 import code_sha256
from .ledger import disposition_counts, ledger_summary, reconcile
from .reference import TASK4_AIR_SPEED, TASK6, compare_ledger, compare_profile
from .resolve import clean_file
from .tier1 import POWER_COLUMNS, TIER1_COLUMNS

TOOL = "task12_cleaning_local_run 1.0"
CLEAN_KEYS = ("temperature_power",)
PERIOD_KEYS = (
    "temperature_power_idle_1",
    "temperature_power_25",
    "temperature_power_50",
    "temperature_power_75",
    "temperature_power_100",
    "temperature_power_idle_2",
)


def _say(on: bool):
    return (
        (lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}", file=sys.stderr, flush=True)) if on else (lambda m: None)
    )


def profile_file(key: str, src) -> tuple[dict, AdapterReader]:
    r = AdapterReader(src)
    idx = r.build_index()
    in_groups = int((idx.dup_size > 1).sum())
    groups = int(len({int(g) for g in idx.dup_group[idx.dup_size > 1]}))
    extra = in_groups - groups
    entry = {
        "filename": src.spec.filename,
        "rows": int(idx.n_rows),
        "first_ts_text": str(idx.ts_text[0]),
        "last_ts_text": str(idx.ts_text[-1]),
        "rows_in_repeated_timestamp_groups": in_groups,
        "repeated_timestamp_groups": groups,
        "extra_rows": extra,
        "cadence": cadence_profile(idx.ts_ns, idx.ts_text, src.spec.nominal_interval_s),
    }
    entry["task4_differences"] = compare_profile(
        key, entry["rows"], entry["first_ts_text"], entry["last_ts_text"], groups, extra
    )
    if src.spec.family == "air_speed":
        lo, hi = TASK4_AIR_SPEED["rows_min"], TASK4_AIR_SPEED["rows_max"]
        if not lo <= entry["rows"] <= hi or groups != 0:
            entry["task4_differences"].append(
                f"{key}: rows {entry['rows']} outside Task 4 range {lo}-{hi} or repeats != 0"
            )
    return entry, r


def run(
    raw: Path,
    *,
    include_periods: bool = False,
    rerun: bool = False,
    manifest_path: Path | None = DEFAULT_MANIFEST,
    progress: bool = False,
    keys: list[str] | None = None,
) -> dict:
    say = _say(progress)
    protocol = load_protocol()
    lock = verify_lock()
    report: dict = {
        "tool": TOOL,
        "python": sys.version,
        "platform": platform.platform(),
        "protocol": {"version": lock["version"], "sha256_lf": protocol_sha256(), "lock_ok": True},
        "cleaning_code_sha256": code_sha256(),
        "time_basis": "naive source text, timezone undeclared (no UTC conversion)",
        "profile": {},
        "cleaning": {},
    }
    wanted = list(keys) if keys else [s.key for s in FILE_SPECS]
    with RawDataGuard(raw):
        sources = discover_all(raw, wanted, manifest_path=manifest_path)
        readers: dict[str, AdapterReader] = {}
        for key, src in sources.items():
            t0 = time.time()
            say(f"A profile {key}")
            entry, rdr = profile_file(key, src)
            entry["seconds"] = round(time.time() - t0, 1)
            report["profile"][key] = entry
            readers[key] = rdr
        report["task4_differences"] = [d for e in report["profile"].values() for d in e["task4_differences"]]
        if "air_speed_50" in report["profile"]:
            cad = report["profile"]["air_speed_50"]["cadence"]
            report["air_speed_50_cadence_gap"] = {
                "max_step_s": cad.get("max_step_s"),
                "max_step_between": cad.get("max_step_between"),
                "steps_above_threshold": cad.get("steps_above_threshold"),
                "threshold_s": cad.get("big_step_threshold_s"),
                "largest_steps": cad.get("largest_steps"),
                "full_file_largest_for_comparison": (
                    report["profile"].get("air_speed", {}).get("cadence", {}) or {}
                ).get("max_step_s"),
            }
        clean_keys = [k for k in (*CLEAN_KEYS, *(PERIOD_KEYS if include_periods else ())) if k in sources]
        protocol_run = protocol.family()["flatline_min_run"]
        gap = protocol.family()["gap_min_step_seconds"]
        for key in clean_keys:
            t0 = time.time()
            say(f"B clean {key}")
            res = clean_file(readers[key], protocol, index_built=True, progress=None)
            res = apply_flags(res, protocol, CleanConfig())  # defaults: no flags
            counts = disposition_counts(res)
            by_col_all = res.stats["cells_made_missing_by_column"]
            by_col_t1 = {c: by_col_all.get(c, 0) for c in TIER1_COLUMNS}
            n_t1 = len(TIER1_COLUMNS)
            ties_t1 = sum(by_col_t1.values())
            entry = {
                "ledger": ledger_summary(res),
                "ledger_problems": reconcile(res),
                "stats_all_51_columns": {
                    k: res.stats[k]
                    for k in (
                        "raw_rows",
                        "unique_seconds",
                        "group_sizes",
                        "cells_made_missing_all_columns",
                        "blank_cells_all_columns",
                        "ambiguous_cells_all_columns",
                        "groups_with_ties",
                    )
                },
                "tier1": {
                    "columns": n_t1,
                    "rack_probe_columns": n_t1 - len(POWER_COLUMNS),
                    "power_columns": len(POWER_COLUMNS),
                    "stored_cells": n_t1 * res.n_seconds,
                    "cells_made_missing_by_tie": ties_t1,
                    "cells_made_missing_by_tie_rack_probes": sum(
                        v for c, v in by_col_t1.items() if c not in POWER_COLUMNS
                    ),
                    "cells_made_missing_by_tie_power": sum(by_col_t1[c] for c in POWER_COLUMNS),
                    "blank_cells": int(((~res.valid) & (res.reason == 2)).sum()),
                    "observed_cells": int(res.valid.sum()),
                    "groups_with_tier1_ties": res.stats["groups_with_tier1_ties"],
                    "groups_with_ties_only_outside_tier1": res.stats["groups_with_ties_only_outside_tier1"],
                    "cells_made_missing_by_column": by_col_t1,
                    "all_51_minus_tier1_ties": res.stats["cells_made_missing_all_columns"] - ties_t1,
                },
                "flatline_would_flag_not_applied": {
                    k: v for k, v in flatline_report(res, protocol_run, gap).items() if k != "by_column"
                },
                "result_digest": res.digest(),
            }
            diffs = compare_ledger(key, res.stats, counts, res.n_seconds)
            if res.stats["ambiguous_cells_all_columns"] != TASK6.get(key, {}).get(
                "rerounded", res.stats["ambiguous_cells_all_columns"]
            ):
                diffs.append(
                    f"{key}: near-tie re-rounded cells {res.stats['ambiguous_cells_all_columns']} vs Task 6 {TASK6[key]['rerounded']} (informational)"
                )
            entry["task6_differences"] = diffs
            if rerun:
                say(f"B rerun {key}")
                again = apply_flags(clean_file(readers[key], protocol, index_built=True), protocol, CleanConfig())
                entry["rerun_digest_identical"] = again.digest() == entry["result_digest"]
            entry["seconds"] = round(time.time() - t0, 1)
            report["cleaning"][key] = entry
            say(f"B done {key} in {entry['seconds']} s")
        report["task6_differences"] = [d for e in report["cleaning"].values() for d in e["task6_differences"]]
        report["tier1_conflict_missing_cells_full_file"] = (
            report["cleaning"].get("temperature_power", {}).get("tier1", {}).get("cells_made_missing_by_tie")
        )
    report["raw_directory_unchanged"] = True  # RawDataGuard raises otherwise
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--include-periods", action="store_true", help="also clean the six period files (subsets of the full file)"
    )
    ap.add_argument(
        "--rerun", action="store_true", help="clean each file twice and compare the result digests (doubles the time)"
    )
    ap.add_argument("--keys", nargs="*")
    a = ap.parse_args()
    raw, out = Path(a.raw).resolve(), Path(a.out).resolve()
    if raw in out.parents:
        sys.exit("refusing: --out must be outside the raw directory")
    rep = run(raw, include_periods=a.include_periods, rerun=a.rerun, keys=a.keys, progress=True)
    out.write_text(json.dumps(rep, indent=2, sort_keys=True), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
