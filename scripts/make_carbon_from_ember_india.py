"""Turn Ember's monthly India state data into a staging file for ``python -m src.carbon_ingest``.

Input: Ember "India Electricity Data", monthly, long format (``india_monthly_full_release_long_format.csv``). The one
series used is ``Category = Power sector emissions, Subcategory = CO2 intensity, Variable = CO2 intensity, Unit = gCO2/kWh``
for one state.

What this script does NOT do: it does not install anything and does not touch ``data/cleaned``. It writes two staging
files (a CSV and a provenance JSON) and prints the install command. ``src.carbon_ingest`` then validates and installs.

What the numbers are, and are not (they are written into the provenance and the docs):
  * One value per calendar month (UTC), generation-based, CO2 only, for the state's own power sector. Imports are not
    counted. It is an average intensity, never a marginal one.
  * ``src.carbon_provider`` needs hourly rows covering all 24 site-local hours, so each monthly value is REPEATED for
    every hour of its month. That gives the right level and NO time-of-day shape. The provider labels such a curve as
    not time-varying (``time_varying_signal`` false), and the carbon scheduler reports "no variation".
  * Months with no value are left out, never turned into zeros.

Usage::

    python scripts/make_carbon_from_ember_india.py --state Maharashtra --year 2025 --retrieved-at 2026-10-25T00:00:00+05:30
    python -m src.carbon_ingest install --csv data/raw/carbon_staging/carbon_intensity_staging.csv \
        --meta data/raw/carbon_staging/carbon_intensity_staging.meta.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW = REPO_ROOT / "data" / "raw" / "india_monthly_full_release_long_format.csv"
DEFAULT_OUT = REPO_ROOT / "data" / "raw" / "carbon_staging"

SERIES = {
    "Category": "Power sector emissions",
    "Subcategory": "CO2 intensity",
    "Variable": "CO2 intensity",
    "Unit": "gCO2/kWh",
}
DEFAULT_LICENSE_REF = "CC-BY-4.0, as stated on ember-energy.org (India Electricity Data page); attribution: Ember"
STAGING_CSV = "carbon_intensity_staging.csv"
STAGING_META = "carbon_intensity_staging.meta.json"
COLUMNS = ("timestamp_utc", "carbon_intensity_gco2_per_kwh", "zone")


class EmberError(ValueError):
    """The input does not hold what this script needs. Nothing is written."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def monthly_values(raw: pd.DataFrame, state: str, year: int) -> dict[int, float]:
    """``{month: gCO2/kWh}`` for ``state`` in ``year``. Empty cells are skipped. Raises ``EmberError`` if nothing usable."""
    needed = {"State", "Date", "Value", *SERIES}
    missing = needed - set(raw.columns)
    if missing:
        raise EmberError(f"the file lacks columns {sorted(missing)}; is it Ember's monthly long-format release?")
    sel = raw
    for col, want in SERIES.items():
        sel = sel[sel[col] == want]
    if sel.empty:
        raise EmberError(f"no rows for the series {SERIES}")
    sel = sel[sel["State"] == state]
    if sel.empty:
        raise EmberError(f"state {state!r} not found for that series; known: {sorted(set(raw['State']))}")
    out: dict[int, float] = {}
    for date, value in zip(sel["Date"], sel["Value"]):
        try:
            when = datetime.strptime(str(date)[:10], "%Y-%m-%d")
            number = float(value)
        except (TypeError, ValueError):
            continue  # empty or unreadable cell: leave the month out
        if when.year != year or number != number or number in (float("inf"), float("-inf")):
            continue
        if when.day != 1:
            raise EmberError(f"expected month-start dates, got {date!r}")
        if when.month in out:
            raise EmberError(f"two values for {state} {when:%Y-%m}; refusing to pick one")
        out[when.month] = number
    if not out:
        raise EmberError(f"no usable monthly values for {state} in {year}")
    return out


def hourly_rows(values: dict[int, float], year: int, zone: str) -> list[dict[str, Any]]:
    """Repeat each monthly value for every UTC hour of that month, in time order."""
    rows: list[dict[str, Any]] = []
    for month in sorted(values):
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
        t = start
        while t < end:
            rows.append(
                {
                    "timestamp_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "carbon_intensity_gco2_per_kwh": values[month],
                    "zone": zone,
                }
            )
            t += timedelta(hours=1)
    return rows


def provenance(
    *, state: str, year: int, months: list[int], raw_sha256: str, retrieved_at: str, license_ref: str
) -> dict[str, Any]:
    span = f"{year}-{months[0]:02d} to {year}-{months[-1]:02d}"
    return {
        "semantic": "average",
        "unit": "gCO2/kWh",
        "source": (
            f"Ember, India Electricity Data (monthly, state level), series 'Power sector emissions / CO2 intensity' "
            f"for {state}: generation-based, CO2 only, imports not counted. One value per month, repeated for every "
            f"hour of that month, so it has no time-of-day shape"
        ),
        "source_version": (
            f"Ember India monthly release, {state}, {span} ({len(months)} months); monthly values repeated hourly; "
            f"raw file sha256 {raw_sha256[:16]}"
        ),
        "license_ref": license_ref,
        "retrieved_at": retrieved_at,
        "resolution_s": 3600,
    }


def build(
    raw_csv: Path, out_dir: Path, *, state: str, year: int, retrieved_at: str, license_ref: str = DEFAULT_LICENSE_REF
) -> dict[str, Any]:
    raw_csv, out_dir = Path(raw_csv), Path(out_dir)
    if not raw_csv.is_file():
        raise EmberError(f"{raw_csv} does not exist")
    raw = pd.read_csv(raw_csv, dtype=str, keep_default_na=False)
    values = monthly_values(raw, state, year)
    zone = f"India/{state} (Ember state data)"
    rows = hourly_rows(values, year, zone)
    months = sorted(values)
    meta = provenance(
        state=state,
        year=year,
        months=months,
        raw_sha256=_sha256(raw_csv),
        retrieved_at=retrieved_at,
        license_ref=license_ref,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=list(COLUMNS)).to_csv(out_dir / STAGING_CSV, index=False)
    (out_dir / STAGING_META).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "rows": len(rows),
        "months": months,
        "values": values,
        "csv": out_dir / STAGING_CSV,
        "meta": out_dir / STAGING_META,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--state", default="Maharashtra")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--retrieved-at", required=True, help="when you downloaded the raw file, ISO-8601 WITH an offset")
    ap.add_argument("--license-ref", default=DEFAULT_LICENSE_REF)
    args = ap.parse_args(argv)
    try:
        result = build(
            args.raw,
            args.out_dir,
            state=args.state,
            year=args.year,
            retrieved_at=args.retrieved_at,
            license_ref=args.license_ref,
        )
    except EmberError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {result['rows']} hourly rows for {len(result['months'])} months: {result['csv']}")
    for month in result["months"]:
        print(f"  {args.year}-{month:02d}: {result['values'][month]:.1f} gCO2/kWh")
    print("Next, validate then install (nothing has been installed yet):")
    print(f"  python -m src.carbon_ingest validate --csv {result['csv']} --meta {result['meta']}")
    print(f"  python -m src.carbon_ingest install  --csv {result['csv']} --meta {result['meta']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
