"""Task 6 screening runner (READ-ONLY).

Applies the LOCKED Task 5 protocol (research/danish_aau/protocol/protocol_v1.toml) unchanged to the Danish AAU
power/temperature CSVs and prints AGGREGATE pair tables only (no raw rows, no per-second values).

* Never writes inside the raw folder; never modifies a raw file; no network; no imputation, no resampling.
* Thresholds, resolutions and tie rules are read from the locked protocol; nothing is hard-coded here.
* Statistics are vectorised numpy re-implementations of `protocol.rules.screen_pair`; the test file
  `test_task6_screen.py` checks that they agree with `screen_pair` on synthetic fixtures.

Run from the repository root (PowerShell):
    python -m research.danish_aau.screening.run_task6_screen --raw .\\realData\\danish-server-room-v5\\raw
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.danish_aau.protocol.lock import verify  # noqa: E402
from research.danish_aau.protocol.protocol import Protocol, ProtocolError, load_protocol  # noqa: E402
from research.danish_aau.protocol.rules import _pearson, to_ticks  # noqa: E402

TS_COLUMN = "Time [Date/Time]"
TS_FORMAT = "%Y-%m-%d %H:%M:%S"
MANIFEST = REPO_ROOT / "docs" / "datasets" / "danish-server-room-v5" / "manifest.json"
AMBIGUITY_MARGIN = 1e-6  # in scaled (tick) units; cells this close to a .5 tie are re-rounded with Decimal on the text
MAX_GRID = 50_000_000

# ----------------------------------------------------------------------------------------------------------------------
# Task 3 identity evidence (CSV column -> source-image label). Evidence only; never inferred here.
# ----------------------------------------------------------------------------------------------------------------------
_TEMP_LABELS = """
1 1 Rack 2 front|1 2 Rack 6 back 1|1 3 Rack 5 front 1|1 4 Rack 5 front 2|1 5 Rack 5 front 3|1 6 Rack 4 front
1 7 Rack 6 front|1 8 Rack 3 front|2 1 Rack 5 back L5|2 2 Rack 5 back L3|2 3 Rack 6 back 2|2 4 Rack 5 back L6
2 5 Rack 5 back L4|2 6 Rack 5 back L2|2 7 Rack 1 front|2 8 Rack 5 back L1|3 1 Back cooling window
3 2 Back cooling wall|3 3 Rack 5 back L7|3 4 Rack 5 back R1|3 5 Rack 5 back R3|3 6 Rack 5 back L8
3 7 Rack 5 back L9|3 8 Rack 5 back R2|4 1 Gradient 1|4 2 Gradient 2|4 3 Gradient 3|4 4 Gradient 5|4 5 Gradient 4
4 6 Rack 5 back R4|4 7 Rack 5 back R6|4 8 Rack 5 back R5|5 1 Rack 5 back R7|5 2 Rack 5 back R8|5 3 Rack 5 back R9
5 4 Rack 4 back 1|6 1 Rack 2 back 1|6 2 Rack 3 back 2|6 3 Rack 3 back 1|6 4 Rack 4 back 2|7 1 Rack 5 front 4
7 2 Rack 1 back 2|7 3 Rack 1 back 1|7 4 Rack 2 back 2|8 1 Cooling wall Front R|8 2 Cooling wall Front L
8 3 Cooling window Front R|8 4 Cooling window Front L
"""
# workbook column K / power.png: port 1 -> racks 1,2,3; port 2 -> racks 4 and 6; port 3 -> rack 5 (group sums, never split)
POWER_RACKS = {"Power Ch 1 (W)": (1, 2, 3), "Power Ch 2 (W)": (4, 6), "Power Ch 3 (W)": (5,)}


@dataclass(frozen=True)
class SeriesInfo:
    column: str
    label: str
    cls: str  # P power | R rack probe | F facility-level (cooling unit / room gradient)
    rack: int | None  # source rack number for rack probes
    power_racks: tuple[int, ...] = ()


def build_register() -> dict[str, SeriesInfo]:
    reg: dict[str, SeriesInfo] = {}
    for col, racks in POWER_RACKS.items():
        reg[col] = SeriesInfo(col, "Power group: racks " + ",".join(map(str, racks)), "P", None, racks)
    for item in _TEMP_LABELS.replace("\n", "|").split("|"):
        item = item.strip()
        if not item:
            continue
        mod, ch, label = item.split(" ", 2)
        col = f"Temperature mod {mod} ch {ch}"
        if label.startswith("Rack "):
            reg[col] = SeriesInfo(col, label, "R", int(label.split()[1]))
        else:
            reg[col] = SeriesInfo(col, label, "F", None)
    return reg


REGISTER = build_register()
KIND = {("P", "P"): "P-P", ("P", "R"): "R-P", ("R", "R"): "R-R", ("F", "R"): "R-F", ("F", "P"): "P-F"}


def pair_kind(a: SeriesInfo, b: SeriesInfo) -> str | None:
    """Scope of the protocol; facility-vs-facility pairs are out of scope (None)."""
    return KIND.get(tuple(sorted((a.cls, b.cls))))  # type: ignore[arg-type]


# ----------------------------------------------------------------------------------------------------------------------
# 1. Reading and exact tick conversion
# ----------------------------------------------------------------------------------------------------------------------


class RunnerError(RuntimeError):
    pass


def scale_for(resolution: Decimal) -> int:
    exp = resolution.as_tuple().exponent
    if not isinstance(exp, int) or exp > 0 or resolution != Decimal(1).scaleb(exp):
        raise RunnerError(f"resolution {resolution} is not a power of ten <= 1")
    return 10 ** (-exp)


def ticks_from_floats(values: np.ndarray, scale: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(ticks float64, finite mask, ambiguous mask). ROUND_HALF_EVEN-equivalent except where flagged ambiguous."""
    scaled = values * scale
    finite = np.isfinite(scaled)
    safe = np.where(finite, scaled, 0.0)
    frac = safe - np.floor(safe)
    ambiguous = finite & (np.abs(frac - 0.5) < AMBIGUITY_MARGIN)
    return np.rint(safe), finite, ambiguous


