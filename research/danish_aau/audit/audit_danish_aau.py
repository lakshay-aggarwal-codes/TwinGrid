#!/usr/bin/env python3
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "realData" / "danish-server-room-v5" / "raw"
OUT_DIR = REPO_ROOT / "research" / "danish_aau" / "reports"
FILES = [
    "AAU_air_speed_25_percent_load_period.csv",
    "AAU_temperature_and_power_use_25_percent_load_period.csv",
    "AAU_supplementary_surrounding_temperatures.csv",
    "AAU_supplementary_ventilation.csv",
]


def find_data_dir():
    if DATA_DIR.exists():
        return DATA_DIR
    for p in REPO_ROOT.rglob("AAU_temperature_and_power_use_25_percent_load_period.csv"):
        return p.parent
    raise FileNotFoundError("not found")


def audit_file(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not rows:
        return {"file": path.name, "error": "empty"}
    header = list(rows[0].keys())
    tc = None
    for k in header:
        if "time" in k.lower() or "date" in k.lower():
            tc = k
            break
    times = []
    bad = 0
    for r in rows:
        try:
            times.append(datetime.strptime(r[tc].strip(), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError, AttributeError, KeyError):
            bad += 1
    res = {"file": path.name, "cols": len(header), "records": len(rows), "time_col": tc, "bad_times": bad}
    if times:
        res["first"] = times[0].isoformat()
        res["last"] = times[-1].isoformat()
        res["duration_s"] = (times[-1] - times[0]).total_seconds()
    time_strs = [r[tc].strip() for r in rows]
    dups = [(k, v) for k, v in Counter(time_strs).items() if v > 1]
    res["dup_timestamp_count"] = len(dups)
    ivals = [(times[i + 1] - times[i]).total_seconds() for i in range(len(times) - 1)]
    res["interval_dist_top"] = Counter(ivals).most_common(10)
    missing = {}
    for c in header:
        miss = sum(
            1
            for r in rows
            if r[c] is None or str(r[c]).strip() == "" or str(r[c]).strip().lower() in ["nan", "na", "null"]
        )
        if miss > 0:
            missing[c] = {"count": miss, "pct": miss / len(rows) * 100}
    res["missing"] = missing
    return res


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data_dir = find_data_dir()
    data_dir_label = data_dir.relative_to(REPO_ROOT).as_posix()
    report = {"data_dir": data_dir_label, "files": []}
    for fn in FILES:
        p = data_dir / fn
        if not p.exists():
            report["files"].append({"file": fn, "error": "not_found"})
            continue
        report["files"].append(audit_file(p))
    try:
        p = data_dir / "AAU_temperature_and_power_use_25_percent_load_period.csv"
        with open(p, encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        header = list(rows[0].keys())
        tc = [k for k in header if "time" in k.lower() or "date" in k.lower()][0]
        time_strs = [r[tc].strip() for r in rows]
        dup_ts = [k for k, v in Counter(time_strs).items() if v == 2]
        details = []
        for ts in dup_ts:
            pair = [r for r in rows if r[tc].strip() == ts]
            diffs = []
            identical = True
            for c in header:
                if c == tc:
                    continue
                if str(pair[0][c]).strip() != str(pair[1][c]).strip():
                    identical = False
                    diffs.append(c)
            details.append({"timestamp": ts, "identical": identical, "diff_columns": diffs})
        report["duplicate_pairs_detail"] = details
    except Exception as e:
        report["duplicate_pairs_detail_error"] = str(e)
    try:
        p = data_dir / "AAU_supplementary_ventilation.csv"
        with open(p, encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        tc = list(rows[0].keys())[0]
        damper_only = []
        for i, r in enumerate(rows):
            v_d = str(r["Room_damper_opening"]).strip()
            miss_d = v_d == "" or v_d.lower() in ["nan", "na", "null"]
            miss_o = False
            for c in [
                "AHU_pressure_supply_duct",
                "AHU_pressure_extraction_duct",
                "AHU_fan_speed_supply",
                "AHU_fan_speed_extraction",
                "AHU_temperature_supply",
            ]:
                v = str(r[c]).strip()
                if v == "" or v.lower() in ["nan", "na", "null"]:
                    miss_o = True
                    break
            if (not miss_d) and miss_o:
                damper_only.append({"index": i, "time": r[tc]})
        pop = [
            r[tc]
            for r in rows
            if not (
                str(r["Room_damper_opening"]).strip() == ""
                or str(r["Room_damper_opening"]).strip().lower() in ["nan", "na", "null"]
            )
        ]
        pop_times = [datetime.strptime(t.strip(), "%Y-%m-%d %H:%M:%S") for t in pop]
        t25_start = datetime(2024, 9, 17, 9, 40, 0)
        t25_end = datetime(2024, 9, 18, 10, 55, 0)
        in25 = sum(1 for t in pop_times if t >= t25_start and t <= t25_end)
        report["ventilation"] = {"damper_only_rows": damper_only, "populated_count": len(pop), "pop_in_25pct": in25}
    except Exception as e:
        report["ventilation_error"] = str(e)
    try:
        p = data_dir / "AAU_supplementary_surrounding_temperatures.csv"
        with open(p, encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        tc = list(rows[0].keys())[0]
        t25_start = datetime(2024, 9, 17, 9, 40, 0)
        t25_end = datetime(2024, 9, 18, 10, 55, 0)
        in25 = 0
        for r in rows:
            try:
                t = datetime.strptime(r[tc].strip(), "%Y-%m-%d %H:%M:%S")
                if t >= t25_start and t <= t25_end:
                    in25 += 1
            except (ValueError, TypeError, AttributeError, KeyError):
                pass
        report["surrounding_in_25pct"] = in25
    except Exception as e:
        report["surrounding_error"] = str(e)
    with open(OUT_DIR / "audit_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    md = ["# Danish AAU Audit Report\n", f"Data dir: {data_dir_label}\n"]
    for fitem in report["files"]:
        md.append(f"## {fitem.get('file')}\n")
        for k, v in fitem.items():
            if k == "missing" and v:
                md.append("Missing:\n")
                for ck, cv in v.items():
                    md.append(f"- {ck}: {cv['count']} ({cv['pct']:.4f}%)\n")
            elif k != "file":
                md.append(f"- {k}: {v}\n")
        md.append("\n")
    md.append(f"## Duplicates: {len(report.get('duplicate_pairs_detail',[]))}\n")
    md.append(f"## Ventilation: {report.get('ventilation')}\n")
    md.append(f"## Surrounding in 25%: {report.get('surrounding_in_25pct')}\n")
    with open(OUT_DIR / "audit_report.md", "w") as f:
        f.writelines(md)
    print("done")


if __name__ == "__main__":
    main()
