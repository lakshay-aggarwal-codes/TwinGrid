#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_DATA_DIR = REPO_ROOT / "realData"
DATA_EXTERNAL_DIR = REPO_ROOT / "data" / "external"

HASH_SIZE_LIMIT_BYTES = 50 * 1024 * 1024

KNOWN_SOURCES = {
    "electricity": {
        "display_name": "Electricity Maps",
        "source_url": "https://api-portal.electricitymaps.com/",
        "license": "Electricity Maps free-tier API terms",
        "citation": "Electricity Maps — real-time and historical grid carbon intensity",
        "used_for": "Feeds the gamma (carbon) term in the PPO reward function (Phase 7)",
    },
    "aqueduct": {
        "display_name": "WRI Aqueduct Water Risk Atlas (v4.0)",
        "source_url": "https://www.wri.org/applications/aqueduct/water-risk-atlas/",
        "license": "Open data, WRI Aqueduct terms of use",
        "citation": "World Resources Institute, Aqueduct 4.0 Water Risk Atlas, 2023",
        "used_for": "Water stress index driving drought-aware cooling-mode arbitration (patent Claim 8, Phase 4)",
    },
    "ashrae_tc0909": {
        "display_name": "ASHRAE TC 9.9 Power Trends White Paper",
        "source_url": "https://www.ashrae.org/",
        "license": "ASHRAE published white paper",
        "citation": "ASHRAE TC 9.9, Power Trends White Paper, revised 22 June 2016",
        "used_for": "Reference values for IT-power trend validation",
    },
    "power_ssj2008": {
        "display_name": "SPECpower_ssj2008 Results Database",
        "source_url": "https://www.spec.org/power_ssj2008/results/",
        "license": "SPEC published benchmark results, free for research/education use",
        "citation": "Standard Performance Evaluation Corporation, SPECpower_ssj2008 results",
        "used_for": "Calibrates the real (non-linear) IT-power-vs-utilisation curve (Phase 4)",
    },
    "rp-1043": {
        "display_name": "ASHRAE RP-1043 Chiller Fault Detection Dataset",
        "source_url": "ASHRAE RP-1043 (public research-data mirror)",
        "license": "Research dataset, public mirror",
        "citation": "Comstock & Braun, ASHRAE RP-1043, Chiller Fault Detection Data",
        "used_for": "Calibrates per-mode cooling COP and validates anomaly-detector fault signatures (Phase 4, 6)",
    },
    "ashrae-energy-prediction": {
        "display_name": "ASHRAE Great Energy Predictor III (Kaggle)",
        "source_url": "https://www.kaggle.com/c/ashrae-energy-prediction",
        "license": "Kaggle competition data — competition rules apply",
        "citation": "ASHRAE Great Energy Predictor III, Kaggle, 2019",
        "used_for": "Building-scale power-vs-weather validation only, not a direct column source",
    },
    "cluster": {
        "display_name": "Alibaba Cluster Trace",
        "source_url": "https://github.com/alibaba/clusterdata",
        "license": "Repository license — see clusterdata-master/LICENSE",
        "citation": "Alibaba Cluster Trace Program, cluster-trace-gpu-v2020",
        "used_for": "Real server_utilisation driver, replacing the synthetic diurnal curve (Phase 4)",
    },
    "cmapss": {
        "display_name": "NASA C-MAPSS Turbofan Degradation Dataset",
        "source_url": "https://data.nasa.gov (NASA Prognostics Center of Excellence)",
        "license": "NASA public data",
        "citation": "Saxena & Goebel, NASA Ames Prognostics Data Repository, C-MAPSS",
        "used_for": (
            "PROXY dataset for the predictive-maintenance RUL model (Phase 5). "
            "NOT real data-center hardware failure data -- used only because it is "
            "a structurally analogous degradation-to-failure sensor trajectory dataset. "
            "This caveat must be repeated everywhere this dataset is referenced in code, "
            "docs, or the UI."
        ),
    },
    "nab": {
        "display_name": "Numenta Anomaly Benchmark (NAB)",
        "source_url": "https://github.com/numenta/NAB",
        "license": "AGPL-3.0 (NAB repository license)",
        "citation": "Lavin & Ahmad, Numenta Anomaly Benchmark, 2015",
        "used_for": (
            "Ground-truth labeled anomalies for OFFLINE VALIDATION of the anomaly "
            "detector only (Phase 6) -- not used as training data, since it comes "
            "from a different physical system."
        ),
    },
    "open_meteo": {
        "display_name": "Open-Meteo Historical Weather Archive",
        "source_url": "https://open-meteo.com/en/docs/historical-weather-api",
        "license": "Open-Meteo — free for non-commercial use (CC BY 4.0 attribution)",
        "citation": "Open-Meteo.com Weather API",
        "used_for": "Real outside_temp_C / humidity_pct driver, replacing synthetic curves (Phase 4)",
    },
}


