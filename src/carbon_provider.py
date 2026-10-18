"""
Carbon-intensity signal for the PPO reward's gamma (carbon) term (T23, roadmap §13.6).

``load_carbon_signal()`` returns a :class:`CarbonSignal` that says WHAT the numbers are:

* ``is_fallback`` -- True when any value is an assumption rather than loaded data. The flat 475 gCO2/kWh
  constant is such an assumption (``semantic="constant_assumption"``); it is never real, measured or
  site-specific data.
* ``semantic`` in {average, marginal, constant_assumption, unknown}. A cleaned carbon file is only labelled
  ``average`` or ``marginal`` if its sidecar ``carbon_intensity.meta.json`` says so; otherwise ``unknown``.
  Average intensity is never called marginal, and nothing is guessed.
* ``aggregation`` -- ``diurnal_mean`` when the 24-point hour-of-day mean is what consumers use (it is a mean
  by hour of day, NOT a time series and not time-varying data for any date), ``constant`` for the fallback.

Hour mapping: source timestamps are UTC; the hour-of-day curve is indexed by SITE-LOCAL hour
(``src.timeutil.to_site_local``, ``SITE_TIMEZONE``, default Asia/Kolkata), so UTC 18:30 is local hour 0 in IST.

"Carbon-aware optimisation demonstrated" needs every condition of §13.6 (real time-varying signal with
``is_fallback=False`` covering the evaluation months, license, seeded ablation vs a shuffled control, no
degradation of energy/thermal metrics). Until then the honest statement is: "carbon term present; signal is an
assumption" -- see :func:`format_carbon_reduction`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .timeutil import TimeContractError, parse_timestamp, site_timezone_name

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLEANED_CARBON_PATH = REPO_ROOT / "data" / "cleaned" / "carbon_intensity.csv"
CARBON_META_FILENAME = "carbon_intensity.meta.json"

# World-average grid carbon intensity (gCO2eq/kWh), commonly cited (IEA/Ember).
# Used ONLY as an explicit, documented fallback constant -- never presented
# as real or site-specific data.
FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH = 475.0

SEMANTICS = ("average", "marginal", "constant_assumption", "unknown")
AGG_DIURNAL_MEAN = "diurnal_mean"
AGG_CONSTANT = "constant"


@dataclass(frozen=True)
class CarbonSignal:
    """A labelled carbon-intensity signal (gCO2eq/kWh). Field meanings follow roadmap §13.6.

    ``values``/``timestamps_utc`` are the SOURCE series (aware-UTC instants; empty for the constant fallback,
    where ``values`` holds the single assumed constant). ``curve_by_site_local_hour`` is what the simulator uses.
    """

    values: tuple[float, ...]
    timestamps_utc: tuple[datetime, ...]
    zone: Optional[str]
    resolution_s: Optional[int]
    semantic: str
    aggregation: str
    interpolation: str
    missing_policy: str
    source_version: Optional[str]
    retrieved_at: Optional[datetime]
    license_ref: Optional[str]
    is_fallback: bool
    site_timezone: str = "UTC"
    missing_hours: tuple[int, ...] = ()  # site-local hours filled by the assumption (=> is_fallback)

    def __post_init__(self) -> None:
        if self.semantic not in SEMANTICS:
            raise ValueError(f"semantic must be one of {SEMANTICS}, got {self.semantic!r}")
        if len(self.values) != len(self.timestamps_utc) and self.timestamps_utc:
            raise ValueError("values and timestamps_utc must have the same length")
        if self.is_fallback is False and self.semantic == "constant_assumption":
            raise ValueError("a constant assumption is always a fallback")

    @property
    def curve_by_site_local_hour(self) -> np.ndarray:
        """Length-24 array indexed by SITE-LOCAL hour of day (0-23)."""
        return _diurnal_curve(self)[0]

    def basis(self) -> dict[str, Any]:
        """The label that travels with every payload / result / report (JSON-safe)."""
        return carbon_basis(self)


def _diurnal_curve(sig: CarbonSignal) -> tuple[np.ndarray, tuple[int, ...]]:
    if not sig.timestamps_utc:  # constant assumption
        return np.full(24, float(sig.values[0]) if sig.values else FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH), ()
    sums = np.zeros(24)
    counts = np.zeros(24)
    zone = ZoneInfo(sig.site_timezone)  # same conversion as timeutil.to_site_local, for the zone recorded on the signal
    for ts, val in zip(sig.timestamps_utc, sig.values):
        h = ts.astimezone(zone).hour
        sums[h] += val
        counts[h] += 1
    curve = np.full(24, FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH)
    missing = []
    for h in range(24):
        if counts[h]:
            curve[h] = sums[h] / counts[h]
        else:
            missing.append(h)
    return curve, tuple(missing)


def fallback_signal(zone: Optional[str] = None) -> CarbonSignal:
    """The flat assumption: not data, not time-varying, not site-specific."""
    return CarbonSignal(
        values=(FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH,),
        timestamps_utc=(),
        zone=zone,
        resolution_s=None,
        semantic="constant_assumption",
        aggregation=AGG_CONSTANT,
        interpolation="none",
        missing_policy="not_applicable",
        source_version="world-average assumption (IEA/Ember), not retrieved",
        retrieved_at=None,
        license_ref=None,
        is_fallback=True,
        site_timezone=site_timezone_name(),
    )


def signal_for_curve(curve: Any) -> CarbonSignal:
    """Label a CALLER-SUPPLIED 24-point curve whose provenance is not known here.

    A flat curve at the fallback value is the assumption itself; anything else is ``semantic="unknown"`` and
    ``is_fallback=True`` (provenance not established, so it cannot support a carbon claim).
    """
    arr = np.asarray(curve, dtype=float)
    if arr.shape == (24,) and bool(np.all(arr == FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH)):
        return fallback_signal()
    return CarbonSignal(
        values=tuple(float(x) for x in arr.ravel()),
        timestamps_utc=(),
        zone=None,
        resolution_s=None,
        semantic="unknown",
        aggregation=AGG_DIURNAL_MEAN,
        interpolation="none",
        missing_policy="not_applicable",
        source_version=None,
        retrieved_at=None,
        license_ref=None,
        is_fallback=True,
        site_timezone=site_timezone_name(),
    )


def carbon_basis(sig: CarbonSignal) -> dict[str, Any]:
    """JSON-safe label for payloads, optimizer results and reports."""
    return {
        "semantic": sig.semantic,
        "is_fallback": sig.is_fallback,
        "aggregation": sig.aggregation,
        "zone": sig.zone,
        "source_version": sig.source_version,
        "license_ref": sig.license_ref,
        "retrieved_at": sig.retrieved_at.isoformat() if sig.retrieved_at else None,
        "site_timezone": sig.site_timezone,
        "time_varying_signal": bool(sig.timestamps_utc) and not sig.is_fallback,
        "statement": carbon_statement(sig),
    }


def _a(word: str) -> str:
    return ("an " if word[:1] in "aeiou" else "a ") + word


def carbon_statement(sig: CarbonSignal) -> str:
    """The only sentence a label may use about this signal."""
    if sig.is_fallback:
        what = (
            "a flat assumed intensity"
            if sig.semantic == "constant_assumption"
            else f"a curve of unestablished provenance (semantic={sig.semantic})"
        )
        return f"Carbon term present; the signal is an assumption ({what}), not measured grid data."
    if sig.aggregation == AGG_DIURNAL_MEAN:
        return (
            f"Carbon term uses a diurnal (hour-of-day) mean of {_a(sig.semantic)}-intensity series; "
            "it is not time-varying data for any specific date."
        )
    return f"Carbon term uses {_a(sig.semantic)}-intensity series."


def format_carbon_reduction(sig: CarbonSignal, reduction_pct: float) -> str:
    """Report text for a carbon change. REFUSES to print "carbon reduction" unless the signal supports it.

    §13.6: a carbon-optimisation claim needs more than a loaded file (license, seeded ablation, tolerance); this
    function enforces the first necessary condition (``is_fallback=False``) and never emits a claim of
    "carbon-aware optimisation demonstrated". With a fallback or unknown signal it returns the assumption
    statement instead of a number.
    """
    if sig.is_fallback or sig.semantic in ("constant_assumption", "unknown"):
        return carbon_statement(sig) + " No carbon reduction is claimed."
    return (
        f"Modelled change in the carbon term: {reduction_pct:+.1f}% under {_a(sig.semantic)}-intensity "
        f"{sig.aggregation.replace('_', ' ')} signal (modelled, not measured; not evidence of carbon-aware "
        "optimisation without the §13.6 ablation)."
    )


def _read_meta(path: Path) -> dict[str, Any]:
    meta_path = path.with_name(CARBON_META_FILENAME)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        logger.warning("Unreadable %s -- treating carbon semantic as unknown", meta_path)
        return {}


def _load_carbon_signal_uncached(
    zone: str | None = None, *, path: Path | None = None, _warn_missing: bool = True
) -> CarbonSignal:
    """Load the cleaned carbon file as a :class:`CarbonSignal`, or the labelled flat fallback if it is absent.

    The file's semantic/license/version come ONLY from the sidecar ``carbon_intensity.meta.json``
    (keys: semantic, source_version, retrieved_at, license_ref, resolution_s). Without it: ``semantic="unknown"``.
    """
    src = Path(path) if path is not None else CLEANED_CARBON_PATH
    if not src.exists():
        if _warn_missing:
            logger.warning(
                "%s not found -- using the flat assumed intensity of %.0f gCO2/kWh (is_fallback=True).",
                src,
                FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH,
            )
        return fallback_signal(zone)

    df = pd.read_csv(src)
    if zone is not None:
        sub = df[df["zone"] == zone]
        if sub.empty:
            logger.warning(
                "Zone '%s' not found (available: %s). Using all zones instead.", zone, sorted(df["zone"].unique())
            )
        else:
            df = sub
    zones = sorted(df["zone"].dropna().unique()) if "zone" in df.columns else []
    zone_label = zones[0] if len(zones) == 1 else ("multiple:" + ",".join(zones) if zones else zone)

    stamps: list[datetime] = []
    vals: list[float] = []
    dropped = 0
    for raw_ts, raw_v in zip(df["timestamp_utc"], df["carbon_intensity_gco2_per_kwh"]):
        try:
            ts = parse_timestamp(str(raw_ts), "UTC")  # the column is UTC by contract; offsets in the text win
            v = float(raw_v)
        except (TimeContractError, TypeError, ValueError):
            dropped += 1
            continue
        if not np.isfinite(v):
            dropped += 1
            continue
        stamps.append(ts)
        vals.append(v)
    if dropped:
        logger.warning("Dropped %d unparseable/non-finite carbon rows", dropped)
    if not vals:
        logger.warning("%s has no usable rows -- using the flat assumed intensity", src)
        return fallback_signal(zone)

    meta = _read_meta(src)
    semantic = meta.get("semantic") if meta.get("semantic") in ("average", "marginal") else "unknown"
    try:
        retrieved = parse_timestamp(meta["retrieved_at"]) if meta.get("retrieved_at") else None
    except TimeContractError:
        retrieved = None
    res = meta.get("resolution_s")
    if res is None and len(stamps) > 2:
        diffs = np.diff(np.array(sorted({s.timestamp() for s in stamps})))
        res = int(np.median(diffs)) if len(diffs) else None

    order = np.argsort([s.timestamp() for s in stamps])
    sig = CarbonSignal(
        values=tuple(vals[i] for i in order),
        timestamps_utc=tuple(stamps[i] for i in order),
        zone=zone_label,
        resolution_s=int(res) if res else None,
        semantic=semantic,
        aggregation=AGG_DIURNAL_MEAN,
        interpolation="none",
        missing_policy="flat_assumption_for_hours_without_data",
        source_version=meta.get("source_version"),
        retrieved_at=retrieved,
        license_ref=meta.get("license_ref"),
        is_fallback=False,
        site_timezone=site_timezone_name(),
    )
    _, missing = _diurnal_curve(sig)
    if missing:
        logger.warning(
            "No data for site-local hours %s -- flat assumption used there; is_fallback=True.", list(missing)
        )
        sig = CarbonSignal(**{**sig.__dict__, "missing_hours": missing, "is_fallback": True})
    if semantic == "unknown":
        logger.warning("%s has no documented semantic (average vs marginal) -- recorded as 'unknown'.", src)
    return sig


# Task 8: the missing-file fallback is memoised too. It used to be exempt ("never cached"), so EVERY DigitalTwin() /
# DataCentreEnv() construction -- one per scenario or episode in a tune/evaluation run -- re-ran the lookup and logged
# the same "not found" warning again (hundreds of times per run). The cache key for an absent file is
# ("missing", path, zone, site tz): it costs one stat per call, a file that appears later gets a content key and is read
# (so nothing is stale), and the warning is emitted once per (path, zone) per process (``clear_carbon_cache`` resets it).
# Task 24: every DigitalTwin() (one per /api/state call) reads and parses the cleaned carbon file. The result is a
# pure function of the file bytes, the sidecar bytes, the zone and the site time zone, so it is memoised under
# exactly that key (content hashes, not mtimes: a same-size rewrite within one clock tick is still seen). A missing
# file is never cached (the labelled fallback and its warning behave as before). CarbonSignal is frozen; the curve
# is handed out as a fresh copy, so no caller can corrupt the cached one.
_LOAD_CACHE_MAX = 8
_load_cache: "OrderedDict[tuple, tuple[CarbonSignal, np.ndarray]]" = OrderedDict()
_load_cache_lock = threading.Lock()
_warned_missing: set[tuple[str, str | None]] = set()


def _content_key(src: Path, zone: str | None) -> tuple | None:
    try:
        data = src.read_bytes()
        meta_path = src.with_name(CARBON_META_FILENAME)
        meta = meta_path.read_bytes() if meta_path.exists() else b""
    except OSError:
        return None
    return (str(src), zone, site_timezone_name(), hashlib.sha256(data).digest(), hashlib.sha256(meta).digest())


def _signal_and_curve(zone: str | None, path: Path | None) -> tuple[CarbonSignal, np.ndarray]:
    src = Path(path) if path is not None else CLEANED_CARBON_PATH
    key = _content_key(src, zone) if src.exists() else None
    if key is None and not src.exists():
        key = ("missing", str(src), zone, site_timezone_name())
    if key is not None:
        with _load_cache_lock:
            hit = _load_cache.get(key)
            if hit is not None:
                _load_cache.move_to_end(key)
                return hit
    sig = _load_carbon_signal_uncached(zone, path=path, _warn_missing=_claim_missing_warning(src, zone))
    curve = sig.curve_by_site_local_hour
    if key is not None:
        with _load_cache_lock:
            _load_cache[key] = (sig, curve)
            while len(_load_cache) > _LOAD_CACHE_MAX:
                _load_cache.popitem(last=False)
    return sig, curve


def _claim_missing_warning(src: Path, zone: str | None) -> bool:
    """True the first time this (path, zone) is found missing in this process; the caller then logs the warning."""
    with _load_cache_lock:
        mark = (str(src), zone)
        if mark in _warned_missing:
            return False
        _warned_missing.add(mark)
        return True


def clear_carbon_cache() -> None:
    """Drop the memoised signals and the warn-once marks (tests, or an operator who wants a forced re-read)."""
    with _load_cache_lock:
        _load_cache.clear()
        _warned_missing.clear()


def load_carbon_signal(zone: str | None = None, *, path: Path | None = None) -> CarbonSignal:
    """Same contract as before (see :func:`_load_carbon_signal_uncached`); repeat loads of an unchanged file are memoised."""
    return _signal_and_curve(zone, path)[0]


def load_diurnal_carbon_intensity(zone: str | None = None) -> tuple[np.ndarray, bool]:
    """Backward-compatible ``(curve_by_site_local_hour, is_real)``. ``is_real == (not is_fallback)``.

    Prefer :func:`load_carbon_signal`: this tuple cannot say whether the data is average or marginal.
    """
    sig, curve = _signal_and_curve(zone, None)
    return curve.copy(), not sig.is_fallback
