"""Deterministic duplicate canonicalisation and conflict resolution for one CSV.

Two entry points that must agree (a test enforces it):

* ``clean_rows``  reference path: plain rows in, every timestamp group resolved by the protocol's own
                  ``rules.resolve_group``. Used by tests and small inputs. Row order never matters.
* ``clean_file``  production path over the Task 11 adapter reader (no second reader): rows whose timestamp is unique
                  are converted in bulk (float -> ticks, with a Decimal re-round for near-ties); repeated-timestamp
                  groups go through ``rules.resolve_group``.

Rules (locked protocol v1.0.0): group = rows of one file with the same naive timestamp TEXT; values are rounded with
Decimal ROUND_HALF_EVEN on the SOURCE TEXT at the declared resolution; exact duplicate = all non-blank cells equal after
rounding; a conflicting cell with no authority field becomes MISSING (reason conflict_unresolved_tie); a blank never
conflicts; the lowest source row is the bookkeeping representative. No timezone, no UTC, no imputation, no resampling.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np

from ..protocol.protocol import Protocol
from ..protocol.rules import RawRow, resolve_group, to_ticks
from .catalogue import (
    D_CONFLICT_MISSING,
    D_RETAINED,
    REASON_BLANK,
    REASON_NONE,
    REASON_TIE,
    ROW_DISPOSITIONS,
)
from .errors import CleaningError
from .tier1 import TIER1_COLUMNS

AMBIGUITY_MARGIN = 1e-6  # in tick units: cells this close to a .5 tie are re-rounded with Decimal on the text
_DISP_INDEX = {n: i for i, n in enumerate(ROW_DISPOSITIONS)}


def naive_seconds(texts: Sequence[str]) -> np.ndarray:
    """Seconds counted on the naive label (numpy datetime64 without a zone). An ordering key, not an instant."""
    try:
        return np.array(list(texts), dtype="datetime64[s]").astype(np.int64)
    except ValueError as exc:
        raise CleaningError(f"timestamp text is not YYYY-MM-DD HH:MM:SS: {exc}") from None


def scale_for(resolution: Decimal) -> int:
    exp = resolution.as_tuple().exponent
    if not isinstance(exp, int) or exp > 0 or resolution != Decimal(1).scaleb(exp):
        raise CleaningError(f"resolution {resolution} is not a power of ten <= 1")
    return 10 ** (-exp)


def ticks_from_floats(values: np.ndarray, scale: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(ticks float64, finite mask, ambiguous mask); half-even-equivalent except where flagged ambiguous."""
    scaled = values * scale
    finite = np.isfinite(scaled)
    safe = np.where(finite, scaled, 0.0)
    frac = safe - np.floor(safe)
    ambiguous = finite & (np.abs(frac - 0.5) < AMBIGUITY_MARGIN)
    return np.rint(safe), finite, ambiguous


@dataclass
class CleanResult:
    file: str
    columns: tuple[str, ...]  # Tier 1 columns, fixed order
    resolutions: dict[str, str]  # Tier 1 column -> resolution text
    ts_text: np.ndarray  # object (n,) unique stored seconds, ascending by naive second
    t_sec: np.ndarray  # int64 (n,)
    ticks: np.ndarray  # int32 (n, k); 0 where not observed
    valid: np.ndarray  # bool (n, k)
    reason: np.ndarray  # int8 (n, k) REASON_*
    flag: np.ndarray  # int8 (n, k) FLAG_* (all zero until apply_flags)
    group_size: np.ndarray  # int32 (n,) raw rows that share the second
    first_row: np.ndarray  # int64 (n,) lowest row ordinal of the group (bookkeeping representative)
    sec_disp: np.ndarray  # int8 (n,) disposition shared by the group's record (retained or conflict_*)
    row_ordinal: np.ndarray  # int64 (N,) every raw row, ascending
    row_sec: np.ndarray  # int32 (N,) index into the unique seconds
    row_disp: np.ndarray  # int8 (N,) one disposition per raw row
    stats: dict = field(default_factory=dict)

    @property
    def n_seconds(self) -> int:
        return int(self.t_sec.shape[0])

    @property
    def n_rows(self) -> int:
        return int(self.row_ordinal.shape[0])

    def digest(self) -> str:
        """SHA-256 over every output array in a fixed little-endian layout (rerun / shuffle comparison)."""
        h = hashlib.sha256()
        h.update("\x1f".join(self.columns).encode())
        h.update("\x1e".join(map(str, self.ts_text)).encode())
        for a, dt in (
            (self.t_sec, "<i8"),
            (self.ticks, "<i4"),
            (self.valid, "|u1"),
            (self.reason, "|i1"),
            (self.flag, "|i1"),
            (self.group_size, "<i4"),
            (self.first_row, "<i8"),
            (self.sec_disp, "|i1"),
            (self.row_ordinal, "<i8"),
            (self.row_sec, "<i4"),
            (self.row_disp, "|i1"),
        ):
            h.update(np.ascontiguousarray(a.astype(dt)).tobytes())
        return h.hexdigest()


