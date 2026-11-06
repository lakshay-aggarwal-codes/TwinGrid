"""Alignment: the ONLY place where two series meet (e.g. measured L1/L2 against simulated L3).

Strategies (named, explicit): ``exact``, ``nearest`` (explicit tolerance), ``backward_asof`` (explicit tolerance, or an
explicit ``allow_unbounded``), ``bucket`` (reduction only with an approved reducer).

Rules enforced here:
  * every TARGET row is retained, in order; each gets ``align_status`` matched | unmatched | ambiguous and a reason;
  * nothing is interpolated or invented: unmatched and ambiguous rows have NaN source values, and the candidate source
    rows are listed in ``align_source_rows`` (conflicting duplicates are preserved, never merged);
  * no row-index joins: matching uses the time axis only;
  * measured and simulated values live in separate namespaces (``target__*`` / ``source__*``); a series keeps the
    layer/provenance it was created with (L1 measured, L2 derived, L3 simulated) and cannot be relabelled;
  * naive wall-clock series must share a declared clock id (or carry an explicit equivalence note); a naive series and a
    tz-aware series are never assumed to share a clock; tz-aware input is refused (needs an approved TimeMapping);
  * two elapsed-time series with DIFFERENT clock ids need an explicit relationship: a declared ``source_offset_s`` (0.0 is a
    deliberate statement that both clocks start together, never a default) or the same stated ``origin_text`` on both;
    the same clock id with conflicting origins is refused;
  * tolerance, offset and bucket width must be finite numbers (NaN and infinity are rejected);
  * bucket reduction (count, min, max, mean only, and only when approved) is never applied to rows that share a source
    timestamp: such a bucket is ``ambiguous``, its row ids are listed, and nothing is aggregated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

from .config import KNOWN_REDUCERS
from .errors import AlignmentError, ClockMismatchError, PolicyNotApproved
from .provenance import DerivationRecord, row_summary
from .timeparse import NAT_NS
from .vocabulary import AlignmentStrategy, AlignStatus, Layer, Provenance, TimeBasis

_LAYER_PROVENANCE = {
    Layer.L1_OBSERVED: Provenance.MEASURED,
    Layer.L2_DERIVED: Provenance.DERIVED,
    Layer.L3_SIMULATED: Provenance.SIMULATED,
}
T_COL = "_t_ns"
MAX_ABS_SECONDS = 9.0e9  # ~285 years: beyond this the int64 nanosecond axis would overflow


def seconds_to_ns(values) -> np.ndarray:
    """int64 nanoseconds; NaN, infinity and out-of-range values become NAT_NS (an invalid time), never garbage."""
    secs = np.asarray(values, dtype=float)
    out = np.full(secs.shape, NAT_NS, dtype=np.int64)
    ok = np.isfinite(secs) & (np.abs(secs) < MAX_ABS_SECONDS)
    out[ok] = np.round(secs[ok] * 1e9).astype(np.int64)
    return out


@dataclass(frozen=True)
class TimedSeries:
    name: str
    layer: Layer
    provenance: Provenance
    time_basis: TimeBasis
    clock_id: str
    frame: pd.DataFrame
    time_col: str = T_COL
    row_col: str = "_src_row"
    origin_text: str | None = None

    def __post_init__(self) -> None:
        expected = _LAYER_PROVENANCE.get(self.layer)
        if expected is None:
            raise AlignmentError(f"layer {self.layer!r} cannot be aligned (only L1, L2, L3)")
        if self.provenance is not expected:
            raise AlignmentError(
                f"{self.layer.value} series must carry provenance {expected.value!r}, not {self.provenance.value!r}: provenance is never relabelled"
            )
        for col in (self.time_col, self.row_col):
            if col not in self.frame.columns:
                raise AlignmentError(f"series {self.name!r} has no column {col!r}")

    @classmethod
    def from_observations(
        cls,
        frame: pd.DataFrame,
        *,
        layer: Layer,
        basis: TimeBasis,
        clock_id: str,
        name: str,
        origin_text: str | None = None,
    ) -> TimedSeries:
        """Build from an L1/L2 frame (annotated by the reader): the time axis is ``_ts_ns`` (naive) or ``_elapsed_s``."""
        if basis is TimeBasis.TZ_AWARE:
            raise ClockMismatchError(
                "tz-aware series need an approved, documentary TimeMapping; none exists in Phase 2"
            )
        if layer is Layer.L3_SIMULATED:
            raise AlignmentError("use TimedSeries.from_simulated for L3")
        src = "_ts_ns" if basis is TimeBasis.NAIVE_WALLCLOCK else "_elapsed_s"
        if src not in frame.columns:
            raise AlignmentError(f"frame has no {src!r} column; build it from an ObservationStream")
        t = frame[src].to_numpy()
        if basis is TimeBasis.ELAPSED:
            t = seconds_to_ns(t)
        out = frame.copy()
        out[T_COL] = np.asarray(t, dtype=np.int64)
        return cls(name, layer, _LAYER_PROVENANCE[layer], basis, clock_id, out, origin_text=origin_text)

    @classmethod
    def from_simulated(
        cls,
        frame: pd.DataFrame,
        *,
        elapsed_s_col: str,
        name: str,
        clock_id: str = "twingrid_simulation",
        origin_text: str | None = None,
    ) -> TimedSeries:
        """Container for an L3 simulated series (Phase 2 defines the container only; no simulator is involved)."""
        if elapsed_s_col not in frame.columns:
            raise AlignmentError(f"no column {elapsed_s_col!r}")
        out = frame.copy()
        out[T_COL] = seconds_to_ns(out[elapsed_s_col].to_numpy(dtype=float))
        if "_sim_row" not in out.columns:
            out["_sim_row"] = np.arange(1, len(out) + 1, dtype=np.int64)
        return cls(
            name,
            Layer.L3_SIMULATED,
            Provenance.SIMULATED,
            TimeBasis.ELAPSED,
            clock_id,
            out,
            row_col="_sim_row",
            origin_text=origin_text,
        )


@dataclass(frozen=True)
class AlignmentSpec:
    strategy: AlignmentStrategy
    tolerance_s: float | None = None
    allow_unbounded: bool = False
    source_offset_s: float | None = (
        None  # None = not declared; elapsed series on different clocks then need a shared origin_text
    )
    bucket_width_s: float | None = None
    reducer: str | None = None
    approved_reducers: tuple[str, ...] = ()
    clock_equivalence_note: str | None = None
    source_columns: tuple[str, ...] | None = None

    @property
    def effective_offset_s(self) -> float:
        return 0.0 if self.source_offset_s is None else float(self.source_offset_s)

    def validate(self) -> None:
        for name, value in (
            ("tolerance_s", self.tolerance_s),
            ("source_offset_s", self.source_offset_s),
            ("bucket_width_s", self.bucket_width_s),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise AlignmentError(
                    f"{name} must be a finite number (NaN, infinity and non-numbers are rejected), got {value!r}"
                )
        if not isinstance(self.allow_unbounded, bool):
            raise AlignmentError("allow_unbounded must be True or False")
        if self.source_offset_s is not None and abs(self.source_offset_s) >= MAX_ABS_SECONDS:
            raise AlignmentError("source_offset_s is out of range")
        s = self.strategy
        if s is AlignmentStrategy.NEAREST and (self.tolerance_s is None or self.tolerance_s < 0):
            raise AlignmentError("nearest alignment requires an explicit tolerance_s >= 0")
        if s is AlignmentStrategy.BACKWARD_ASOF and self.tolerance_s is None and not self.allow_unbounded:
            raise AlignmentError(
                "backward_asof requires an explicit tolerance_s, or allow_unbounded=True to accept any age"
            )
        if self.tolerance_s is not None and self.tolerance_s < 0:
            raise AlignmentError("tolerance_s must be >= 0")
        if s is AlignmentStrategy.BUCKET:
            if self.bucket_width_s is None or self.bucket_width_s <= 0:
                raise AlignmentError("bucket alignment requires bucket_width_s > 0")
            if self.reducer not in KNOWN_REDUCERS:
                raise AlignmentError(f"bucket alignment requires a reducer from {KNOWN_REDUCERS}; got {self.reducer!r}")
            if self.reducer not in self.approved_reducers:
                raise PolicyNotApproved(
                    f"bucket reducer {self.reducer!r} is not approved (approved: {list(self.approved_reducers)})"
                )
            unknown = [r for r in self.approved_reducers if r not in KNOWN_REDUCERS]
            if unknown:
                raise AlignmentError(
                    f"approved_reducers contains reducers that do not exist: {unknown}; only {KNOWN_REDUCERS} are authorised"
                )


@dataclass
class AlignmentResult:
    frame: pd.DataFrame
    spec: AlignmentSpec
    target_name: str
    source_name: str
    target_layer: str
    source_layer: str
    provenance: DerivationRecord
    clock: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        f = self.frame
        return {
            "strategy": self.spec.strategy.value,
            "n_target_rows": int(len(f)),
            "by_status": {s.value: int((f["align_status"] == s.value).sum()) for s in AlignStatus},
            "by_reason": {str(k): int(v) for k, v in f["align_reason"].value_counts().items()},
            "clock": self.clock,
        }


def _check_clocks(t: TimedSeries, s: TimedSeries, spec: AlignmentSpec) -> dict[str, Any]:
    if TimeBasis.TZ_AWARE in (t.time_basis, s.time_basis):
        raise ClockMismatchError(
            "tz-aware series cannot be aligned in Phase 2: an approved, documentary TimeMapping is required"
        )
    if t.time_basis is not s.time_basis:
        raise ClockMismatchError(
            f"time bases differ ({t.time_basis.value} vs {s.time_basis.value}); no shared clock is assumed"
        )
    info: dict[str, Any] = {
        "time_basis": t.time_basis.value,
        "target_clock_id": t.clock_id,
        "source_clock_id": s.clock_id,
        "target_origin": t.origin_text,
        "source_origin": s.origin_text,
        "source_offset_declared": spec.source_offset_s is not None,
        "source_offset_s": spec.effective_offset_s,
        "clock_equivalence_note": spec.clock_equivalence_note,
        "offset_basis": None,
    }
    if t.time_basis is TimeBasis.NAIVE_WALLCLOCK:
        if spec.effective_offset_s != 0:
            raise AlignmentError(
                "a clock offset between naive wall clocks is a time mapping and needs approval; use elapsed-time alignment with a declared offset"
            )
        if t.clock_id != s.clock_id and not spec.clock_equivalence_note:
            raise ClockMismatchError(
                f"naive clocks {t.clock_id!r} and {s.clock_id!r} are not declared equivalent; pass clock_equivalence_note to record that decision"
            )
        info["offset_basis"] = "same_clock_id" if t.clock_id == s.clock_id else "declared_equivalence_note"
        return info
    # ELAPSED: each series counts seconds from its OWN origin, so the relationship between the origins must be stated.
    both_origins = t.origin_text is not None and s.origin_text is not None
    if t.clock_id == s.clock_id:
        if both_origins and t.origin_text != s.origin_text:
            raise ClockMismatchError(
                f"both series claim clock {t.clock_id!r} but their origins differ ({t.origin_text!r} vs {s.origin_text!r}); give them different clock ids and declare source_offset_s"
            )
        info["offset_basis"] = "declared_offset" if spec.source_offset_s is not None else "same_clock_id"
    elif spec.source_offset_s is not None:
        info["offset_basis"] = "declared_offset"
    elif both_origins and t.origin_text == s.origin_text:
        info["offset_basis"] = "shared_origin_text"
    else:
        raise ClockMismatchError(
            f"elapsed clocks {t.clock_id!r} and {s.clock_id!r} are different and no relationship is stated: declare source_offset_s "
            "(0.0 is an explicit claim that both start together) or give both series the same origin_text"
        )
    return info


def _value_columns(source: TimedSeries, spec: AlignmentSpec) -> list[str]:
    cols = (
        list(spec.source_columns)
        if spec.source_columns is not None
        else [c for c in source.frame.columns if not c.startswith("_")]
    )
    bad = [c for c in cols if c not in source.frame.columns]
    if bad:
        raise AlignmentError(f"source columns not found: {bad}")
    if spec.strategy is AlignmentStrategy.BUCKET:
        non_num = [c for c in cols if not pd.api.types.is_numeric_dtype(source.frame[c])]
        if non_num:
            raise AlignmentError(f"bucket reduction needs numeric columns; not numeric: {non_num}")
    return cols


def _reduce(name: str, values: np.ndarray) -> float:
    """count / min / max / mean over the non-NaN values. These four are the only authorised reducers."""
    if name not in KNOWN_REDUCERS:
        raise AlignmentError(f"reducer {name!r} does not exist; authorised: {KNOWN_REDUCERS}")
    ok = values[~np.isnan(values)]
    if name == "count":
        return float(ok.size)
    if ok.size == 0:
        return float("nan")
    return float({"min": ok.min, "max": ok.max, "mean": ok.mean}[name]())


def align(target: TimedSeries, source: TimedSeries, spec: AlignmentSpec) -> AlignmentResult:
    """Align ``source`` onto ``target``. Output has exactly one row per target row, in target order."""
    spec.validate()
    clock = _check_clocks(target, source, spec)
    cols = _value_columns(source, spec)
    n = len(target.frame)
    t = target.frame[target.time_col].to_numpy(dtype=np.int64)
    s_all = source.frame[source.time_col].to_numpy(dtype=np.int64)
    offset = int(round(spec.effective_offset_s * 1e9))
    valid = np.flatnonzero(s_all != NAT_NS)
    order = np.argsort(s_all[valid], kind="stable")
    spos = valid[order]  # positions in source.frame, time-sorted (stable)
    st = s_all[spos] + offset
    srow = source.frame[source.row_col].to_numpy()
    conflict = (
        source.frame["_dup_conflict"].to_numpy()
        if "_dup_conflict" in source.frame.columns
        else np.zeros(len(source.frame), dtype=bool)
    )
    tol = None if spec.tolerance_s is None else int(round(spec.tolerance_s * 1e9))

    status = np.full(n, AlignStatus.UNMATCHED.value, dtype=object)
    reason = np.full(n, "no_candidate", dtype=object)
    ncand = np.zeros(n, dtype=np.int64)
    rows_txt = np.full(n, "", dtype=object)
    dt_s = np.full(n, np.nan)
    pick = np.full(n, -1, dtype=np.int64)  # source frame position of the single matched row
    nconf = np.zeros(n, dtype=np.int64)
    bucket_vals = {c: np.full(n, np.nan) for c in cols} if spec.strategy is AlignmentStrategy.BUCKET else {}
    used: set[int] = set()

    def finish(i: int, lo: int, hi: int, matched_time: int | None) -> None:
        cand = spos[lo:hi]
        ncand[i] = cand.size
        rows_txt[i] = ";".join(str(srow[p]) for p in cand)
        used.update(int(srow[p]) for p in cand)
        if cand.size == 1:
            status[i], reason[i], pick[i] = AlignStatus.MATCHED.value, "", cand[0]
            dt_s[i] = (matched_time - t[i]) / 1e9 if matched_time is not None else np.nan
        else:
            status[i] = AlignStatus.AMBIGUOUS.value
            reason[i] = "conflicting_duplicates" if conflict[cand].any() else "multiple_candidates"
            dt_s[i] = (matched_time - t[i]) / 1e9 if matched_time is not None else np.nan

    for i in range(n):
        if t[i] == NAT_NS:
            reason[i] = "target_time_invalid"
            continue
        if st.size == 0:
            reason[i] = "no_source_rows"
            continue
        ti = int(t[i])
        if spec.strategy is AlignmentStrategy.EXACT:
            lo, hi = int(np.searchsorted(st, ti, "left")), int(np.searchsorted(st, ti, "right"))
            if hi > lo:
                finish(i, lo, hi, ti)
        elif spec.strategy is AlignmentStrategy.NEAREST:
            j = int(np.searchsorted(st, ti, "left"))
            right = int(st[j]) if j < st.size else None
            left = int(st[j - 1]) if j > 0 else None
            dr = None if right is None else right - ti
            dl = None if left is None else ti - left
            best = min(d for d in (dl, dr) if d is not None)
            if best > tol:
                reason[i] = "outside_tolerance"
                continue
            times = sorted({tm for tm, d in ((left, dl), (right, dr)) if d == best})
            lo = int(np.searchsorted(st, times[0], "left"))
            hi = int(np.searchsorted(st, times[-1], "right"))
            if len(times) > 1:  # equally near on both sides: both candidate times are listed, none is chosen
                lo2, hi2 = int(np.searchsorted(st, times[0], "left")), int(np.searchsorted(st, times[0], "right"))
                lo3, hi3 = int(np.searchsorted(st, times[1], "left")), int(np.searchsorted(st, times[1], "right"))
                cand_idx = list(range(lo2, hi2)) + list(range(lo3, hi3))
                ncand[i] = len(cand_idx)
                rows_txt[i] = ";".join(str(srow[spos[k]]) for k in cand_idx)
                used.update(int(srow[spos[k]]) for k in cand_idx)
                status[i], reason[i] = AlignStatus.AMBIGUOUS.value, "equidistant_candidates"
            else:
                finish(i, lo, hi, times[0])
        elif spec.strategy is AlignmentStrategy.BACKWARD_ASOF:
            k = int(np.searchsorted(st, ti, "right")) - 1
            if k < 0:
                continue
            tm = int(st[k])
            if tol is not None and ti - tm > tol:
                reason[i] = "outside_tolerance"
                continue
            finish(i, int(np.searchsorted(st, tm, "left")), k + 1, tm)
        else:  # BUCKET: trailing window (t - width, t]
            width = int(round(spec.bucket_width_s * 1e9))
            lo, hi = int(np.searchsorted(st, ti - width, "right")), int(np.searchsorted(st, ti, "right"))
            if hi <= lo:
                continue
            cand = spos[lo:hi]
            ncand[i] = cand.size
            rows_txt[i] = ";".join(str(srow[p]) for p in cand)
            used.update(int(srow[p]) for p in cand)
            nconf[i] = int(conflict[cand].sum())
            if cand.size > 1 and bool(np.any(st[lo + 1 : hi] == st[lo : hi - 1])):
                # Rows that share a source timestamp are never aggregated: the bucket is ambiguous, ids are kept, values stay NaN.
                status[i] = AlignStatus.AMBIGUOUS.value
                reason[i] = "conflicting_duplicates" if conflict[cand].any() else "duplicate_source_timestamps"
                continue
            status[i], reason[i] = AlignStatus.MATCHED.value, ""
            for c in cols:
                bucket_vals[c][i] = _reduce(spec.reducer, source.frame[c].to_numpy(dtype=float)[cand])

    out = target.frame.reset_index(drop=True).add_prefix("target__")
    for c in cols:
        if spec.strategy is AlignmentStrategy.BUCKET:
            out[f"source__{c}"] = bucket_vals[c]
            continue
        col = source.frame[c].to_numpy()
        if pd.api.types.is_numeric_dtype(source.frame[c]):
            vals = np.full(n, np.nan)
        else:
            vals = np.full(n, None, dtype=object)
        m = pick >= 0
        vals[m] = col[pick[m]]
        out[f"source__{c}"] = vals
    out["align_status"], out["align_reason"] = status, reason
    out["align_n_candidates"], out["align_source_rows"], out["align_dt_s"] = ncand, rows_txt, dt_s
    if spec.strategy is AlignmentStrategy.BUCKET:
        out["align_n_conflict_rows"] = nconf
    out.attrs.update(
        {"target_layer": target.layer.value, "source_layer": source.layer.value, "strategy": spec.strategy.value}
    )

    config = {
        "strategy": spec.strategy.value,
        "tolerance_s": spec.tolerance_s,
        "allow_unbounded": spec.allow_unbounded,
        "source_offset_s": spec.source_offset_s,
        "effective_source_offset_s": spec.effective_offset_s,
        "bucket_width_s": spec.bucket_width_s,
        "reducer": spec.reducer,
        "approved_reducers": list(spec.approved_reducers),
        "source_columns": cols,
        "clock": clock,
        "n_source_rows_with_invalid_time": int(len(s_all) - valid.size),
        "source_sorted_internally_by_time": True,
    }
    record = DerivationRecord(
        operation="alignment",
        policy_id=f"align_{spec.strategy.value}",
        transformation=(
            f"align source {source.name!r} ({source.layer.value}, {source.provenance.value}) onto target {target.name!r} "
            f"({target.layer.value}, {target.provenance.value}); all target rows retained; no interpolation; separate namespaces"
        ),
        source_files=(source.name,),
        source_rows={
            "source": row_summary(sorted(used)),
            "target": row_summary(target.frame[target.row_col].to_numpy()),
        },
        config=config,
        exclusions={
            "n_excluded": 0,
            "note": "all target rows retained; unmatched/ambiguous rows are flagged, not dropped",
        },
        output={
            "layer": "aligned",
            "target_layer": target.layer.value,
            "target_provenance": target.provenance.value,
            "source_layer": source.layer.value,
            "source_provenance": source.provenance.value,
            "n_rows": int(n),
            "columns": list(out.columns),
        },
    )
    return AlignmentResult(out, spec, target.name, source.name, target.layer.value, source.layer.value, record, clock)