def read_panel(path: Path, proto: Protocol, chunk_rows: int = 250_000) -> dict:
    """Parse one CSV into (seconds, tick matrix, observed mask) in SOURCE ROW ORDER. Rejects unexpected schema."""
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if not header or header[0] != TS_COLUMN:
        raise RunnerError(f"{path.name}: first column must be {TS_COLUMN!r}, got {header[:1]}")
    cols = header[1:]
    unknown = [c for c in cols if c not in REGISTER]
    missing = [c for c in REGISTER if c not in cols]
    if unknown or missing or len(set(cols)) != len(cols):
        raise RunnerError(f"{path.name}: unexpected schema. unknown={unknown} missing={missing}")
    res = [proto.resolution(c, path.name) for c in cols]
    scale = np.array([float(scale_for(r)) for r in res])
    secs_parts, tick_parts, valid_parts = [], [], []
    n_ambiguous = n_blank = 0
    start = 0
    reader = pd.read_csv(path, chunksize=chunk_rows, dtype={TS_COLUMN: str}, float_precision="high")
    for chunk in reader:
        bad = [c for c in cols if chunk[c].dtype == object]
        if bad:
            raise RunnerError(f"{path.name}: non-numeric tokens in {bad[:5]} (rows {start + 2}..)")
        ts = pd.to_datetime(chunk[TS_COLUMN], format=TS_FORMAT, errors="raise")
        secs = ts.to_numpy().astype("datetime64[s]").astype(np.int64)  # naive wall-clock seconds, no timezone applied
        vals = chunk[cols].to_numpy(dtype=np.float64)
        ticks, finite, amb = ticks_from_floats(vals, scale)
        n_blank += int(np.isnan(vals).sum())
        if (~finite & ~np.isnan(vals)).any():
            raise RunnerError(f"{path.name}: non-finite values (inf) in rows {start + 2}..")
        if np.abs(ticks).max(initial=0) > 2**31 - 1:
            raise RunnerError(f"{path.name}: tick overflow")
        if amb.any():
            n_ambiguous += int(amb.sum())
            rr, cc = np.nonzero(amb)
            text = pd.read_csv(
                path,
                header=None,
                skiprows=start + 1,
                nrows=len(chunk),
                usecols=sorted({int(c) + 1 for c in cc}),
                dtype=str,
            )
            for r, c in zip(rr, cc, strict=True):
                ticks[r, c] = to_ticks(str(text[int(c) + 1].iat[int(r)]), res[int(c)])
        secs_parts.append(secs)
        tick_parts.append(ticks.astype(np.int32))
        valid_parts.append(finite)
        start += len(chunk)
    if not secs_parts:
        raise RunnerError(f"{path.name}: no data rows")
    return {
        "columns": cols,
        "secs": np.concatenate(secs_parts),
        "ticks": np.concatenate(tick_parts),
        "valid": np.concatenate(valid_parts),
        "n_ambiguous": n_ambiguous,
        "n_blank": n_blank,
        "resolutions": {c: str(r) for c, r in zip(cols, res, strict=True)},
    }


