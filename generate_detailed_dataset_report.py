from pathlib import Path

import pandas as pd

ROOT = Path("realData")
OUTPUT = Path("detailed_dataset_report.txt")

MAX_SAMPLE_ROWS = 5


# ============================================================
# GENERAL HELPERS
# ============================================================

def size_string(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.2f} KB"
    if size < 1024**3:
        return f"{size / (1024**2):.2f} MB"
    return f"{size / (1024**3):.2f} GB"


def section(title):
    return [
        "",
        "=" * 100,
        title,
        "=" * 100,
    ]


def csv_info(path, sample_rows=5):
    lines = []

    lines.append(f"FILE: {path}")
    lines.append(f"SIZE: {size_string(path.stat().st_size)}")

    try:
        # Header only
        header = pd.read_csv(
            path,
            nrows=0,
            low_memory=False,
            on_bad_lines="skip"
        )

        lines.append(f"COLUMNS: {len(header.columns)}")

        for col in header.columns:
            lines.append(f"  - {col}")

        # Small sample
        sample = pd.read_csv(
            path,
            nrows=sample_rows,
            low_memory=False,
            on_bad_lines="skip"
        )

        lines.append(f"SAMPLE ROWS: {len(sample)}")
        lines.append(sample.to_string(index=False))

    except Exception as e:
        lines.append(f"ERROR: {type(e).__name__}: {e}")

    return lines


def excel_info(path):
    lines = []

    lines.append(f"FILE: {path}")
    lines.append(f"SIZE: {size_string(path.stat().st_size)}")

    try:
        xls = pd.ExcelFile(path)

        lines.append(f"SHEETS: {len(xls.sheet_names)}")

        for sheet in xls.sheet_names:
            lines.append(f"\nSHEET: {sheet}")

            df = pd.read_excel(
                path,
                sheet_name=sheet,
                nrows=MAX_SAMPLE_ROWS
            )

            lines.append(f"COLUMNS: {len(df.columns)}")

            for col in df.columns:
                lines.append(f"  - {col}")

            lines.append("SAMPLE:")
            lines.append(df.to_string(index=False))

    except Exception as e:
        lines.append(f"ERROR: {type(e).__name__}: {e}")

    return lines


def text_info(path):
    lines = []

    lines.append(f"FILE: {path}")
    lines.append(f"SIZE: {size_string(path.stat().st_size)}")

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = []

            for i, line in enumerate(f):
                if i >= 10:
                    break

                content.append(line.rstrip())

        lines.append("FIRST 10 LINES:")
        lines.extend(content)

    except Exception as e:
        lines.append(f"ERROR: {type(e).__name__}: {e}")

    return lines


# ============================================================
# 1. OPEN-METEO
# ============================================================

def inspect_open_meteo(report):

    report.extend(section("1. OPEN-METEO"))

    folder = ROOT / "open_meteo"

    if not folder.exists():
        report.append("NOT FOUND")
        return

    files = sorted(folder.glob("*.csv"))

    report.append(f"CSV FILES FOUND: {len(files)}")

    for path in files:

        report.extend(section(f"OPEN-METEO FILE: {path.name}"))

        report.extend(csv_info(path))


# ============================================================
# 2. SPECPOWER
# ============================================================

def inspect_specpower(report):

    report.extend(section("2. SPECPOWER"))

    candidates = [
        ROOT / "power_ssj2008-results-20260906-021726.csv"
    ]

    found = False

    for path in candidates:

        if path.exists():

            found = True

            report.extend(csv_info(path))

    if not found:
        report.append("SPECpower CSV NOT FOUND")


# ============================================================
# 3. CMAPSS
# ============================================================

def inspect_cmapss(report):

    report.extend(section("3. NASA C-MAPSS"))

    folder = ROOT / "CMAPSSData"

    if not folder.exists():
        report.append("NOT FOUND")
        return

    for path in sorted(folder.iterdir()):

        if not path.is_file():
            continue

        report.extend(section(path.name))

        if path.suffix.lower() == ".txt":
            report.extend(text_info(path))
        else:
            report.append(f"NON-TEXT FILE: {path}")


# ============================================================
# 4. NAB
# ============================================================

def inspect_nab(report):

    report.extend(section("4. NAB ANOMALY BENCHMARK"))

    folder = ROOT / "NAB-master"

    if not folder.exists():
        report.append("NOT FOUND")
        return

    csv_files = sorted(folder.rglob("*.csv"))

    report.append(f"NAB CSV FILES: {len(csv_files)}")

    # Don't inspect every CSV in full.
    # Inspect representative files from important directories.

    selected = []

    for path in csv_files:

        text = str(path).lower()

        if "realAWSCloudwatch" in text:
            selected.append(path)

        elif "realKnownCause" in text:
            selected.append(path)

        if len(selected) >= 8:
            break

    for path in selected:

        report.extend(section(f"NAB FILE: {path.relative_to(ROOT)}"))

        report.extend(csv_info(path))


    # Labels
    labels = folder / "labels"

    if labels.exists():

        report.extend(section("NAB LABEL FILES"))

        for path in sorted(labels.rglob("*")):

            if path.is_file():

                report.append(
                    f"{path.relative_to(ROOT)} | "
                    f"{size_string(path.stat().st_size)}"
                )


