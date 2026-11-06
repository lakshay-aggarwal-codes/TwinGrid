"""TimeIndex: the global, per-row annotation of one source file, built in the reader's FIRST pass.

Row identity: ``_src_row`` is the 1-based ordinal of the non-blank DATA line (header excluded), the same convention
as the Phase 1 row count. It is stable: it never changes with filtering, sorting or chunking.

Everything global (ordering, deltas, duplicate groups, conflicts) is computed in ``finalize()`` over the whole file, so
a duplicate group that straddles a chunk boundary is found exactly like one inside a chunk.

POPULATION PATTERNS: for every row the exact set of populated measurement columns is its signature; ``pattern_census()``
lists each distinct signature with its row count and first/last source row and timestamp. It is purely descriptive: it
does not infer simultaneity, a shared acquisition schedule, or why cells are empty. Each row keeps its ``_pattern_id``.

CONTENT DIGESTS: pass 1 stores, per chunk and per non-timestamp column, a SHA-256 of the raw cell text. Pass 2 recomputes
them for the columns it reads, so a changed value is detected even when the timestamp and the cell length are unchanged.
Columns that pass 2 does not read are not verified by it (``AauCsvReader.verify_integrity`` verifies all of them).

Duplicate CONFLICT = the raw text of at least one non-timestamp column differs between rows of the same group (compared
as written, so "21.30" vs "21.3" counts as a difference). Nothing is dropped, averaged or reordered here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .errors import ReaderError
from .timeparse import ERROR, NAT_NS, OK, STATUS_NAMES, TZ_SUFFIX, ns_to_text, parse_naive_timestamps
from .vocabulary import Completeness, OrderFlag

_ORDER_CODES = {OrderFlag.FIRST: 0, OrderFlag.OK: 1, OrderFlag.BACKWARD: 2, OrderFlag.UNPARSED: 3}
ORDER_NAMES = {v: k.value for k, v in _ORDER_CODES.items()}


@dataclass
class TimeIndex:
    file_key: str
    timestamp_column: str
    ts_text: np.ndarray  # object: original text, never altered
    ts_ns: np.ndarray  # int64 (NAT_NS where not parsed): naive wall clock "as written"
    ts_status: np.ndarray  # int8: 0 ok, 1 empty, 2 parse_error
    elapsed_s: np.ndarray  # float64 seconds since the first parseable timestamp in SOURCE order (NaN if unparsed)
    delta_s: np.ndarray  # float64 seconds since the previous parseable row in source order (NaN for first/unparsed)
    order_flag: np.ndarray  # int8 code, see ORDER_NAMES
    dup_group: np.ndarray  # int32: global duplicate group id (-1 = none), numbered by first appearance in source order
    dup_size: np.ndarray  # int32: size of the row's group (0 = none)
    seq_in_group: np.ndarray  # int32: 1-based position inside the group in source order (0 = none)
    dup_conflict: np.ndarray  # bool: the row's group has differing values
    n_present: np.ndarray  # int16: populated measurement fields in the row
    n_expected: int
    measurement_columns: tuple[str, ...]
    missing_by_column: dict[str, int]
    pattern_id: np.ndarray  # int32: id of the row's population pattern (numbered by first appearance in source order)
    pattern_columns: list[tuple[str, ...]]  # pattern id -> the populated measurement columns (file column order)
    chunk_ranges: list[tuple[int, int]]  # pass-1 chunk boundaries as 1-based inclusive src-row ranges
    chunk_digests: list[dict[str, str]]  # per chunk: non-timestamp column -> SHA-256 of that column's raw cell text
    timestamp_state: str = "naive_unspecified"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        return int(self.ts_ns.shape[0])

    # -- completeness --------------------------------------------------------------------------------------------
    def completeness(self) -> np.ndarray:
        """Object array of Completeness values per row (FULL / PARTIAL / EMPTY)."""
        out = np.full(self.n_rows, Completeness.PARTIAL.value, dtype=object)
        out[self.n_present == self.n_expected] = Completeness.FULL.value
        out[self.n_present == 0] = Completeness.EMPTY.value
        return out

    def completeness_counts(self) -> dict[str, int]:
        comp = self.completeness()
        return {c.value: int((comp == c.value).sum()) for c in Completeness}

    # -- row access ----------------------------------------------------------------------------------------------
    def src_rows(self) -> np.ndarray:
        return np.arange(1, self.n_rows + 1, dtype=np.int64)

    def slice_annotations(self, start_row: int, stop_row: int) -> pd.DataFrame:
        """Annotation columns for src rows [start_row, stop_row] (1-based, inclusive)."""
        sl = slice(start_row - 1, stop_row)
        comp = self.completeness()[sl]
        return pd.DataFrame(
            {
                "_src_row": self.src_rows()[sl],
                "_ts_text": self.ts_text[sl],
                "_ts_status": [STATUS_NAMES[int(c)] for c in self.ts_status[sl]],
                "_ts_ns": self.ts_ns[sl],
                "_elapsed_s": self.elapsed_s[sl],
                "_delta_s": self.delta_s[sl],
                "_order_flag": [ORDER_NAMES[int(c)] for c in self.order_flag[sl]],
                "_dup_group": self.dup_group[sl],
                "_dup_size": self.dup_size[sl],
                "_seq_in_group": self.seq_in_group[sl],
                "_dup_conflict": self.dup_conflict[sl],
                "_completeness": comp,
                "_pattern_id": self.pattern_id[sl],
            }
        )

    # -- population patterns -------------------------------------------------------------------------------------
    def pattern_rows(self, pattern_id: int) -> np.ndarray:
        """1-based src rows that have the given population pattern, in source order."""
        return np.flatnonzero(self.pattern_id == pattern_id) + 1

    def pattern_census(self, window_ns: tuple[int, int] | None = None) -> list[dict[str, Any]]:
        """One entry per distinct populated-column signature, in order of first appearance. Descriptive only."""
        ok = self.ts_status == OK
        out = []
        for pid, cols in enumerate(self.pattern_columns):
            rows = self.pattern_rows(pid)
            if rows.size == 0:
                continue
            entry: dict[str, Any] = {
                "pattern_id": pid,
                "populated_columns": list(cols),
                "n_populated_columns": len(cols),
                "n_rows": int(rows.size),
                "first_src_row": int(rows[0]),
                "last_src_row": int(rows[-1]),
                "first_timestamp_text": str(self.ts_text[rows[0] - 1]),
                "last_timestamp_text": str(self.ts_text[rows[-1] - 1]),
            }
            if window_ns is not None:
                lo, hi = window_ns
                inside = ok[rows - 1] & (self.ts_ns[rows - 1] >= lo) & (self.ts_ns[rows - 1] <= hi)
                entry["n_rows_in_window"] = int(inside.sum())
            out.append(entry)
        return out

    def to_frame(self) -> pd.DataFrame:
        """The full annotation table (one row per source row; no measurement values). Small enough to materialise."""
        return self.slice_annotations(1, self.n_rows) if self.n_rows else self.slice_annotations(1, 0)

    def duplicate_rows_frame(self) -> pd.DataFrame:
        frame = self.to_frame()
        return frame[frame["_dup_group"] >= 0].reset_index(drop=True)

    # -- summary -------------------------------------------------------------------------------------------------
    def summary(self, window_ns: tuple[int, int] | None = None) -> dict[str, Any]:
        ok = self.ts_status == OK
        flags = self.order_flag
        deltas = self.delta_s[~np.isnan(self.delta_s)]
        uniq, counts = np.unique(deltas, return_counts=True)
        dup_mask = self.dup_group >= 0
        group_ids = np.unique(self.dup_group[dup_mask])
        sizes = [int((self.dup_group == g).sum()) for g in group_ids]
        conflicting = int(len({int(g) for g in self.dup_group[dup_mask & self.dup_conflict]}))
        out: dict[str, Any] = {
            "file_key": self.file_key,
            "timestamp_state": self.timestamp_state,
            "n_rows": self.n_rows,
            "n_timestamp_ok": int(ok.sum()),
            "n_timestamp_empty": int((self.ts_status == 1).sum()),
            "n_timestamp_parse_errors": int((self.ts_status == ERROR).sum()),
            "n_timestamp_tz_suffix_rejected": int((self.ts_status == TZ_SUFFIX).sum()),
            "first_row_text": str(self.ts_text[0]) if self.n_rows else None,
            "last_row_text": str(self.ts_text[-1]) if self.n_rows else None,
            "min_parsed": ns_to_text(self.ts_ns[ok].min()) if ok.any() else None,
            "max_parsed": ns_to_text(self.ts_ns[ok].max()) if ok.any() else None,
            "n_ordering_violations": int((flags == _ORDER_CODES[OrderFlag.BACKWARD]).sum()),
            "delta_seconds_counts": {repr(float(u)): int(c) for u, c in zip(uniq, counts, strict=True)},
            "n_duplicate_groups": int(group_ids.size),
            "n_duplicate_rows": int(dup_mask.sum()),
            "duplicate_group_size_histogram": {str(s): sizes.count(s) for s in sorted(set(sizes))},
            "n_conflicting_duplicate_groups": conflicting,
            "n_expected_measurement_fields": self.n_expected,
            "completeness_counts": self.completeness_counts(),
            "n_missing_cells": int(sum(self.missing_by_column.values())),
            "missing_by_column": {k: v for k, v in self.missing_by_column.items() if v},
            "n_population_patterns": len(self.pattern_census()),
            "population_patterns": self.pattern_census(window_ns),
        }
        if window_ns is not None:
            lo, hi = window_ns
            inside = ok & (self.ts_ns >= lo) & (self.ts_ns <= hi)
            out["in_window_rows"] = int(inside.sum())
        return out


def column_digest(cells: list[str]) -> str:
    """SHA-256 of a column's raw cell text for one chunk (order-sensitive; deterministic across platforms/versions)."""
    return hashlib.sha256((str(len(cells)) + "\x1f" + "\x1f".join(cells)).encode("utf-8", "surrogatepass")).hexdigest()