# ----------------------------------------------------------------------------------------------------------------------
# 2. Duplicate groups and cell-level conflict handling (protocol [duplicates]; authority_fields must be empty)
# ----------------------------------------------------------------------------------------------------------------------


def canonicalise(secs: np.ndarray, ticks: np.ndarray, valid: np.ndarray, proto: Protocol) -> dict:
    """One canonical row per naive second. Conflicting cells become missing (conflict_unresolved_tie); no imputation."""
    dup = proto["duplicates"]
    if dup["authority_fields"]:
        raise RunnerError("runner implements only the locked empty authority_fields list")
    n = len(secs)
    order = np.argsort(secs, kind="stable")  # bookkeeping order only; outcome never depends on it
    secs, ticks, valid = secs[order], ticks[order], valid[order]
    new = np.ones(n, dtype=bool)
    new[1:] = secs[1:] != secs[:-1]
    starts = np.flatnonzero(new)
    counts = np.diff(np.append(starts, n))
    u = len(starts)
    out_t, out_v = ticks[starts].copy(), valid[starts].copy()
    ledger = {"rows": n, "retained": 0, "exact_duplicate": 0, "conflict_cell_missing": 0}
    ledger["retained"] += int((counts == 1).sum())
    cells_missing = 0
    sizes: dict[int, int] = {}
    big = np.iinfo(np.int32).max
    for g in np.flatnonzero(counts > 1):
        s, k = int(starts[g]), int(counts[g])
        sizes[k] = sizes.get(k, 0) + 1
        blk, vv = ticks[s : s + k], valid[s : s + k]
        anyv = vv.any(axis=0)
        mn = np.where(vv, blk, big).min(axis=0)
        mx = np.where(vv, blk, -big).max(axis=0)
        conflict = anyv & (mn != mx)
        out_t[g] = np.where(anyv & ~conflict, mn, 0)
        out_v[g] = anyv & ~conflict
        cells_missing += int(conflict.sum())
        if conflict.any():
            ledger["conflict_cell_missing"] += k
        else:
            ledger["retained"] += 1
            ledger["exact_duplicate"] += k - 1
    if ledger["retained"] + ledger["exact_duplicate"] + ledger["conflict_cell_missing"] != n:
        raise RunnerError("ledger does not reconcile")
    return {
        "secs": secs[starts],
        "ticks": out_t,
        "valid": out_v,
        "ledger": ledger,
        "cells_missing": cells_missing,
        "group_sizes": sizes,
        "unique_seconds": u,
    }


def to_grid(secs_u: np.ndarray, ticks_u: np.ndarray, valid_u: np.ndarray) -> dict:
    """Regular 1 s grid, series-major (S, G). Missing seconds stay unobserved (no fill)."""
    sec0 = int(secs_u[0])
    g = int(secs_u[-1]) - sec0 + 1
    if g > MAX_GRID:
        raise RunnerError(f"grid of {g} seconds is implausibly large")
    idx = (secs_u - sec0).astype(np.int64)
    s = ticks_u.shape[1]
    t = np.zeros((s, g), dtype=np.int32)
    v = np.zeros((s, g), dtype=bool)
    t[:, idx] = ticks_u.T
    v[:, idx] = valid_u.T
    return {"T": t, "V": v, "sec0": sec0}


# ----------------------------------------------------------------------------------------------------------------------
# 3. Vectorised screening statistics (same definitions as protocol.rules.screen_pair)
# ----------------------------------------------------------------------------------------------------------------------


def series_events(valid: np.ndarray, ticks: np.ndarray, flat_run: int, gap_step: int) -> np.ndarray:
    """Sorted codes: gap at previous second -> 2*pos, flatline start -> 2*pos+1 (same events as rules._events)."""
    pos = np.flatnonzero(valid)
    if len(pos) < 2:
        return np.empty(0, dtype=np.int64)
    vals = ticks[pos]
    ds = np.diff(pos)
    ev = [pos[:-1][ds > gap_step] * 2]
    cont = (ds <= gap_step) & (vals[1:] == vals[:-1])
    pad = np.concatenate(([False], cont, [False])).astype(np.int8)
    edge = np.diff(pad)
    run_starts, run_ends = np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)
    long_runs = (run_ends - run_starts) >= flat_run - 1
    ev.append(pos[run_starts[long_runs]] * 2 + 1)
    return np.unique(np.concatenate(ev).astype(np.int64))