# ----------------------------------------------------------------------------------------------------------------------
# group resolution through the protocol's reference implementation
# ----------------------------------------------------------------------------------------------------------------------
def _resolve_one(rows: list[RawRow], res_all: Mapping[str, Decimal], protocol: Protocol, tier1: Sequence[str]) -> dict:
    gr = resolve_group(rows, res_all, protocol)
    tie_reason = protocol["duplicates"]["tie_reason"]
    k = len(tier1)
    ticks = np.zeros(k, dtype=np.int32)
    valid = np.zeros(k, dtype=bool)
    reason = np.zeros(k, dtype=np.int8)
    for j, col in enumerate(tier1):
        cr = gr.cells[col]
        if cr.observed:
            ticks[j], valid[j] = to_ticks(cr.value, res_all[col]), True
        else:
            reason[j] = REASON_TIE if cr.reason == tie_reason else REASON_BLANK
    ties = [c for c, cr in gr.cells.items() if cr.reason == tie_reason]
    blanks = [c for c, cr in gr.cells.items() if not cr.observed and cr.reason is None]
    disps = {r: _DISP_INDEX[d] for r, d in gr.row_dispositions.items()}
    sec_disp = D_RETAINED if gr.group_kind in ("single", "exact_duplicate") else max(disps.values())
    return {
        "first_row": min(disps),
        "size": len(rows),
        "ticks": ticks,
        "valid": valid,
        "reason": reason,
        "ties": ties,
        "blanks": blanks,
        "row_disps": disps,
        "sec_disp": sec_disp,
        "kind": gr.group_kind,
    }


def _assemble(
    file: str,
    tier1: Sequence[str],
    res_t1: Mapping[str, str],
    single: dict | None,
    groups: list[tuple[str, dict]],
    stats: dict,
) -> CleanResult:
    k = len(tier1)
    parts_ts, parts_sec, parts_ticks, parts_valid, parts_reason = [], [], [], [], []
    parts_gs, parts_first, parts_sd = [], [], []
    ledger_rows, ledger_disp, ledger_cidx = [], [], []
    offset = 0
    if single is not None and len(single["ts"]):
        m = len(single["ts"])
        parts_ts.append(single["ts"])
        parts_sec.append(single["t_sec"])
        parts_ticks.append(single["ticks"])
        parts_valid.append(single["valid"])
        parts_reason.append(single["reason"])
        parts_gs.append(np.ones(m, dtype=np.int32))
        parts_first.append(single["rows"])
        parts_sd.append(np.full(m, D_RETAINED, dtype=np.int8))
        ledger_rows.append(single["rows"])
        ledger_disp.append(np.full(m, D_RETAINED, dtype=np.int8))
        ledger_cidx.append(np.arange(m, dtype=np.int64))
        offset = m
    if groups:
        texts = [t for t, _ in groups]
        recs = [g for _, g in groups]
        parts_ts.append(np.array(texts, dtype=object))
        parts_sec.append(naive_seconds(texts))
        parts_ticks.append(np.stack([g["ticks"] for g in recs]) if k else np.zeros((len(recs), 0), np.int32))
        parts_valid.append(np.stack([g["valid"] for g in recs]))
        parts_reason.append(np.stack([g["reason"] for g in recs]))
        parts_gs.append(np.array([g["size"] for g in recs], dtype=np.int32))
        parts_first.append(np.array([g["first_row"] for g in recs], dtype=np.int64))
        parts_sd.append(np.array([g["sec_disp"] for g in recs], dtype=np.int8))
        for gi, g in enumerate(recs):
            for r, d in sorted(g["row_disps"].items()):
                ledger_rows.append(np.array([r], dtype=np.int64))
                ledger_disp.append(np.array([d], dtype=np.int8))
                ledger_cidx.append(np.array([offset + gi], dtype=np.int64))
    if not parts_ts:
        raise CleaningError(f"{file}: no rows")
    ts = np.concatenate(parts_ts)
    t_sec = np.concatenate(parts_sec)
    order = np.argsort(t_sec, kind="stable")
    sorted_sec = t_sec[order]
    if sorted_sec.size > 1 and (np.diff(sorted_sec) == 0).any():
        raise CleaningError(f"{file}: two stored seconds share one naive second (timestamp texts not unique)")
    inv = np.empty_like(order)
    inv[order] = np.arange(order.size)
    rows_all = np.concatenate(ledger_rows)
    disp_all = np.concatenate(ledger_disp)
    sec_all = inv[np.concatenate(ledger_cidx)].astype(np.int32)
    lo = np.argsort(rows_all, kind="stable")
    rows_all, disp_all, sec_all = rows_all[lo], disp_all[lo], sec_all[lo]
    if rows_all.size > 1 and (np.diff(rows_all) == 0).any():
        raise CleaningError(f"{file}: duplicate source row ordinal")
    n = order.size
    ticks = np.concatenate(parts_ticks).astype(np.int32)[order] if k else np.zeros((n, 0), np.int32)
    return CleanResult(
        file=file,
        columns=tuple(tier1),
        resolutions=dict(res_t1),
        ts_text=ts[order],
        t_sec=sorted_sec,
        ticks=ticks,
        valid=np.concatenate(parts_valid)[order],
        reason=np.concatenate(parts_reason)[order],
        flag=np.zeros((n, k), dtype=np.int8),
        group_size=np.concatenate(parts_gs)[order],
        first_row=np.concatenate(parts_first)[order],
        sec_disp=np.concatenate(parts_sd)[order],
        row_ordinal=rows_all,
        row_sec=sec_all,
        row_disp=disp_all,
        stats=stats,
    )