class TimeIndexBuilder:
    """Accumulates chunks (all columns as raw text) and builds the global TimeIndex in ``finalize()``."""

    def __init__(
        self,
        file_key: str,
        timestamp_column: str,
        measurement_columns: tuple[str, ...],
        formats: tuple[str, ...],
        *,
        strip: bool = True,
        na_values: tuple[str, ...] = ("",),
    ):
        self.file_key, self.ts_col = file_key, timestamp_column
        self.meas = tuple(measurement_columns)
        self.formats, self.strip, self.na = tuple(formats), strip, set(na_values)
        self._text: list[np.ndarray] = []
        self._ns: list[np.ndarray] = []
        self._status: list[np.ndarray] = []
        self._hash: list[np.ndarray] = []
        self._present: list[np.ndarray] = []
        self._missing = dict.fromkeys(self.meas, 0)
        self._rows = 0
        self._pattern: list[np.ndarray] = []
        self._pattern_keys: dict[bytes, int] = {}
        self._pattern_cols: list[tuple[str, ...]] = []
        self._ranges: list[tuple[int, int]] = []
        self._digests: list[dict[str, str]] = []

    def add_chunk(self, chunk: pd.DataFrame) -> None:
        if self.ts_col not in chunk.columns:
            raise ReaderError(f"timestamp column {self.ts_col!r} missing from a chunk")
        text = chunk[self.ts_col]
        ns, status = parse_naive_timestamps(text, self.formats, self.strip)
        others = chunk.drop(columns=[self.ts_col])
        row_hash = (
            pd.util.hash_pandas_object(others, index=False).to_numpy(dtype=np.uint64)
            if others.shape[1]
            else np.zeros(len(chunk), dtype=np.uint64)
        )
        populated = np.zeros((len(chunk), len(self.meas)), dtype=bool)
        for j, col in enumerate(self.meas):
            cells = chunk[col].astype(object).map(lambda v: "" if v is None else str(v))
            cells = cells.str.strip() if self.strip else cells
            missing = cells.isin(self.na).to_numpy()
            self._missing[col] += int(missing.sum())
            populated[:, j] = ~missing
        present = populated.sum(axis=1).astype(np.int16)
        packed = np.packbits(populated, axis=1)
        ids = np.empty(len(chunk), dtype=np.int32)
        for i in range(len(chunk)):
            key = packed[i].tobytes()
            pid = self._pattern_keys.get(key)
            if pid is None:
                pid = len(self._pattern_cols)
                self._pattern_keys[key] = pid
                self._pattern_cols.append(tuple(c for c, on in zip(self.meas, populated[i], strict=True) if on))
            ids[i] = pid
        self._pattern.append(ids)
        self._ranges.append((self._rows + 1, self._rows + len(chunk)))
        self._digests.append(
            {c: column_digest(chunk[c].astype(object).tolist()) for c in chunk.columns if c != self.ts_col}
        )
        self._text.append(text.astype(object).to_numpy())
        self._ns.append(ns)
        self._status.append(status)
        self._hash.append(row_hash)
        self._present.append(present)
        self._rows += len(chunk)

    def finalize(self) -> TimeIndex:
        n = self._rows
        text = np.concatenate(self._text) if self._text else np.array([], dtype=object)
        ns = np.concatenate(self._ns) if self._ns else np.array([], dtype=np.int64)
        status = np.concatenate(self._status) if self._status else np.array([], dtype=np.int8)
        row_hash = np.concatenate(self._hash) if self._hash else np.array([], dtype=np.uint64)
        present = np.concatenate(self._present) if self._present else np.array([], dtype=np.int16)
        pattern_id = np.concatenate(self._pattern) if self._pattern else np.array([], dtype=np.int32)

        ok_idx = np.flatnonzero(status == OK)
        elapsed = np.full(n, np.nan)
        delta = np.full(n, np.nan)
        flag = np.full(n, _ORDER_CODES[OrderFlag.UNPARSED], dtype=np.int8)
        if ok_idx.size:
            ok_ns = ns[ok_idx]
            elapsed[ok_idx] = (ok_ns - ok_ns[0]) / 1e9
            d = np.diff(ok_ns) / 1e9
            delta[ok_idx[1:]] = d
            flag[ok_idx[0]] = _ORDER_CODES[OrderFlag.FIRST]
            flag[ok_idx[1:]] = np.where(d < 0, _ORDER_CODES[OrderFlag.BACKWARD], _ORDER_CODES[OrderFlag.OK])

        dup_group = np.full(n, -1, dtype=np.int32)
        dup_size = np.zeros(n, dtype=np.int32)
        seq = np.zeros(n, dtype=np.int32)
        conflict = np.zeros(n, dtype=bool)
        if ok_idx.size:
            uniq, first_pos, inverse, counts = np.unique(
                ns[ok_idx], return_index=True, return_inverse=True, return_counts=True
            )
            inverse = np.asarray(inverse).reshape(-1)
            dup_u = np.flatnonzero(counts > 1)
            if dup_u.size:
                order = np.argsort(first_pos[dup_u], kind="stable")  # number groups by first appearance in SOURCE order
                gid_of_unique = np.full(uniq.shape[0], -1, dtype=np.int32)
                gid_of_unique[dup_u[order]] = np.arange(dup_u.size, dtype=np.int32)
                g_ok = gid_of_unique[inverse]
                sel = g_ok >= 0
                rows = ok_idx[sel]
                dup_group[rows] = g_ok[sel]
                dup_size[rows] = counts[inverse][sel].astype(np.int32)
                frame = pd.DataFrame({"g": g_ok[sel], "h": row_hash[rows]})
                seq[rows] = (frame.groupby("g").cumcount() + 1).to_numpy(dtype=np.int32)
                differs = frame.groupby("g")["h"].transform("nunique").to_numpy() > 1
                conflict[rows] = differs

        return TimeIndex(
            file_key=self.file_key,
            timestamp_column=self.ts_col,
            ts_text=text,
            ts_ns=np.where(status == OK, ns, NAT_NS).astype(np.int64),
            ts_status=status,
            elapsed_s=elapsed,
            delta_s=delta,
            order_flag=flag,
            dup_group=dup_group,
            dup_size=dup_size,
            seq_in_group=seq,
            dup_conflict=conflict,
            n_present=present,
            n_expected=len(self.meas),
            measurement_columns=self.meas,
            missing_by_column=dict(self._missing),
            pattern_id=pattern_id,
            pattern_columns=list(self._pattern_cols),
            chunk_ranges=list(self._ranges),
            chunk_digests=list(self._digests),
        )
