#!/usr/bin/env python3
"""Compact schema report for ./realData (v2 of detailed_dataset_report.py).

Run from the project root (DigitalTwin-main):
    pip install pandas xlrd openpyxl        # xlrd is needed for the .xls files
    python detailed_dataset_report_v2.py

Writes detailed_dataset_report.txt. Metadata, schemas, row counts and tiny samples only.
Secrets (api keys, tokens, passwords) in scripts are redacted, but READ THE REPORT
before sharing it.
"""

import re
from pathlib import Path

import pandas as pd

ROOT = Path("realData")
OUTPUT = Path("detailed_dataset_report.txt")
SAMPLE = 3
CLIP = 260

SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|bearer)\s*([=:])\s*\S+")


def size_string(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def section(title):
    return ["", "=" * 90, title, "=" * 90]


def clip(s, k=CLIP):
    s = str(s).replace("\n", " ")
    return s if len(s) <= k else s[:k] + "..."


def redact(line):
    return SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)} ***REDACTED***", line)


def count_rows(path):
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return max(n - 1, 0)


def last_line(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(size - 4096, 0))
        tail = f.read().decode("utf-8", errors="replace").strip().splitlines()
    return tail[-1] if tail else ""


def csv_info(path, sample=SAMPLE, with_tail=True):
    L = [f"FILE: {path.relative_to(ROOT)}  ({size_string(path.stat().st_size)})"]
    try:
        head = pd.read_csv(path, nrows=sample, low_memory=False, on_bad_lines="skip")
        L.append(f"COLUMNS ({len(head.columns)}): " + ", ".join(map(str, head.columns)))
        L.append(f"ROWS (approx): {count_rows(path):,}")
        for i, row in head.iterrows():
            L.append(f"  row{i}: " + clip(", ".join(f"{k}={v}" for k, v in row.items())))
        if with_tail:
            L.append("  last line: " + clip(last_line(path)))
    except Exception as e:  # noqa: BLE001
        L.append(f"ERROR: {type(e).__name__}: {e}")
    return L


def excel_info(path, sheets_limit=4):
    L = [f"FILE: {path.relative_to(ROOT)}  ({size_string(path.stat().st_size)})"]
    try:
        xls = pd.ExcelFile(path)
        L.append(f"SHEETS ({len(xls.sheet_names)}): " + ", ".join(xls.sheet_names[:20]))
        for sh in xls.sheet_names[:sheets_limit]:
            df = pd.read_excel(path, sheet_name=sh, nrows=SAMPLE)
            L.append(f" SHEET '{sh}' columns ({len(df.columns)}): " + clip(", ".join(map(str, df.columns)), 700))
            for i, row in df.head(1).iterrows():
                L.append("  row0: " + clip(", ".join(f"{k}={v}" for k, v in row.items())))
    except Exception as e:  # noqa: BLE001
        L.append(f"ERROR: {type(e).__name__}: {e}  (for .xls run: pip install xlrd)")
    return L