def _group_stats(groups: list[tuple[str, dict]], tier1: Sequence[str]) -> dict:
    sizes: dict[int, int] = {}
    ties_by_col: dict[str, int] = {}
    t1 = set(tier1)
    ties_all = tier1_ties = blanks = 0
    groups_with_ties = groups_ties_only_outside = groups_with_tier1_ties = 0
    for _, g in groups:
        if g["size"] > 1:
            sizes[g["size"]] = sizes.get(g["size"], 0) + 1
        blanks += len(g["blanks"])
        ties_all += len(g["ties"])
        for c in g["ties"]:
            ties_by_col[c] = ties_by_col.get(c, 0) + 1
        in_t1 = sum(1 for c in g["ties"] if c in t1)
        tier1_ties += in_t1
        if g["ties"]:
            groups_with_ties += 1
            if in_t1:
                groups_with_tier1_ties += 1
            else:
                groups_ties_only_outside += 1
    return {
        "group_sizes": dict(sorted(sizes.items())),
        "cells_made_missing_all_columns": ties_all,
        "cells_made_missing_tier1": tier1_ties,
        "cells_made_missing_by_column": dict(sorted(ties_by_col.items())),
        "blank_cells_in_groups": blanks,
        "groups_with_ties": groups_with_ties,
        "groups_with_tier1_ties": groups_with_tier1_ties,
        "groups_with_ties_only_outside_tier1": groups_ties_only_outside,
    }


# ----------------------------------------------------------------------------------------------------------------------
# reference path
# ----------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RawRowIn:
    row_ordinal: int
    ts_text: str
    cells: Mapping[str, str]  # column -> source text ("" = blank)


def clean_rows(
    rows: Iterable[RawRowIn],
    all_columns: Sequence[str],
    resolutions: Mapping[str, Decimal],
    protocol: Protocol,
    *,
    file: str = "synthetic.csv",
    tier1: Sequence[str] = TIER1_COLUMNS,
) -> CleanResult:
    """Reference implementation: every timestamp group, including size 1, goes through ``resolve_group``."""
    by_ts: dict[str, list[RawRow]] = {}
    n_rows = 0
    for r in rows:
        missing = [c for c in all_columns if c not in r.cells]
        if missing:
            raise CleaningError(f"row {r.row_ordinal} lacks column(s) {missing[:3]}")
        by_ts.setdefault(r.ts_text, []).append(RawRow(r.row_ordinal, dict(r.cells)))
        n_rows += 1
    res_all = {c: resolutions[c] for c in all_columns}
    groups = [(ts, _resolve_one(g, res_all, protocol, tier1)) for ts, g in by_ts.items()]
    stats = {"raw_rows": n_rows, "unique_seconds": len(groups), "ambiguous_cells_all_columns": None}
    stats.update(_group_stats(groups, tier1))
    return _assemble(file, tier1, {c: str(res_all[c]) for c in tier1}, None, groups, stats)