def lag_correlations(t: np.ndarray, v: np.ndarray, max_lag: int) -> tuple[np.ndarray, list[int]]:
    """R[k, i, j] = Pearson of first differences dx_i[t] vs dx_j[t+lag_k], pairs where all four samples exist.

    Pairwise sums come from BLAS products of masked difference matrices; final algebra uses exact Python integers."""
    s, g = t.shape
    vd = np.zeros((s, g))
    a = np.zeros((s, g))
    for i in range(s):
        m = v[i, 1:] & v[i, :-1]
        vd[i, 1:] = m
        a[i, 1:] = np.where(m, t[i, 1:].astype(np.int64) - t[i, :-1], 0)
    a2 = a * a
    lags = list(range(-max_lag, max_lag + 1))
    out = np.full((len(lags), s, s), np.nan)
    for k, lag in enumerate(lags):
        if lag >= 0:
            left, right = slice(0, g - lag), slice(lag, g)
        else:
            left, right = slice(-lag, g), slice(0, g + lag)
        if g - abs(lag) < 2:
            continue

        def blk(x, y, left=left, right=right):
            return np.rint(x[:, left] @ y[:, right].T).astype(np.int64).astype(object)

        n, sx, sy = blk(vd, vd), blk(a, vd), blk(vd, a)
        sxx, syy, sxy = blk(a2, vd), blk(vd, a2), blk(a, a)
        vx = n * sxx - sx * sx
        vy = n * syy - sy * sy
        num = n * sxy - sx * sy
        ok = (n >= 2) & (vx > 0) & (vy > 0)
        den = np.sqrt(np.where(ok, vx, 1).astype(float) * np.where(ok, vy, 1).astype(float))
        r = np.where(ok, num.astype(float) / den, np.nan)
        out[k] = r
    return out, lags


@dataclass
class PairRecord:
    i: int
    j: int
    kind: str
    level: int
    status: str
    reasons: tuple[str, ...]
    stats: dict[str, float] = field(default_factory=dict)


def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    union = len(a) + len(b) - len(np.intersect1d(a, b, assume_unique=True))
    return len(np.intersect1d(a, b, assume_unique=True)) / union if union else float("nan")


def screen_pair_fast(
    i: int, j: int, t: np.ndarray, v: np.ndarray, pre: dict, r_lag: np.ndarray, lags: list[int], proto: Protocol
) -> tuple[int, str, tuple[str, ...], dict[str, float]]:
    sc, th = proto["screening"], proto.thresholds
    reasons: list[str] = []
    level = 0
    m = v[i] & v[j]
    n = int(m.sum())
    stats: dict[str, float] = {"n_overlap": float(n)}
    if n < sc["min_overlap_samples"]:
        return level, "insufficient_overlap", tuple(reasons), stats
    x = t[i][m].astype(np.int64)
    y = t[j][m].astype(np.int64)
    span = sc["min_span_ticks"]
    if (x.max() - x.min()) < span or (y.max() - y.min()) < span:
        return level, "degenerate_series", tuple(reasons), stats
    stats["frac_equal"] = float(np.mean(x == y))
    d = x - y
    stats["frac_offset"] = float(np.bincount(d - d.min()).max() / len(d))
    slope, icpt = np.polyfit(x.astype(float), y.astype(float), 1)
    resid = np.abs(y - (slope * x + icpt))
    stats["frac_affine"] = float(np.mean(resid <= th["affine_tolerance_ticks"]))
    if stats["frac_equal"] >= th["l3_equal_fraction"]:
        reasons.append("equal_at_resolution")
    if stats["frac_offset"] >= th["l3_offset_fraction"]:
        reasons.append("constant_offset")
    if stats["frac_affine"] >= th["l3_affine_fraction"]:
        reasons.append("affine_copy")
    if reasons:
        level = 3
    r_lvl = _pearson(x.astype(float), y.astype(float))
    stats["r_levels"] = r_lvl
    k0 = lags.index(0)
    r_diff = float(r_lag[k0, i, j])
    stats["r_diff"] = r_diff
    best_r, best_lag = 0.0, 0
    for k, lag in enumerate(lags):
        r = float(r_lag[k, i, j])
        if not math.isnan(r) and abs(r) > abs(best_r):
            best_r, best_lag = r, lag
    stats["best_lag_r_diff"], stats["best_lag_seconds"] = best_r, float(best_lag)
    ea, eb = pre["events"][i], pre["events"][j]
    stats["n_events_a"], stats["n_events_b"] = float(len(ea)), float(len(eb))
    stats["event_jaccard"] = jaccard(ea, eb)
    va, vb = pre["values"][i], pre["values"][j]
    stats["value_set_jaccard"] = jaccard(va, vb)
    stats["value_set_distinct"] = float(min(len(va), len(vb)))
    l2 = []
    if not math.isnan(r_diff) and abs(r_diff) >= th["l2_diff_correlation"]:
        l2.append("first_difference_correlation")
    if abs(best_r) >= th["l2_lag_diff_correlation"] and best_lag != 0:
        l2.append("lagged_difference_correlation")
    if (
        min(len(ea), len(eb)) >= th["l2_shared_event_min_events"]
        and stats["event_jaccard"] >= th["l2_shared_event_jaccard"]
    ):
        l2.append("shared_gaps_or_flatlines")
    if (
        stats["value_set_distinct"] >= th["l2_value_set_min_distinct"]
        and stats["value_set_jaccard"] >= th["l2_value_set_jaccard"]
    ):
        l2.append("identical_value_set")
    if l2:
        reasons.extend(l2)
        level = max(level, 2)
    if level < 2 and not math.isnan(r_lvl) and abs(r_lvl) >= th["l1_level_correlation"]:
        reasons.append("level_correlation_shared_driver")
        level = max(level, 1)
    return level, "screened", tuple(reasons), stats


