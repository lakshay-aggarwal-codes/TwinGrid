"""L1: original, read-only observations as a lazy stream.

An ``ObservationStream`` never sorts, drops, averages or rewrites anything: it iterates the file in source order and
applies only the EXPLICIT selection it was given (columns, src_rows, window), which is recorded in its provenance.
Materialising it into one in-memory DataFrame is a deliberate, guarded act (``to_frame``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .errors import MaterialisationError
from .provenance import DerivationRecord, output_descriptor, row_summary
from .reader import AauCsvReader
from .vocabulary import Layer, Provenance

ANNOTATION_COLUMNS = 14  # _src_file + the 13 TimeIndex annotation columns (see TimeIndex.slice_annotations)


def check_materialisation(cell_limit: int, cells: int, confirm: bool, allow_large: bool) -> None:
    """The single guard behind every to_frame(): explicit confirmation AND a size limit."""
    if not confirm:
        raise MaterialisationError(
            "to_frame() materialises the observations in memory; pass confirm=True to request that deliberately "
            "(prefer iter_chunks() for large files)"
        )
    if cells > cell_limit and not allow_large:
        raise MaterialisationError(
            f"estimated {cells} cells exceeds reader.materialise_cell_limit={cell_limit}; narrow the selection or pass allow_large=True"
        )


@dataclass
class ObservationStream:
    reader: AauCsvReader
    columns: tuple[str, ...]
    src_rows: tuple[int, ...] | None = None
    window: tuple[str, str] | None = None
    include_text: bool = False

    layer = Layer.L1_OBSERVED
    provenance = Provenance.MEASURED

    @classmethod
    def open(
        cls,
        reader: AauCsvReader,
        columns: Sequence[str] | None = None,
        *,
        src_rows: Sequence[int] | None = None,
        window: tuple[str, str] | None = None,
        include_text: bool = False,
    ) -> ObservationStream:
        cols = tuple(columns) if columns is not None else tuple(reader.channels.measurement_columns)
        return cls(
            reader, cols, tuple(int(r) for r in src_rows) if src_rows is not None else None, window, include_text
        )

    # -- selection ------------------------------------------------------------------------------------------------
    def selected_rows(self):
        return self.reader.selected_rows(self.src_rows, self.window)

    @property
    def n_selected_rows(self) -> int:
        return int(self.selected_rows().size)

    # -- iteration ------------------------------------------------------------------------------------------------
    def iter_chunks(self) -> Iterator[pd.DataFrame]:
        yield from self.reader.iter_chunks(
            self.columns, src_rows=self.src_rows, window=self.window, include_text=self.include_text
        )

    # -- guarded materialisation ------------------------------------------------------------------------------------
    def estimated_cells(self) -> int:
        per_row = ANNOTATION_COLUMNS + len(self.columns) * (2 if self.include_text else 1)
        return self.n_selected_rows * per_row

    def to_frame(self, *, confirm: bool = False, allow_large: bool = False) -> pd.DataFrame:
        """Materialise the selection in memory. Requires ``confirm=True``; refuses over the configured cell limit
        unless ``allow_large=True``. Row order and values are exactly the file's."""
        check_materialisation(
            self.reader.cfg.reader.materialise_cell_limit, self.estimated_cells(), confirm, allow_large
        )
        parts = list(self.iter_chunks())
        frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        frame.attrs.update(
            {"layer": self.layer.value, "provenance": self.provenance.value, "file_key": self.reader.source.key}
        )
        return frame

    # -- provenance -------------------------------------------------------------------------------------------------
    def derivation_record(self) -> DerivationRecord:
        rows = self.selected_rows()
        return DerivationRecord(
            operation="l1_observation_view",
            policy_id=None,
            transformation="read-only view of the source file in source order; selection is explicit; values converted to float64 without alteration",
            source_files=(self.reader.source.relpath,),
            source_rows=row_summary(rows),
            config={
                "columns": list(self.columns),
                "src_rows_given": self.src_rows is not None,
                "window": list(self.window) if self.window else None,
                "timestamp_state": self.reader.index.timestamp_state if self.reader.index else None,
                "timestamp_formats": list(self.reader.formats),
                "chunksize": self.reader.cfg.reader.chunksize,
                "data_config_sha256": self.reader.cfg.sha256,
            },
            exclusions=None,
            output=output_descriptor(self.layer, self.provenance, rows.size, list(self.columns)),
        )

    def describe(self) -> dict[str, Any]:
        return self.derivation_record().to_dict()
