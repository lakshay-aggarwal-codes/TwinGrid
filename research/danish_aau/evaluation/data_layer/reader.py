"""Two-pass streaming reader for the registered AAU CSV files (L0 -> L1).

PASS 1  ``build_time_index()``: stream the file in chunks (default 50,000 rows), keep the ORIGINAL timestamp text, parse it
        with the configured explicit format(s), and build one global ``TimeIndex`` (row numbers, status, ordering,
        deltas, duplicate groups across chunk boundaries, completeness, conflicts).
PASS 2  ``iter_chunks()``: stream ONLY the requested columns (and, optionally, only requested rows/window), attach the
        TimeIndex annotations, convert values to float64 without altering them.

Guarantees: file order and every row are preserved (selection is explicit and recorded, never implicit); values are never
filled, interpolated, averaged or rewritten; raw files are opened only through the Phase 1 read-only helper; pass 2
verifies, for each chunk, the timestamp text AND the content of every column it reads against the digests stored by
pass 1, so a changed value is detected even when the timestamp and the cell length are unchanged. Columns pass 2 does
not read are NOT verified by it; ``verify_integrity()`` re-reads every column and verifies them all.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import numpy as np
import pandas as pd

from ..guard import open_raw_bytes
from .channels import ChannelSet
from .config import DataConfig
from .discovery import SourceFile
from .errors import DataConfigError, NumericParseError, ReaderError
from .time_index import TimeIndex, TimeIndexBuilder, column_digest
from .timeparse import parse_one


class AauCsvReader:
    def __init__(self, source: SourceFile, channels: ChannelSet, data_cfg: DataConfig):
        self.source, self.channels, self.cfg = source, channels, data_cfg
        self.delimiter = source.delimiter
        if not self.delimiter:
            raise ReaderError(
                f"{source.key}: delimiter is ambiguous in the header; set reader.delimiter in the data config"
            )
        if not source.encoding_utf8:
            raise ReaderError(
                f"{source.key}: the header is not valid UTF-8; set a different reader.encoding after checking the file"
            )
        self.formats = data_cfg.formats_for(source.key)
        self.index: TimeIndex | None = None
        self.diagnostics: dict[str, Any] = self._fresh_diagnostics()

    # ------------------------------------------------------------------------------------------------ plumbing
    @staticmethod
    def _fresh_diagnostics() -> dict[str, Any]:
        return {
            "non_numeric_cells": 0,
            "non_numeric_by_column": {},
            "first_non_numeric": [],
            "rows_streamed": 0,
            "chunks": 0,
        }

    def _chunks(self, usecols: list[str] | None) -> Iterator[pd.DataFrame]:
        rd = self.cfg.reader
        with open_raw_bytes(self.source.path, self.source.raw_dir) as handle:
            try:
                reader = pd.read_csv(
                    handle,
                    sep=self.delimiter,
                    dtype=str,
                    keep_default_na=False,
                    na_filter=False,
                    usecols=usecols,
                    encoding=rd.encoding,
                    chunksize=rd.chunksize,
                    skip_blank_lines=True,
                )
                yield from reader
            except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, ValueError) as exc:
                raise ReaderError(
                    f"{self.source.key}: the CSV is malformed, unreadable or its header changed ({type(exc).__name__}): {str(exc).splitlines()[0]}"
                ) from None

    # ------------------------------------------------------------------------------------------------ pass 1
    def build_time_index(self) -> TimeIndex:
        rd = self.cfg.reader
        builder = TimeIndexBuilder(
            self.source.key,
            self.channels.timestamp_column,
            self.channels.measurement_columns,
            self.formats,
            strip=rd.strip_whitespace,
            na_values=rd.na_values,
        )
        expected = set(self.source.columns)
        for chunk in self._chunks(None):
            if set(chunk.columns) != expected:
                raise ReaderError(f"{self.source.key}: chunk columns differ from the header")
            builder.add_chunk(chunk)
        self.index = builder.finalize()
        return self.index

    def require_index(self) -> TimeIndex:
        if self.index is None:
            raise ReaderError("the TimeIndex has not been built yet: call build_time_index() first (pass 1)")
        return self.index

    # ------------------------------------------------------------------------------------------------ integrity
    def _verify_chunk(self, chunk: pd.DataFrame, cols: Sequence[str], chunk_no: int, first: int, last: int) -> None:
        """Compare a pass-2 chunk with pass 1: boundaries, timestamp text of every row, content of every read column."""
        idx = self.require_index()
        key = self.source.key
        if chunk_no >= len(idx.chunk_ranges) or idx.chunk_ranges[chunk_no] != (first, last):
            raise ReaderError(
                f"{key}: chunk {chunk_no + 1} covers rows {first}-{last} but pass 1 saw a different layout; the file changed between passes"
            )
        ann_text = idx.ts_text[first - 1 : last]
        if not np.array_equal(chunk[self.channels.timestamp_column].astype(object).to_numpy(), ann_text):
            raise ReaderError(
                f"{key}: timestamps differ from pass 1 near src_row {first}; the file changed between passes"
            )
        expected = idx.chunk_digests[chunk_no]
        for col in cols:
            if column_digest(chunk[col].astype(object).tolist()) != expected.get(col):
                raise ReaderError(
                    f"{key}: the content of column {col!r} differs from pass 1 in rows {first}-{last}; the file changed between passes"
                )

    def verify_integrity(self, columns: Sequence[str] | None = None) -> dict[str, Any]:
        """Re-read the file and verify the timestamp column and every listed column (default: ALL non-timestamp columns)
        against pass 1. Raises ReaderError on any difference. Nothing is kept in memory beyond one chunk."""
        idx = self.require_index()
        ts_col = self.channels.timestamp_column
        cols = list(columns) if columns is not None else [c for c in self.source.columns if c != ts_col]
        bad = [c for c in cols if c not in self.source.columns or c == ts_col]
        if bad:
            raise DataConfigError(f"{self.source.key}: cannot verify column(s) {bad}")
        n, chunk_no = 0, 0
        for chunk in self._chunks([ts_col, *cols]):
            self._verify_chunk(chunk, cols, chunk_no, n + 1, n + len(chunk))
            n += len(chunk)
            chunk_no += 1
        if n != idx.n_rows or chunk_no != len(idx.chunk_ranges):
            raise ReaderError(
                f"{self.source.key}: the file has {n} rows now but pass 1 saw {idx.n_rows}; the file changed between passes"
            )
        return {"columns_verified": len(cols), "rows": n, "chunks": chunk_no, "timestamp_column_verified": True}

    # ------------------------------------------------------------------------------------------------ pass 2
    def window_ns(self, window: tuple[str, str]) -> tuple[int, int]:
        lo, hi = (parse_one(t, self.formats) for t in window)
        if lo is None or hi is None:
            raise DataConfigError(f"window {window!r} does not match the configured timestamp format")
        if lo > hi:
            raise DataConfigError("window start is after window end")
        return lo, hi

    def selected_rows(self, src_rows: Sequence[int] | None = None, window: tuple[str, str] | None = None) -> np.ndarray:
        """1-based src rows chosen by an explicit selection; derived from the index only (no value I/O)."""
        idx = self.require_index()
        rows = idx.src_rows()
        mask = np.ones(idx.n_rows, dtype=bool)
        if src_rows is not None:
            mask &= np.isin(rows, np.asarray(list(src_rows), dtype=np.int64))
        if window is not None:
            lo, hi = self.window_ns(window)
            mask &= (idx.ts_status == 0) & (idx.ts_ns >= lo) & (idx.ts_ns <= hi)
        return rows[mask]

    def _numeric(self, col: str, series: pd.Series, first_row: int) -> np.ndarray:
        rd = self.cfg.reader
        cells = series.astype(object).map(lambda v: "" if v is None else str(v))
        cells = cells.str.strip() if rd.strip_whitespace else cells
        missing = cells.isin(set(rd.na_values)).to_numpy()
        values = pd.to_numeric(cells.mask(missing), errors="coerce").to_numpy(
            dtype=np.float64, copy=True
        )  # copy: pandas CoW arrays are read-only
        bad = ~missing & ~np.isfinite(values)
        if bad.any():
            where = [int(first_row + i) for i in np.flatnonzero(bad)]
            if rd.non_numeric == "raise":
                raise NumericParseError(
                    f"{self.source.key}: column {col!r} has a non-numeric, non-missing cell at src_row {where[0]}"
                )
            values[bad] = np.nan
            d = self.diagnostics
            d["non_numeric_cells"] += len(where)
            d["non_numeric_by_column"][col] = d["non_numeric_by_column"].get(col, 0) + len(where)
            d["first_non_numeric"].extend((r, col) for r in where[: max(0, 20 - len(d["first_non_numeric"]))])
        return values

    def iter_chunks(
        self,
        columns: Sequence[str] | None = None,
        *,
        src_rows: Sequence[int] | None = None,
        window: tuple[str, str] | None = None,
        include_text: bool = False,
    ) -> Iterator[pd.DataFrame]:
        idx = self.require_index()
        cols = list(columns) if columns is not None else list(self.channels.measurement_columns)
        header = set(self.source.columns)
        bad = [c for c in cols if c not in header or c == self.channels.timestamp_column]
        if bad:
            raise DataConfigError(f"{self.source.key}: cannot select column(s) {bad}")
        if len(set(cols)) != len(cols):
            raise DataConfigError("duplicate column selection")
        ts_col = self.channels.timestamp_column
        keep = set(int(r) for r in src_rows) if src_rows is not None else None
        win = self.window_ns(window) if window is not None else None
        self.diagnostics = self._fresh_diagnostics()
        start = 0
        for chunk_no, chunk in enumerate(self._chunks([ts_col, *cols])):
            n = len(chunk)
            first, last = start + 1, start + n
            self._verify_chunk(chunk, cols, chunk_no, first, last)
            ann = idx.slice_annotations(first, last)
            frame = ann.copy()
            frame.insert(0, "_src_file", self.source.filename)
            for col in cols:
                frame[col] = self._numeric(col, chunk[col], first)
                if include_text:
                    frame[f"{col}__text"] = chunk[col].astype(object).to_numpy()
            mask = np.ones(n, dtype=bool)
            if keep is not None:
                mask &= frame["_src_row"].isin(keep).to_numpy()
            if win is not None:
                mask &= (
                    (frame["_ts_status"] == "ok") & (frame["_ts_ns"] >= win[0]) & (frame["_ts_ns"] <= win[1])
                ).to_numpy()
            self.diagnostics["rows_streamed"] += n
            self.diagnostics["chunks"] += 1
            start = last
            if mask.any():
                yield frame[mask].reset_index(drop=True)
        if start != idx.n_rows:
            raise ReaderError(
                f"{self.source.key}: pass 2 saw {start} rows but pass 1 saw {idx.n_rows}; the file changed between passes"
            )
