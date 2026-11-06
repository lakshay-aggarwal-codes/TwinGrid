"""Chunked, read-only cell reader with stable source references. Reuses ``AauCsvReader`` (two-pass, integrity-checked).

Cell order is fixed: file row order, then the header's measurement-column order. Values are never altered, filled,
resolved or converted: ``value_text`` is the raw cell, ``value`` its float (None when blank). Duplicate timestamps stay
as separate rows (the reader's ``keep_all_ordered``); resolving them is Task 12.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from typing import NamedTuple

import numpy as np

from ..evaluation.data_layer.channels import resolve_channels
from ..evaluation.data_layer.config import DataConfig, ReaderSection
from ..evaluation.data_layer.errors import DataLayerError
from ..evaluation.data_layer.reader import AauCsvReader
from ..evaluation.data_layer.time_index import OK, TimeIndex
from .errors import AdapterError
from .schema import DATASET_ID, ROW_NUMBERING
from .source import AdapterSource


class ParsedCell(NamedTuple):
    file: str
    column: str
    row_ordinal: int  # 1-based data row, header excluded (contract section 8)
    ts_text: str  # exact source text, naive, no timezone
    value_text: str  # exact source cell ('' = blank)
    value: float | None  # None when blank


def make_source_ref(file: str, column: str, row_ordinal: int | None, ts_text: str, file_sha256: str | None) -> dict:
    """Contract 1.0.0 ``source_ref`` object. Rejects a '|' in file/column (it would corrupt ``key``)."""
    if "|" in file or "|" in column:
        raise AdapterError("file and column names must not contain '|'")
    return {
        "file": file,
        "column": column,
        "row_ordinal": row_ordinal,
        "row_numbering": ROW_NUMBERING if row_ordinal is not None else "unspecified",
        "ts_text": ts_text,
        "key": f"{file}|{column}|{ts_text}",
        "file_sha256": file_sha256,
    }


class AdapterReader:
    dataset_id = DATASET_ID

    def __init__(self, src: AdapterSource, chunksize: int | None = None):
        self.src = src
        cfg = DataConfig(reader=ReaderSection(chunksize=chunksize)) if chunksize else DataConfig()
        self._cfg = cfg
        self._channels = resolve_channels(src.source, cfg)
        self._reader = AauCsvReader(src.source, self._channels, cfg)

    @property
    def columns(self) -> tuple[str, ...]:
        """Measurement columns in header order."""
        return self._channels.measurement_columns

    def build_index(self) -> TimeIndex:
        try:
            idx = self._reader.build_time_index()
        except DataLayerError as exc:
            raise AdapterError(str(exc)) from None
        bad = int((idx.ts_status != OK).sum())
        if bad:
            raise AdapterError(
                f"{self.src.spec.filename}: {bad} row(s) have a timestamp that does not match {self._cfg.reader.timestamp_formats}"
            )
        return idx

    @property
    def index(self) -> TimeIndex:
        return self._reader.require_index()

    def source_ref(self, cell: ParsedCell) -> dict:
        return make_source_ref(cell.file, cell.column, cell.row_ordinal, cell.ts_text, self.src.file_sha256)

    def iter_frames(self, columns: Sequence[str] | None = None, *, include_text: bool = True):
        """Reader chunks (annotation columns ``_src_row``, ``_ts_text``, ``_dup_*`` ... plus ``<col>`` and ``<col>__text``)."""
        try:
            yield from self._reader.iter_chunks(self._select(columns), include_text=include_text)
        except AdapterError:
            raise
        except DataLayerError as exc:  # e.g. a non-numeric cell: refused, never coerced
            raise AdapterError(str(exc)) from None

    def _select(self, columns: Sequence[str] | None) -> list[str]:
        if columns is None:
            return list(self.columns)
        bad = [c for c in columns if c not in self.columns]
        if bad:
            raise AdapterError(f"{self.src.spec.filename}: not a measurement column: {bad}")
        return list(dict.fromkeys(columns)) if len(set(columns)) != len(columns) else list(columns)

    def iter_cells(self, columns: Sequence[str] | None = None) -> Iterator[ParsedCell]:
        cols = self._select(columns)
        name = self.src.spec.filename
        for frame in self.iter_frames(cols, include_text=True):
            rows = frame["_src_row"].to_numpy()
            ts = frame["_ts_text"].to_numpy()
            texts = [frame[f"{c}__text"].to_numpy() for c in cols]
            vals = [frame[c].to_numpy() for c in cols]
            for i in range(len(rows)):
                r, t = int(rows[i]), str(ts[i])
                for j, c in enumerate(cols):
                    v = vals[j][i]
                    yield ParsedCell(name, c, r, t, str(texts[j][i]), None if np.isnan(v) else float(v))

    def fingerprint(self, columns: Sequence[str] | None = None) -> str:
        """SHA-256 over every (row, timestamp text, column, value text). Equal across reruns for an unchanged file."""
        h = hashlib.sha256()
        for c in self.iter_cells(columns):
            h.update(f"{c.row_ordinal}\x1f{c.ts_text}\x1f{c.column}\x1f{c.value_text}\x1e".encode())
        return h.hexdigest()

    def verify_integrity(self) -> dict:
        try:
            return self._reader.verify_integrity()
        except DataLayerError as exc:
            raise AdapterError(str(exc)) from None