def screen_panel(grid: dict, columns: list[str], proto: Protocol, progress=None) -> list[PairRecord]:
    t, v = grid["T"], grid["V"]
    fam = proto.family("power_temperature")
    info = [REGISTER[c] for c in columns]
    pre = {
        "events": [
            series_events(v[i], t[i], fam["flatline_min_run"], fam["gap_min_step_seconds"]) for i in range(len(columns))
        ],
        "values": [np.unique(t[i][v[i]]) for i in range(len(columns))],
    }
    if fam["diff_step_seconds"] != 1:
        raise RunnerError("runner implements diff_step_seconds = 1 only (locked value)")
    r_lag, lags = lag_correlations(t, v, int(fam["max_lag_seconds"]))
    records: list[PairRecord] = []
    pairs = [(i, j) for i in range(len(columns)) for j in range(i + 1, len(columns)) if pair_kind(info[i], info[j])]
    for n, (i, j) in enumerate(pairs, 1):
        level, status, reasons, stats = screen_pair_fast(i, j, t, v, pre, r_lag, lags, proto)
        records.append(PairRecord(i, j, pair_kind(info[i], info[j]) or "", level, status, reasons, stats))
        if progress and n % 200 == 0:
            progress(f"    pairs {n}/{len(pairs)}")
    return records


# ----------------------------------------------------------------------------------------------------------------------
# 4. Reporting (aggregate tables only)
# ----------------------------------------------------------------------------------------------------------------------

STAT_KEYS = (
    "n_overlap",
    "frac_equal",
    "frac_offset",
    "frac_affine",
    "r_levels",
    "r_diff",
    "best_lag_r_diff",
    "best_lag_seconds",
    "event_jaccard",
    "n_events_a",
    "n_events_b",
    "value_set_jaccard",
    "value_set_distinct",
)


def short(col: str) -> str:
    return col.replace("Temperature mod ", "T").replace(" ch ", ".").replace("Power Ch ", "P").replace(" (W)", "")


def fmt(x: float | None, nd: int = 4) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def annotate(a: SeriesInfo, b: SeriesInfo) -> str:
    notes = []
    if a.cls == "R" and b.cls == "R" and a.rack == b.rack:
        notes.append("same_rack")
    for p, q in ((a, b), (b, a)):
        if p.cls == "P" and q.cls == "R" and q.rack in p.power_racks:
            notes.append("rack_on_this_power_group")
    return ",".join(notes)


def pair_row(rec: PairRecord, info: list[SeriesInfo], cols: list[str]) -> list[str]:
    a, b = info[rec.i], info[rec.j]
    s = rec.stats
    return [
        rec.kind,
        f"{short(cols[rec.i])} [{a.label}]",
        f"{short(cols[rec.j])} [{b.label}]",
        str(rec.level),
        rec.status,
        ";".join(rec.reasons),
        annotate(a, b),
        *(fmt(s.get(k), 0 if k.startswith(("n_", "value_set_d", "best_lag_s")) else 4) for k in STAT_KEYS),
    ]