def text_head(path, n=10, redact_secrets=False):
    L = [f"FILE: {path.relative_to(ROOT)}  ({size_string(path.stat().st_size)})", f"FIRST {n} LINES:"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= n:
                    break
                line = line.rstrip()
                L.append("  " + clip(redact(line) if redact_secrets else line, 200))
    except Exception as e:  # noqa: BLE001
        L.append(f"ERROR: {e}")
    return L


def folder_overview(folder, top=12):
    by_ext = {}
    for p in folder.rglob("*"):
        if p.is_file():
            e = p.suffix.lower() or "(none)"
            c, s = by_ext.get(e, (0, 0))
            by_ext[e] = (c + 1, s + p.stat().st_size)
    return [
        f"  {e}: {c} files, {size_string(s)}" for e, (c, s) in sorted(by_ext.items(), key=lambda kv: -kv[1][1])[:top]
    ]


# ---------------------------------------------------------------- sections


def top_level_sizes(R):
    R += section("0. SIZE BY TOP-LEVEL ITEM (where the 6 GB is)")
    rows = []
    for p in ROOT.iterdir():
        if p.is_dir():
            rows.append((sum(q.stat().st_size for q in p.rglob("*") if q.is_file()), p.name + "/"))
        else:
            rows.append((p.stat().st_size, p.name))
    for s, n in sorted(rows, reverse=True):
        R.append(f"  {size_string(s):>10}  {n}")


def open_meteo(R):
    R += section("1. OPEN-METEO (hourly weather per city)")
    files = sorted((ROOT / "open_meteo").glob("*.csv"))
    R.append(f"CSV files: {len(files)}")
    headers = {}
    for p in files:
        h = tuple(pd.read_csv(p, nrows=0).columns)
        headers.setdefault(h, []).append(p.name)
    R.append(f"Distinct headers across files: {len(headers)}")
    for h, names in headers.items():
        R.append(f"  header ({len(names)} files): {', '.join(h)}")
    for p in files:
        try:
            first = pd.read_csv(p, nrows=1).iloc[0, 0]
            R.append(f"  {p.name}: rows {count_rows(p):,}, first {first}, last {clip(last_line(p).split(',')[0])}")
        except Exception as e:  # noqa: BLE001
            R.append(f"  {p.name}: ERROR {e}")
    pick = next((p for p in files if p.name.startswith("delhi")), files[0] if files else None)
    if pick:
        R += csv_info(pick)
    script = ROOT / "open_meteo" / "download_weather.py"
    if script.exists():
        R += text_head(script, 40, True)


def specpower(R):
    R += section("2. SPECPOWER")
    for p in ROOT.glob("power_ssj2008*.csv"):
        R += csv_info(p, 2)


def cmapss(R):
    R += section("3. NASA C-MAPSS")
    for p in sorted((ROOT / "CMAPSSData").glob("*.txt")):
        if p.name.lower() == "readme.txt":
            R += text_head(p, 25)
        elif p.name.startswith("train_FD001"):
            R += text_head(p, 3)
    R.append("Other files: " + ", ".join(p.name for p in sorted((ROOT / "CMAPSSData").iterdir())))


def nab(R):
    R += section("4. NAB")
    base = ROOT / "NAB-master"
    csvs = sorted(base.rglob("*.csv"))
    R.append(f"CSV files: {len(csvs)}")
    wanted = (
        "machine_temperature_system_failure",
        "ambient_temperature_system_failure",
        "ec2_cpu_utilization_24ae8d",
        "nyc_taxi",
    )
    for p in csvs:
        if p.stem in wanted:
            R += csv_info(p, 2)
    for p in sorted((base / "labels").rglob("*.json")):
        R.append(f"  label file: {p.relative_to(ROOT)} ({size_string(p.stat().st_size)})")
    cl = base / "labels" / "combined_labels.json"
    if cl.exists():
        R += text_head(cl, 8)


def electricity_maps(R):
    R += section("5. ELECTRICITY MAPS")
    for p in sorted((ROOT / "electricity_maps").rglob("*")):
        if p.is_file():
            if p.suffix == ".py":
                R += text_head(p, 60, True)
            elif p.suffix == ".csv":
                R += csv_info(p)
            else:
                R.append(f"  {p.name}: {size_string(p.stat().st_size)}")
    cov = next(ROOT.glob("*electricity-maps-coverage*.csv"), None)
    if cov:
        R += csv_info(cov)


def ashrae_energy(R):
    R += section("6. ASHRAE GREAT ENERGY PREDICTOR (buildings)")
    for p in sorted((ROOT / "ashrae-energy-prediction").glob("*.csv")):
        R += csv_info(p, 2, with_tail=False)


def rp1043(R):
    R += section("7. ASHRAE RP-1043 (chiller fault data)")
    base = ROOT / "ASHRAE RP-1043" / "Chiller Data"
    R.append("Files per folder:")
    for d in sorted(p for p in base.rglob("*") if p.is_dir()):
        n = len([f for f in d.iterdir() if f.is_file()])
        R.append(f"  {d.relative_to(base)}: {n} files")
    for name in ("read me first.xls", "11000.xlsx"):
        p = base / name
        if p.exists():
            R += excel_info(p, 3)
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        first = next(iter(sorted(d.rglob("*.xls"))), None)
        if first:
            R += excel_info(first, 1)
            break  # one representative data workbook is enough
    pdf = next(ROOT.glob("ASHRAE_TC0909*.pdf"), None)
    if pdf:
        R.append(f"PDF: {pdf.name} ({size_string(pdf.stat().st_size)})")


def aqueduct(R):
    R += section("8. AQUEDUCT")
    for name in ("aqueduct-4-0-country-rankings", "aqueduct-4-0-water-risk-data"):
        base = ROOT / name
        if not base.exists():
            continue
        R.append(f"{name}:")
        R += folder_overview(base)
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix.lower() == ".csv":
                R += csv_info(p, 2, with_tail=False)
            elif p.is_file() and p.suffix.lower() in {".xlsx", ".xls"}:
                R += excel_info(p, 2)
    x = next(ROOT.glob("aqueduct-water-stress*.xlsx"), None)
    if x:
        R += excel_info(x, 3)


def cluster(R):
    R += section("9. CLUSTER TRACES (Google / Alibaba)")
    for name in ("cluster-data-master", "clusterdata-master"):
        base = ROOT / name
        if not base.exists():
            continue
        R.append(f"{name}: overview by extension")
        R += folder_overview(base)
    # real trace data present? (large files)
    big = [
        p
        for n in ("cluster-data-master", "clusterdata-master")
        for p in (ROOT / n).rglob("*")
        if p.is_file() and p.stat().st_size > 5 * 1024 * 1024
    ]
    R.append(f"Files > 5 MB in cluster folders: {len(big)}")
    for p in big[:10]:
        R.append(f"  {p.relative_to(ROOT)} ({size_string(p.stat().st_size)})")
    for rel in ("cluster-data-master/PowerData2019.md", "clusterdata-master/cluster-trace-gpu-v2020/data/README.md"):
        p = ROOT / rel
        if p.exists():
            R += text_head(p, 40)
    for p in sorted((ROOT / "clusterdata-master" / "cluster-trace-gpu-v2020" / "data").glob("*.header")):
        R += text_head(p, 3)


def main():
    R = [
        "TWINGRID DATASET SCHEMA REPORT (v2)",
        f"ROOT: {ROOT.resolve()}",
        "Metadata, schemas and tiny samples only. Secrets redacted in scripts.",
    ]
    for step in (
        top_level_sizes,
        open_meteo,
        specpower,
        cmapss,
        nab,
        electricity_maps,
        ashrae_energy,
        rp1043,
        aqueduct,
        cluster,
    ):
        try:
            step(R)
        except Exception as e:  # noqa: BLE001
            R.append(f"[{step.__name__}] FAILED: {type(e).__name__}: {e}")
    OUTPUT.write_text("\n".join(R), encoding="utf-8")
    print(f"Wrote {OUTPUT.resolve()} ({OUTPUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