def match_known_source(name: str) -> Optional[dict]:
    lowered = name.lower()
    for key, meta in KNOWN_SOURCES.items():
        if key in lowered:
            return meta
    return None


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_entry(entry: Path) -> dict:
    total_size = 0
    extensions: set[str] = set()
    files = []

    candidates = [entry] if entry.is_file() else [p for p in entry.rglob("*") if p.is_file()]

    for f in candidates:
        try:
            stat = f.stat()
        except OSError:
            continue
        size = stat.st_size
        total_size += size
        extensions.add(f.suffix.lower())
        rel = f.relative_to(entry.parent)
        record = {
            "path": str(rel).replace(os.sep, "/"),
            "size_bytes": size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
        if size <= HASH_SIZE_LIMIT_BYTES:
            record["sha256"] = sha256_of_file(f)
        else:
            record["sha256"] = None
            record["note"] = (
                f"file exceeds {HASH_SIZE_LIMIT_BYTES} byte hashing limit; "
                "size + mtime recorded instead of a full checksum"
            )
        files.append(record)

    return {
        "file_count": len(files),
        "total_size_bytes": total_size,
        "extensions": sorted(extensions),
        "files": files,
    }


def build_provenance(entry: Path) -> dict:
    known = match_known_source(entry.name)
    return {
        "source_slug": entry.name,
        "original_path": f"realData/{entry.name}",
        "scanned_at_utc": datetime.now(timezone.utc).isoformat(),
        "metadata": known
        or {
            "display_name": entry.name,
            "source_url": "TODO -- fill in manually",
            "license": "TODO -- fill in manually",
            "citation": "TODO -- fill in manually",
            "used_for": "TODO -- fill in manually",
        },
        "metadata_is_placeholder": known is None,
        "scan": scan_entry(entry),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate provenance manifests for realData/ sources.")
    parser.add_argument("--source", help="Only scan the realData/ entry with this exact name.")
    args = parser.parse_args()

    if not REAL_DATA_DIR.exists():
        print(f"ERROR: {REAL_DATA_DIR} does not exist. Run this from the repository root.", file=sys.stderr)
        return 1

    DATA_EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)

    entries = sorted(p for p in REAL_DATA_DIR.iterdir() if not p.name.startswith("."))
    if args.source:
        entries = [e for e in entries if e.name == args.source]
        if not entries:
            print(f"ERROR: no entry named '{args.source}' found in {REAL_DATA_DIR}", file=sys.stderr)
            return 1

    placeholders = []
    for entry in entries:
        print(f"Scanning {entry.name} ...")
        manifest = build_provenance(entry)
        out_dir = DATA_EXTERNAL_DIR / entry.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "provenance.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        scan = manifest["scan"]
        print(f"  -> {out_path}  ({scan['file_count']} files, {scan['total_size_bytes'] / 1e6:.1f} MB)")
        if manifest["metadata_is_placeholder"]:
            placeholders.append(entry.name)

    if placeholders:
        print(
            "\nWARNING: no known metadata for these sources -- edit their "
            "provenance.json by hand and fill in source_url / license / "
            "citation / used_for:"
        )
        for name in placeholders:
            print(f"  - {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())