# ============================================================
# 5. ELECTRICITY MAPS
# ============================================================

def inspect_electricity_maps(report):

    report.extend(section("5. ELECTRICITY MAPS"))

    folder = ROOT / "electricity_maps"

    if not folder.exists():
        report.append("NOT FOUND")
        return

    for path in sorted(folder.rglob("*")):

        if not path.is_file():
            continue

        report.extend(section(
            f"ELECTRICITY MAPS FILE: {path.relative_to(ROOT)}"
        ))

        if path.suffix.lower() == ".csv":

            report.extend(csv_info(path))

        elif path.suffix.lower() == ".py":

            lines = path.read_text(
                encoding="utf-8",
                errors="replace"
            ).splitlines()

            report.append("PYTHON SCRIPT")
            report.append("FIRST 40 LINES:")

            report.extend(lines[:40])

        else:

            report.append(
                f"TYPE: {path.suffix}"
            )


    # Top-level coverage CSV
    coverage = ROOT / "2026-09-06-electricity-maps-coverage-data.csv"

    if coverage.exists():

        report.extend(section("ELECTRICITY MAPS COVERAGE CSV"))

        report.extend(csv_info(coverage))


# ============================================================
# 6. ASHRAE ENERGY PREDICTION
# ============================================================

def inspect_ashrae_energy(report):

    report.extend(section("6. ASHRAE ENERGY PREDICTION"))

    folder = ROOT / "ashrae-energy-prediction"

    if not folder.exists():
        report.append("NOT FOUND")
        return

    files = sorted(folder.iterdir())

    for path in files:

        if not path.is_file():
            continue

        report.extend(section(path.name))

        if path.suffix.lower() == ".csv":

            report.extend(csv_info(path))

        elif path.suffix.lower() in {".txt", ".md"}:

            report.extend(text_info(path))

        else:

            report.append(
                f"FILE TYPE: {path.suffix}"
            )


# ============================================================
# 7. AQUEDUCT
# ============================================================

def inspect_aqueduct(report):

    report.extend(section("7. AQUEDUCT WATER-STRESS DATA"))

    folders = [
        ROOT / "aqueduct-4-0-country-rankings",
        ROOT / "aqueduct-4-0-water-risk-data",
    ]

    for folder in folders:

        if not folder.exists():
            continue

        report.extend(section(
            f"AQUEDUCT FOLDER: {folder.name}"
        ))

        files = list(folder.rglob("*"))

        for path in files:

            if not path.is_file():
                continue

            report.append(
                f"{path.relative_to(ROOT)} | "
                f"{size_string(path.stat().st_size)}"
            )

            if path.suffix.lower() in {
                ".csv",
                ".xlsx",
                ".xls"
            }:

                try:

                    if path.suffix.lower() == ".csv":

                        report.extend(
                            csv_info(path)
                        )

                    else:

                        report.extend(
                            excel_info(path)
                        )

                except Exception as e:

                    report.append(
                        f"ERROR: {type(e).__name__}: {e}"
                    )


# ============================================================
# 8. CLUSTER DATA
# ============================================================

def inspect_cluster_data(report):

    report.extend(section("8. CLUSTER / ALIBABA WORKLOAD DATA"))

    folders = [
        ROOT / "cluster-data-master",
        ROOT / "clusterdata-master",
    ]

    for folder in folders:

        if not folder.exists():
            continue

        report.extend(section(
            f"CLUSTER FOLDER: {folder.name}"
        ))

        files = list(folder.rglob("*"))

        report.append(
            f"TOTAL FILES: "
            f"{sum(p.is_file() for p in files)}"
        )

        # Focus on CSV / header / README files
        interesting = []

        for path in files:

            if not path.is_file():
                continue

            suffix = path.suffix.lower()

            if suffix in {
                ".csv",
                ".header",
                ".md",
                ".proto"
            }:

                interesting.append(path)

        for path in interesting[:30]:

            report.append(
                f"{path.relative_to(ROOT)} | "
                f"{size_string(path.stat().st_size)}"
            )

            if path.suffix.lower() == ".csv":

                report.extend(
                    csv_info(path)
                )

            elif path.suffix.lower() in {
                ".md",
                ".proto",
                ".header"
            }:

                report.extend(
                    text_info(path)
                )


# ============================================================
# RUN ALL DATASET INSPECTIONS
# ============================================================

def main():

    report = []

    report.extend([
        "TWINGRID DETAILED DATASET SCHEMA REPORT",
        "=" * 100,
        f"ROOT: {ROOT.resolve()}",
        "",
        "This report contains metadata, schemas and small samples only.",
        "It does NOT copy entire datasets.",
    ])

    inspect_open_meteo(report)
    inspect_specpower(report)
    inspect_cmapss(report)
    inspect_nab(report)
    inspect_electricity_maps(report)
    inspect_ashrae_energy(report)
    inspect_aqueduct(report)
    inspect_cluster_data(report)

    OUTPUT.write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    print()
    print("=" * 70)
    print("REPORT CREATED")
    print("=" * 70)
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()