# ----------------------------------------------------------------------------------------------------------------------
# production path over the Task 11 adapter reader
# ----------------------------------------------------------------------------------------------------------------------
def clean_file(
    reader,
    protocol: Protocol,
    *,
    tier1: Sequence[str] = TIER1_COLUMNS,
    index_built: bool = False,
    progress: Callable[[str], None] | None = None,
) -> CleanResult:
    """Clean one temperature/power CSV through ``AdapterReader`` (read-only). Aggregates are in ``result.stats``."""
    say = progress or (lambda m: None)
    if not index_built:
        reader.build_index()
    filename = reader.src.spec.filename
    all_cols = list(reader.columns)
    missing = [c for c in tier1 if c not in all_cols]
    if missing:
        raise CleaningError(f"{filename}: Tier 1 column(s) not in the file: {missing[:3]}")
    res_all = {c: protocol.resolution(c, filename) for c in all_cols}
    scale = np.array([float(scale_for(res_all[c])) for c in all_cols])
    t1_idx = np.array([all_cols.index(c) for c in tier1], dtype=np.int64)

    s_ts, s_rows, s_ticks, s_valid, s_reason = [], [], [], [], []
    pending: dict[str, list[RawRow]] = {}
    expected_size: dict[str, int] = {}
    blanks_all = ambiguous_all = rows_total = 0
    for frame in reader.iter_frames(all_cols, include_text=True):
        rows = frame["_src_row"].to_numpy(dtype=np.int64)
        ts = frame["_ts_text"].to_numpy(dtype=object)
        dsize = frame["_dup_size"].to_numpy(dtype=np.int64)
        vals = frame[all_cols].to_numpy(dtype=np.float64)
        ticks_f, finite, amb = ticks_from_floats(vals, scale)
        blanks_all += int(np.isnan(vals).sum())
        ambiguous_all += int(amb.sum())
        if finite.any() and np.abs(ticks_f[finite]).max() > 2**31 - 1:
            raise CleaningError(f"{filename}: tick overflow")
        rows_total += len(rows)
        grp = dsize > 1
        sng = ~grp
        if sng.any():
            tk = ticks_f[sng][:, t1_idx]
            vd = finite[sng][:, t1_idx]
            am = amb[sng][:, t1_idx]
            if am.any():  # near-tie cells: exact Decimal rounding of the SOURCE TEXT
                s_rows_chunk = np.flatnonzero(sng)
                text_cache: dict[int, np.ndarray] = {}
                for r, c in zip(*np.nonzero(am), strict=True):
                    c = int(c)
                    if c not in text_cache:
                        text_cache[c] = frame[f"{tier1[c]}__text"].to_numpy(dtype=object)
                    tk[int(r), c] = to_ticks(str(text_cache[c][int(s_rows_chunk[int(r)])]), res_all[tier1[c]])
            rs = np.where(vd, REASON_NONE, REASON_BLANK).astype(np.int8)
            s_ts.append(ts[sng])
            s_rows.append(rows[sng])
            s_ticks.append(np.where(vd, tk, 0).astype(np.int32))
            s_valid.append(vd)
            s_reason.append(rs)
        if grp.any():
            texts = {c: frame[f"{c}__text"].to_numpy(dtype=object) for c in all_cols}
            for i in np.flatnonzero(grp):
                t = str(ts[i])
                cells = {c: str(texts[c][i]) for c in all_cols}
                pending.setdefault(t, []).append(RawRow(int(rows[i]), cells))
                expected_size[t] = int(dsize[i])
        say(f"{filename}: {rows_total} rows read")
    for t, rs_ in pending.items():
        if len(rs_) != expected_size[t]:
            raise CleaningError(f"{filename}: group {t!r} has {len(rs_)} rows but the index says {expected_size[t]}")
    groups = [(t, _resolve_one(rs_, res_all, protocol, tier1)) for t, rs_ in pending.items()]
    single = None
    if s_ts:
        ts_cat = np.concatenate(s_ts)
        single = {
            "ts": ts_cat,
            "t_sec": naive_seconds(ts_cat),
            "rows": np.concatenate(s_rows),
            "ticks": np.concatenate(s_ticks),
            "valid": np.concatenate(s_valid),
            "reason": np.concatenate(s_reason),
        }
    n_single = 0 if single is None else len(single["ts"])
    stats = {
        "raw_rows": rows_total,
        "unique_seconds": n_single + len(groups),
        "ambiguous_cells_all_columns": ambiguous_all,
        "blank_cells_all_columns": blanks_all,
    }
    stats.update(_group_stats(groups, tier1))
    return _assemble(filename, tier1, {c: str(res_all[c]) for c in tier1}, single, groups, stats)


__all__ = [
    "CleanResult",
    "RawRowIn",
    "clean_file",
    "clean_rows",
    "naive_seconds",
    "ticks_from_floats",
    "D_CONFLICT_MISSING",
]