PAIR_HEADER = ["kind", "series_a", "series_b", "level", "status", "reasons", "context", *STAT_KEYS]


def table(rows: list[list[str]], header: list[str]) -> str:
    return "\n".join("\t".join(r) for r in [header, *rows])


def union_find_units(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for x in range(n):
        groups.setdefault(find(x), []).append(x)
    return sorted(groups.values())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def row_hashes(ticks: np.ndarray, valid: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(20261105)
    w = rng.integers(1, 2**62, size=ticks.shape[1], dtype=np.int64) | 1
    mixed = np.where(valid, ticks.astype(np.int64) + 1_000_003, 0)
    return (mixed * w).sum(axis=1)  # wraps modulo 2**64 deliberately


def summarise_file(name: str, records: list[PairRecord], cols: list[str], out: list[str], max_rows: int) -> None:
    info = [REGISTER[c] for c in cols]
    out.append(f"\n--- {name}: pair outcome counts (rows = pair kind) ---")
    rows = []
    for kind in ("R-R", "R-P", "P-P", "R-F", "P-F"):
        rs = [r for r in records if r.kind == kind]
        c = lambda **kw: sum(all(getattr(r, k) == val for k, val in kw.items()) for r in rs)  # noqa: E731
        rows.append(
            [
                kind,
                str(len(rs)),
                str(c(status="screened")),
                str(c(status="insufficient_overlap")),
                str(c(status="degenerate_series")),
                *(str(c(status="screened", level=lv)) for lv in (0, 1, 2, 3)),
            ]
        )
    out.append(table(rows, ["kind", "pairs", "screened", "insufficient_overlap", "degenerate", "L0", "L1", "L2", "L3"]))
    scr = [r for r in records if r.status == "screened"]
    out.append(f"\n--- {name}: maximum of each statistic over screened pairs (distance from locked thresholds) ---")
    rows = []
    for key in (
        "frac_equal",
        "frac_offset",
        "frac_affine",
        "r_diff",
        "best_lag_r_diff",
        "event_jaccard",
        "value_set_jaccard",
        "r_levels",
    ):
        vals = [(abs(r.stats[key]), r) for r in scr if not math.isnan(r.stats.get(key, float("nan")))]
        if not vals:
            continue
        top, rec = max(vals, key=lambda p: p[0])
        rows.append([key, fmt(top), rec.kind, short(cols[rec.i]), short(cols[rec.j])])
    out.append(table(rows, ["statistic(|max|)", "value", "kind", "series_a", "series_b"]))
    flagged = sorted(
        [r for r in records if r.level >= 2], key=lambda r: (-r.level, -abs(r.stats.get("r_diff", 0) or 0))
    )
    out.append(
        f"\n--- {name}: flagged pairs (Level >= 2): {len(flagged)} (L3 {sum(r.level == 3 for r in flagged)}) ---"
    )
    shown = flagged[:max_rows]
    out.append(table([pair_row(r, info, cols) for r in shown], PAIR_HEADER) if shown else "(none)")
    if len(flagged) > len(shown):
        out.append(f"... {len(flagged) - len(shown)} more flagged pairs not printed (see the TSV in --out-dir)")
    l1 = [r for r in records if r.level == 1]
    out.append(f"\n--- {name}: Level 1 (shared-driver level correlation, recorded only): {len(l1)} pairs ---")
    for kind in ("R-R", "R-P", "P-P", "R-F", "P-F"):
        ks = [r for r in l1 if r.kind == kind]
        if ks:
            out.append(
                f"  {kind}: {len(ks)} pairs, |r_levels| range {fmt(min(abs(r.stats['r_levels']) for r in ks), 3)}..{fmt(max(abs(r.stats['r_levels']) for r in ks), 3)}"
            )
    # Bounds on independent units (NOT dispositions)
    n = len(cols)
    sel = [i for i in range(n) if info[i].cls in ("R", "P")]
    out.append(
        f"\n--- {name}: bounds on independent units among the {len(sel)} rack/power series (NOT dispositions) ---"
    )
    for label, minlvl in (
        ("no pair merged (upper bound)", 99),
        ("all L3 pairs merged", 3),
        ("all L2+L3 pairs merged (lower bound)", 2),
    ):
        edges = [(r.i, r.j) for r in records if r.level >= minlvl and r.i in sel and r.j in sel]
        units = union_find_units(n, edges)
        count = sum(1 for u in units if any(x in sel for x in u))
        out.append(
            f"  {label}: {count} units; merged clusters: "
            + (
                "; ".join(
                    "{" + ", ".join(short(cols[x]) for x in u if x in sel) + "}"
                    for u in units
                    if sum(x in sel for x in u) > 1
                )
                or "none"
            )
        )


def write_tsv(path: Path, records: list[PairRecord], cols: list[str]) -> None:
    info = [REGISTER[c] for c in cols]
    path.write_text(
        table([pair_row(r, info, cols) for r in records], PAIR_HEADER) + "\n", encoding="utf-8", newline="\n"
    )


# ----------------------------------------------------------------------------------------------------------------------
# 5. Main
# ----------------------------------------------------------------------------------------------------------------------


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True, type=Path, help="folder with the AAU CSV files (read-only)")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "research" / "danish_aau" / "reports" / "task6_screen")
    ap.add_argument("--files", nargs="*", help="file names to screen (default: all AAU_temperature_and_power_use*.csv)")
    ap.add_argument(
        "--skip-hash", action="store_true", help="skip SHA-256 check against the manifest (sizes still checked)"
    )
    ap.add_argument("--max-rows", type=int, default=300, help="max flagged pairs printed per file")
    ap.add_argument("--chunk-rows", type=int, default=250_000)
    args = ap.parse_args(argv)

    raw = args.raw.resolve()
    if not raw.is_dir():
        print(f"raw folder not found: {raw}")
        return 2
    if inside(args.out_dir, raw):
        print("refusing to write inside the raw folder")
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)

    out: list[str] = []
    started = time.time()

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    # --- protocol --------------------------------------------------------------------------------------------------
    try:
        rec = verify()
        proto = load_protocol()
    except ProtocolError as exc:
        print(f"PROTOCOL ERROR: {exc}")
        return 1
    if proto.open_items():
        print(f"protocol has open items: {proto.open_items()}")
        return 1
    fam = proto.family("power_temperature")
    names = args.files or sorted(p.name for p in raw.glob("*.csv") if fnmatch.fnmatchcase(p.name, fam["files_glob"]))
    names = sorted(names, key=lambda s: (s != "AAU_temperature_and_power_use.csv", s))
    out.append("TASK6_SCREEN | read-only | aggregate pair tables only")
    out.append(
        f"protocol {rec['protocol_file']} v{rec['version']} sha256(LF) {rec['sha256_lf_normalised']} approved {rec['approved_by']} {rec['approved_on']}"
    )
    out.append(
        f"python {platform.python_version()} numpy {np.__version__} pandas {pd.__version__} | {platform.platform()} | cpus {os.cpu_count()}"
    )
    out.append(f"runner sha256 {hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}")
    out.append(
        f"time basis: naive text seconds, timezone undeclared (no conversion) | resolutions: temperature 0.01 degC, power 0.1 W | authority_fields {proto['duplicates']['authority_fields']}"
    )

    # --- raw file check vs manifest --------------------------------------------------------------------------------
    manifest = {f["filename"]: f for f in json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["files"]}
    out.append("\n--- raw file verification vs docs/datasets manifest ---")
    for nme in names:
        p = raw / nme
        if nme not in manifest or not p.is_file():
            out.append(f"{nme}: NOT FOUND or not in manifest")
            print("\n".join(out))
            return 1
        size_ok = p.stat().st_size == manifest[nme]["size_bytes"]
        if args.skip_hash:
            sha = "skipped"
        else:
            log(f"hashing {nme}")
            sha = "match" if sha256_file(p) == manifest[nme]["local_sha256"] else "MISMATCH"
        out.append(f"{nme}\tsize {'ok' if size_ok else 'MISMATCH'}\tsha256 {sha}")
        if not size_ok or sha == "MISMATCH":
            out.append("ABORT: raw file differs from the manifest; no screening performed")
            print("\n".join(out))
            return 1

    all_records: dict[str, list[PairRecord]] = {}
    cols_ref: list[str] | None = None
    hashes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for nme in names:
        log(f"[{nme}] reading")
        panel = read_panel(raw / nme, proto, args.chunk_rows)
        cols = panel["columns"]
        if cols_ref is None:
            cols_ref = cols
        elif cols != cols_ref:
            raise RunnerError(f"{nme}: column order differs from the first file")
        can = canonicalise(panel["secs"], panel["ticks"], panel["valid"], proto)
        led = can["ledger"]
        steps = np.diff(can["secs"])
        out.append(f"\n=== {nme} ===")
        out.append(
            f"raw rows {led['rows']} | unique seconds {can['unique_seconds']} | ledger: retained {led['retained']}, exact_duplicate {led['exact_duplicate']}, conflict_cell_missing {led['conflict_cell_missing']} (sum {led['retained'] + led['exact_duplicate'] + led['conflict_cell_missing']})"
        )
        out.append(
            f"repeated-timestamp group sizes {dict(sorted(can['group_sizes'].items()))} | cells made missing by unresolved ties {can['cells_missing']} | blank cells in source {panel['n_blank']} | cells re-rounded with Decimal (near-tie) {panel['n_ambiguous']}"
        )
        uniq, cnt = np.unique(steps, return_counts=True)
        step_counts = (
            {int(k): int(c) for k, c in zip(uniq, cnt, strict=True)} if len(uniq) < 12 else "many distinct steps"
        )
        out.append(
            f"span {int(can['secs'][-1] - can['secs'][0])} s | step counts {step_counts} | "
            f"gaps > 3 s: {int((steps > fam['gap_min_step_seconds']).sum())}"
        )
        hashes[nme] = (can["secs"], row_hashes(can["ticks"], can["valid"]))
        grid = to_grid(can["secs"], can["ticks"], can["valid"])
        del panel
        log(f"[{nme}] screening {len(cols)} series")
        recs = screen_panel(grid, cols, proto, progress=lambda m: log(f"  [{nme}] {m}"))
        all_records[nme] = recs
        write_tsv(args.out_dir / f"pairs_{Path(nme).stem}.tsv", recs, cols)
        summarise_file(nme, recs, cols, out, args.max_rows)
        del grid

    assert cols_ref is not None
    info = [REGISTER[c] for c in cols_ref]
    # --- consistency across files ------------------------------------------------------------------------------------
    out.append(
        "\n=== Replication: Level >= 2 pairs per file (columns = files; value = level or . when < 2 or unscreened) ==="
    )
    keys = sorted({(r.i, r.j) for rs in all_records.values() for r in rs if r.level >= 2})
    short_names = {
        n: n.replace("AAU_temperature_and_power_use", "")
        .replace("_percent_load_period", "pct")
        .replace(".csv", "")
        .strip("_")
        or "full"
        for n in names
    }
    rows = []
    for i, j in keys:
        row = [
            pair_kind(info[i], info[j]) or "",
            f"{short(cols_ref[i])} [{info[i].label}]",
            f"{short(cols_ref[j])} [{info[j].label}]",
        ]
        for nme in names:
            hit = next((r for r in all_records[nme] if (r.i, r.j) == (i, j)), None)
            row.append(str(hit.level) if hit and hit.level >= 2 else ".")
        rows.append(row)
    out.append(
        table(rows, ["kind", "series_a", "series_b", *[short_names[n] for n in names]])
        if rows
        else "(no pair reached Level 2 in any file)"
    )

    # --- period files vs full file --------------------------------------------------------------------------------------
    full = "AAU_temperature_and_power_use.csv"
    if full in hashes and len(hashes) > 1:
        out.append("\n=== Period files vs full file (canonical rows at the same naive second) ===")
        fs, fh = hashes[full]
        rows = []
        for nme in names:
            if nme == full:
                continue
            ps, ph = hashes[nme]
            pos = np.searchsorted(fs, ps)
            pos = np.minimum(pos, len(fs) - 1)
            present = fs[pos] == ps
            same = present & (fh[pos] == ph)
            rows.append([short_names[nme], str(len(ps)), f"{present.mean():.6f}", f"{same.mean():.6f}"])
        out.append(table(rows, ["file", "seconds", "frac_seconds_in_full", "frac_rows_identical_to_full"]))
        out.append("(identical rows would make the period files non-independent replications of the full file)")

    # --- scope limits ---------------------------------------------------------------------------------------------------
    out.append(
        "\n=== Not screened (protocol cross_cadence = not_comparable; no resampling) ===\n"
        "rack/power series vs AAU_supplementary_surrounding_temperatures (900 s), AAU_supplementary_ventilation (120-780 s) and AAU_air_speed* (10 s): not_comparable_cadence.\n"
        "Facility-level comparison here is limited to the cooling-unit and room-gradient probes inside the 1 s temperature/power files."
    )
    out.append(f"\nfinished in {time.time() - started:.0f} s | per-file full pair tables: {args.out_dir}")
    text = "\n".join(out)
    (args.out_dir / "task6_screen_output.txt").write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
