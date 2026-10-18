"""Validate and install a USER-PROVIDED carbon-intensity time series (Task 8).

TwinGrid ships no carbon data and this module never creates any: it checks a file the operator supplies and, only if
every check passes, copies it to ``data/cleaned/carbon_intensity.csv`` with the provenance sidecar
``carbon_intensity.meta.json`` that ``src.carbon_provider`` reads. Only then does the loader report ``is_fallback=False``
(``is_real=True`` in the older payloads).

CSV schema (header required, UTF-8, one row per instant):
  timestamp_utc                  ISO-8601 WITH an explicit offset or ``Z``. A naive timestamp is refused (the loader would
                                 silently call it UTC). Strictly increasing within a zone, no duplicates.
  carbon_intensity_gco2_per_kwh  finite number, 0 <= v <= MAX_GCO2_PER_KWH. Unit is grams CO2-equivalent per kWh.
  zone                           non-empty string (e.g. a grid-zone code). Every row.

Provenance (a JSON object you supply; all required): ``semantic`` (``average`` | ``marginal``), ``unit``
(must be ``gCO2/kWh``), ``source`` (who produced it), ``license_ref`` (licence or terms), ``retrieved_at`` (ISO-8601 with
offset). Optional: ``source_version``, ``resolution_s`` (else the median spacing is used).

Checks: columns, offsets, order, duplicates, value range, resolution regularity (a gap larger than ``max_gap_factor`` x
the resolution is an error), and coverage of all 24 SITE-LOCAL hours (a missing hour would be filled by the flat 475
assumption and the loader would then mark the whole signal ``is_fallback=True``, so it is refused unless
``allow_partial_hours``).

Not checked, and not claimed: that the numbers are correct, that the licence permits your use, or that the semantic you
declare is true. Provenance is a record of what you stated plus the file's SHA-256.

CLI::

    python -m src.carbon_ingest validate --csv my.csv --meta my_meta.json
    python -m src.carbon_ingest install  --csv my.csv --meta my_meta.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .carbon_provider import CARBON_META_FILENAME, CLEANED_CARBON_PATH
from .timeutil import TimeContractError, parse_timestamp, site_timezone_name

REQUIRED_COLUMNS = ("timestamp_utc", "carbon_intensity_gco2_per_kwh", "zone")
REQUIRED_META = ("semantic", "unit", "source", "license_ref", "retrieved_at")
SEMANTICS = ("average", "marginal")
UNIT = "gCO2/kWh"
MAX_GCO2_PER_KWH = 2000.0  # above any real grid mix (coal ~1000); a larger value is almost surely a unit error
DEFAULT_MAX_GAP_FACTOR = 3.0
MAX_ERRORS_LISTED = 20


@dataclass
class IngestReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: int = 0
    zones: list[str] = field(default_factory=list)
    first_utc: str | None = None
    last_utc: str | None = None
    resolution_s: int | None = None
    missing_site_local_hours: list[int] = field(default_factory=list)
    csv_sha256: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_meta(meta: Any, errors: list[str]) -> dict[str, Any]:
    if not isinstance(meta, dict):
        errors.append("provenance metadata must be a JSON object")
        return {}
    for key in REQUIRED_META:
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            errors.append(f"metadata.{key} is required (non-empty string)")
    if isinstance(meta.get("semantic"), str) and meta["semantic"] not in SEMANTICS:
        errors.append(f"metadata.semantic must be one of {SEMANTICS} (average intensity is never labelled marginal)")
    if isinstance(meta.get("unit"), str) and meta["unit"].strip() != UNIT:
        errors.append(f"metadata.unit must be exactly {UNIT!r}, got {meta['unit']!r}; convert before ingesting")
    if isinstance(meta.get("retrieved_at"), str) and meta["retrieved_at"].strip():
        try:
            parse_timestamp(meta["retrieved_at"])  # naive -> TimeContractError
        except TimeContractError:
            errors.append("metadata.retrieved_at must be ISO-8601 with an explicit offset or Z")
    res = meta.get("resolution_s")
    if res is not None and (isinstance(res, bool) or not isinstance(res, (int, float)) or res <= 0):
        errors.append("metadata.resolution_s must be a positive number when given")
    return meta


def validate_carbon_csv(
    csv_path: Path,
    meta: Any,
    *,
    allow_partial_hours: bool = False,
    max_gap_factor: float = DEFAULT_MAX_GAP_FACTOR,
) -> IngestReport:
    """Check ``csv_path`` against the schema above. Pure: reads the file, writes nothing."""
    errors: list[str] = []
    warnings: list[str] = []
    meta = _check_meta(meta, errors)
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        return IngestReport(False, [*errors, f"{csv_path} does not exist"])
    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a validation error, reported not raised
        return IngestReport(False, [*errors, f"cannot read CSV: {type(exc).__name__}"], csv_sha256=_sha256(csv_path))
    report = IngestReport(False, errors, warnings, rows=len(df), csv_sha256=_sha256(csv_path), meta=meta)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"missing column(s): {', '.join(missing)}")
        return report
    if df.empty:
        errors.append("the file has no data rows")
        return report

    stamps: list[datetime | None] = []
    bad = 0
    for i, (raw_ts, raw_v, raw_z) in enumerate(
        zip(df["timestamp_utc"], df["carbon_intensity_gco2_per_kwh"], df["zone"]), start=2
    ):
        row_err = None
        ts = None
        text = raw_ts.strip()
        if not text:
            row_err = "empty timestamp"
        else:
            try:
                ts = parse_timestamp(text)  # no source_tz: a naive stamp is refused
            except TimeContractError:
                row_err = "timestamp is unparseable or has no explicit offset/Z"
        if row_err is None:
            try:
                v = float(raw_v)
                if not math.isfinite(v) or v < 0 or v > MAX_GCO2_PER_KWH:
                    row_err = f"value {raw_v!r} outside 0..{MAX_GCO2_PER_KWH:g} gCO2/kWh (unit error?)"
            except ValueError:
                row_err = f"value {raw_v!r} is not a number"
        if row_err is None and not raw_z.strip():
            row_err = "empty zone"
        stamps.append(ts)
        if row_err:
            bad += 1
            if bad <= MAX_ERRORS_LISTED:
                errors.append(f"line {i}: {row_err}")
    if bad > MAX_ERRORS_LISTED:
        errors.append(f"... and {bad - MAX_ERRORS_LISTED} more bad rows")
    if bad:
        return report

    df = df.assign(_ts=stamps)
    report.zones = sorted(df["zone"].str.strip().unique())
    gaps_s: list[float] = []
    for zone, grp in df.groupby(df["zone"].str.strip(), sort=True):
        times = [t.timestamp() for t in grp["_ts"]]
        for a, b in zip(times, times[1:]):
            if b == a:
                errors.append(
                    f"zone {zone}: duplicate timestamp {datetime.fromtimestamp(a, tz=ZoneInfo('UTC')).isoformat()}"
                )
            elif b < a:
                errors.append(f"zone {zone}: timestamps are not increasing (file order matters)")
            else:
                gaps_s.append(b - a)
        if len(errors) > MAX_ERRORS_LISTED:
            break
    if errors:
        return report

    all_ts = sorted(t for t in stamps if t is not None)
    report.first_utc, report.last_utc = all_ts[0].isoformat(), all_ts[-1].isoformat()
    declared = meta.get("resolution_s")
    if gaps_s:
        median = sorted(gaps_s)[len(gaps_s) // 2]
        report.resolution_s = int(declared) if declared else int(median)
        limit = report.resolution_s * max_gap_factor
        big = [g for g in gaps_s if g > limit]
        if big:
            errors.append(
                f"{len(big)} gap(s) longer than {max_gap_factor:g} x the {report.resolution_s}s resolution "
                f"(largest {int(max(big))}s): the series has holes"
            )
    elif declared:
        report.resolution_s = int(declared)
    else:
        warnings.append("a single row per zone: resolution cannot be established")

    site = ZoneInfo(site_timezone_name())
    covered = {t.astimezone(site).hour for t in all_ts}
    report.missing_site_local_hours = [h for h in range(24) if h not in covered]
    if report.missing_site_local_hours:
        msg = (
            f"no data for site-local hours {report.missing_site_local_hours} ({site_timezone_name()}); the loader would "
            "fill them with the flat 475 assumption and mark the whole signal is_fallback=True"
        )
        (warnings if allow_partial_hours else errors).append(msg)
    if len(report.zones) > 1:
        warnings.append(f"{len(report.zones)} zones in one file; the loader averages them unless a zone is requested")

    report.ok = not errors
    return report


def install_carbon_csv(
    csv_path: Path,
    meta: dict[str, Any],
    *,
    target: Path | None = None,
    allow_partial_hours: bool = False,
    overwrite: bool = False,
    max_gap_factor: float = DEFAULT_MAX_GAP_FACTOR,
) -> IngestReport:
    """Validate, then copy the CSV and write the sidecar. Raises ``ValueError`` (no files touched) if invalid."""
    report = validate_carbon_csv(csv_path, meta, allow_partial_hours=allow_partial_hours, max_gap_factor=max_gap_factor)
    if not report.ok:
        raise ValueError("carbon file refused:\n  " + "\n  ".join(report.errors))
    target = Path(target) if target is not None else CLEANED_CARBON_PATH
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} exists; pass overwrite=True (--overwrite) to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    sidecar = {
        "semantic": meta["semantic"],
        "unit": UNIT,
        "source_version": meta.get("source_version") or meta["source"],
        "source": meta["source"],
        "license_ref": meta["license_ref"],
        "retrieved_at": meta["retrieved_at"],
        "resolution_s": report.resolution_s,
        "csv_sha256": report.csv_sha256,
        "rows": report.rows,
        "first_utc": report.first_utc,
        "last_utc": report.last_utc,
        "validated_by": "src.carbon_ingest",
    }
    target.write_bytes(Path(csv_path).read_bytes())
    target.with_name(CARBON_META_FILENAME).write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    from .carbon_provider import clear_carbon_cache

    clear_carbon_cache()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.carbon_ingest", description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=("validate", "install"))
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--meta", required=True, type=Path, help="JSON file with the provenance fields")
    ap.add_argument("--allow-partial-hours", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--max-gap-factor", type=float, default=DEFAULT_MAX_GAP_FACTOR)
    args = ap.parse_args(argv)
    try:
        meta = json.loads(args.meta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read metadata: {type(exc).__name__}", file=sys.stderr)
        return 2
    try:
        if args.action == "validate":
            report = validate_carbon_csv(
                args.csv, meta, allow_partial_hours=args.allow_partial_hours, max_gap_factor=args.max_gap_factor
            )
            print(json.dumps(report.as_dict(), indent=2, default=str))
            return 0 if report.ok else 1
        report = install_carbon_csv(
            args.csv,
            meta,
            allow_partial_hours=args.allow_partial_hours,
            overwrite=args.overwrite,
            max_gap_factor=args.max_gap_factor,
        )
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"installed {report.rows} rows to {CLEANED_CARBON_PATH}; the loader will now report is_fallback=False"
        f"{' (partial hours: still a fallback)' if report.missing_site_local_hours else ''}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
