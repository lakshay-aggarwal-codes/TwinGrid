"""Pure reference implementation of the protocol rules. No file or database access; thresholds come from Protocol.

Used by the synthetic-fixture tests now, and by Task 6 (screening) and Task 12 (cleaning) later.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

import numpy as np

from .protocol import Protocol, ProtocolError

# ======================================================================================================================
# 1. Canonical value at the declared resolution
# ======================================================================================================================


def to_ticks(text: str, resolution: Decimal) -> int:
    """Integer number of `resolution` steps for a SOURCE TEXT value (decimal arithmetic, ROUND_HALF_EVEN)."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise ProtocolError(f"not a decimal number: {text!r}") from exc
    if not value.is_finite():
        raise ProtocolError(f"non-finite value: {text!r}")
    return int((value / resolution).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def canonical_text(ticks: int, resolution: Decimal) -> str:
    """Canonical decimal text of a tick count (fixed number of decimals = the resolution's)."""
    places = max(0, -resolution.as_tuple().exponent)
    return format(Decimal(ticks) * resolution, f".{places}f")


# ======================================================================================================================
# 2. Duplicate groups and conflict resolution (one timestamp group at a time)
# ======================================================================================================================


@dataclass(frozen=True)
class RawRow:
    row_number: int  # source line number (bookkeeping only)
    cells: Mapping[str, str]  # column -> source text ("" = blank / not observed)
    authority: Mapping[str, float] = field(default_factory=dict)  # documented authority fields, if the source has any


@dataclass(frozen=True)
class CellResult:
    column: str
    observed: bool
    value: str | None  # canonical text, None when missing
    reason: str | None  # None, or the protocol tie reason
    source_rows: tuple[int, ...]  # rows that supplied the value (or all candidates when missing)


@dataclass(frozen=True)
class GroupResult:
    cells: dict[str, CellResult]
    row_dispositions: dict[int, str]  # exactly one per raw row
    group_kind: str  # single | exact_duplicate | conflict


def resolve_group(rows: Sequence[RawRow], resolutions: Mapping[str, Decimal], protocol: Protocol) -> GroupResult:
    """Resolve all rows that share one naive timestamp in one file. Order of `rows` must not matter."""
    if not rows:
        raise ProtocolError("empty group")
    ids = [r.row_number for r in rows]
    if len(set(ids)) != len(ids):
        raise ProtocolError("row numbers must be unique inside a group")
    dup = protocol["duplicates"]
    fields = dup["authority_fields"]
    rows = sorted(rows, key=lambda r: r.row_number)  # bookkeeping order only; outcome never depends on it
    columns = sorted({c for r in rows for c in r.cells})

    cells: dict[str, CellResult] = {}
    any_conflict = False
    any_missing_from_tie = False
    for col in columns:
        res = resolutions[col]
        cands: list[tuple[int, RawRow]] = []  # (ticks, row) for non-blank cells
        for r in rows:
            txt = r.cells.get(col, "")
            if txt.strip() != "":
                cands.append((to_ticks(txt, res), r))
        distinct = {t for t, _ in cands}
        if not cands:
            cells[col] = CellResult(col, False, None, None, ())
        elif len(distinct) == 1:
            t = next(iter(distinct))
            cells[col] = CellResult(col, True, canonical_text(t, res), None, tuple(r.row_number for _, r in cands))
        else:
            any_conflict = True
            winner = _authority_winner(cands, fields)
            if winner is None:
                any_missing_from_tie = True
                cells[col] = CellResult(
                    col, False, None, dup["tie_reason"], tuple(sorted(r.row_number for _, r in cands))
                )
            else:
                t, r = winner
                cells[col] = CellResult(col, True, canonical_text(t, res), None, (r.row_number,))

    if len(rows) == 1:
        kind, disp = "single", {rows[0].row_number: "retained"}
    elif not any_conflict:
        kind = "exact_duplicate"
        keep = rows[0].row_number  # lowest row number: bookkeeping only
        disp = {r.row_number: ("retained" if r.row_number == keep else "exact_duplicate") for r in rows}
    else:
        kind = "conflict"
        label = "conflict_cell_missing" if any_missing_from_tie else "conflict_resolved_by_source_rule"
        disp = {r.row_number: label for r in rows}
    return GroupResult(cells, disp, kind)


def _authority_winner(cands: list[tuple[int, RawRow]], fields: list[dict]) -> tuple[int, RawRow] | None:
    """Strict winner by documented authority fields in priority order; None when absent, equal, or tied."""
    if not fields:
        return None
    live = list(cands)
    for f in fields:
        name, lower = f["name"], f["direction"] == "lower_wins"
        scored = [(c, c[1].authority.get(name)) for c in live]
        if any(s is None for _, s in scored):
            return None  # a candidate lacks the documented field -> not usable
        best = min(s for _, s in scored) if lower else max(s for _, s in scored)
        live = [c for c, s in scored if s == best]
        if len({t for t, _ in live}) == 1:
            return min(live, key=lambda c: c[1].row_number)  # same value: any holder; bookkeeping only
    # all fields tied but values still differ
    return None


# ======================================================================================================================
# 3. Pair screening (statistics + level assignment)
# ======================================================================================================================


@dataclass(frozen=True)
class SeriesMeta:
    series_id: str
    file: str
    column: str
    sensor_id: str = ""  # documented sensor id, if any


@dataclass(frozen=True)
class PairResult:
    a: str
    b: str
    level: int  # 0 none, 1 recorded, 2 suspect, 3 copy evidence
    status: str  # screened | insufficient_overlap | not_comparable_cadence | degenerate_series
    reasons: tuple[str, ...]
    stats: dict[str, float]


def _align(xs: Mapping[int, int], ys: Mapping[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    secs = np.array(sorted(set(xs) & set(ys)), dtype=np.int64)
    return secs, np.array([xs[s] for s in secs], dtype=np.int64), np.array([ys[s] for s in secs], dtype=np.int64)


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2:
        return float("nan")
    sx, sy = x.std(), y.std()
    if sx == 0 or sy == 0:
        return float("nan")
    return float(np.mean((x - x.mean()) * (y - y.mean())) / (sx * sy))


def _diff_pairs(xs: Mapping[int, int], ys: Mapping[int, int], step: int, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """First differences over `step` seconds of x(t) and y(t+lag); only where all four samples exist."""
    dx, dy = [], []
    for t in xs:
        t2 = t - step
        if t2 in xs and (t + lag) in ys and (t2 + lag) in ys:
            dx.append(xs[t] - xs[t2])
            dy.append(ys[t + lag] - ys[t2 + lag])
    return np.array(dx, dtype=float), np.array(dy, dtype=float)


def _events(series: Mapping[int, int], flat_run: int, gap_step: int) -> set[tuple[str, int]]:
    secs = sorted(series)
    ev: set[tuple[str, int]] = set()
    run_start, run_len = None, 0
    prev = None
    for s in secs:
        if prev is not None and s - prev > gap_step:
            ev.add(("gap", prev))
        if prev is not None and s - prev <= gap_step and series[s] == series[prev]:
            run_len += 1
            if run_len == flat_run - 1:
                ev.add(("flatline", run_start))
        else:
            run_start, run_len = s, 0
        prev = s
    return ev


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else float("nan")


def screen_pair(
    meta_a: SeriesMeta,
    meta_b: SeriesMeta,
    ticks_a: Mapping[int, int],
    ticks_b: Mapping[int, int],
    protocol: Protocol,
    *,
    cadence_a: str = "1s",
    cadence_b: str = "1s",
    family: str = "power_temperature",
) -> PairResult:
    """Apply the frozen screening rules to two series given as {naive second: integer ticks}."""
    pid = (meta_a.series_id, meta_b.series_id)
    sc, th, fam = protocol["screening"], protocol.thresholds, protocol.family(family)
    if cadence_a != cadence_b:
        return PairResult(*pid, 0, "not_comparable_cadence", (), {})

    reasons: list[str] = []
    level = 0
    if (meta_a.file, meta_a.column) == (meta_b.file, meta_b.column):
        reasons.append("same_source_column")
        level = 3
    if meta_a.sensor_id and meta_a.sensor_id == meta_b.sensor_id:
        reasons.append("same_sensor_id")
        level = 3

    secs, x, y = _align(ticks_a, ticks_b)
    stats: dict[str, float] = {"n_overlap": float(len(secs))}
    if len(secs) < sc["min_overlap_samples"]:
        return PairResult(*pid, level, "insufficient_overlap", tuple(reasons), stats)

    span = sc["min_span_ticks"]
    degenerate = (x.max() - x.min()) < span or (y.max() - y.min()) < span
    status = "degenerate_series" if degenerate else "screened"

    if not degenerate:
        stats["frac_equal"] = float(np.mean(x == y))
        d = x - y
        modal = Counter(d.tolist()).most_common(1)[0][0]
        stats["frac_offset"] = float(np.mean(d == modal))
        slope, icpt = np.polyfit(x.astype(float), y.astype(float), 1)
        resid = np.abs(y - (slope * x + icpt))
        stats["frac_affine"] = float(np.mean(resid <= th["affine_tolerance_ticks"]))
        if stats["frac_equal"] >= th["l3_equal_fraction"]:
            reasons.append("equal_at_resolution")
        if stats["frac_offset"] >= th["l3_offset_fraction"]:
            reasons.append("constant_offset")
        if stats["frac_affine"] >= th["l3_affine_fraction"]:
            reasons.append("affine_copy")
        if any(r in reasons for r in ("equal_at_resolution", "constant_offset", "affine_copy")):
            level = 3

        r_lvl = _pearson(x.astype(float), y.astype(float))
        stats["r_levels"] = r_lvl
        step = fam["diff_step_seconds"]
        dx, dy = _diff_pairs(ticks_a, ticks_b, step, 0)
        r_diff = _pearson(dx, dy)
        stats["r_diff"] = r_diff
        best = (0.0, 0)
        for lag in range(-fam["max_lag_seconds"], fam["max_lag_seconds"] + 1):
            lx, ly = _diff_pairs(ticks_a, ticks_b, step, lag)
            r = _pearson(lx, ly)
            if not np.isnan(r) and abs(r) > abs(best[0]):
                best = (r, lag)
        stats["best_lag_r_diff"], stats["best_lag_seconds"] = best[0], float(best[1])

        ea = _events(ticks_a, fam["flatline_min_run"], fam["gap_min_step_seconds"])
        eb = _events(ticks_b, fam["flatline_min_run"], fam["gap_min_step_seconds"])
        stats["n_events_a"], stats["n_events_b"] = float(len(ea)), float(len(eb))
        stats["event_jaccard"] = _jaccard(ea, eb)
        va, vb = set(ticks_a.values()), set(ticks_b.values())
        stats["value_set_jaccard"] = _jaccard(va, vb)
        stats["value_set_distinct"] = float(min(len(va), len(vb)))

        l2 = []
        if not np.isnan(r_diff) and abs(r_diff) >= th["l2_diff_correlation"]:
            l2.append("first_difference_correlation")
        if abs(best[0]) >= th["l2_lag_diff_correlation"] and best[1] != 0:
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
        if level < 2 and not np.isnan(r_lvl) and abs(r_lvl) >= th["l1_level_correlation"]:
            reasons.append("level_correlation_shared_driver")
            level = max(level, 1)
    return PairResult(*pid, level, status, tuple(reasons), stats)


# ======================================================================================================================
# 4. Independent units
# ======================================================================================================================


def independent_units(
    series_ids: Sequence[str], pair_dispositions: Mapping[tuple[str, str], str], protocol: Protocol
) -> list[list[str]]:
    """Clusters of series that count as ONE independent unit. Unresolved pairs stay clustered (conservative)."""
    merge = set(protocol["groups"]["merge_dispositions"])
    allowed = set(protocol["dispositions"]["pair"])
    parent = {s: s for s in series_ids}

    def find(s: str) -> str:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for (a, b), disp in pair_dispositions.items():
        if disp not in allowed:
            raise ProtocolError(f"unknown pair disposition {disp!r}")
        if a not in parent or b not in parent:
            raise ProtocolError(f"pair references unknown series: {a!r}, {b!r}")
        if disp in merge:
            parent[find(a)] = find(b)
    clusters: dict[str, list[str]] = {}
    for s in series_ids:
        clusters.setdefault(find(s), []).append(s)
    return sorted(sorted(c) for c in clusters.values())
