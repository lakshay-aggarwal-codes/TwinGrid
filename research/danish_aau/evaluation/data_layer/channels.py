"""Channel declarations: which column is the timestamp, which columns are measurement fields.

No sensor mapping or unit is invented. Units and provenance come only from the Phase 1 column classification
(header/paper-context/unconfirmed); unclassified columns are kept but marked ``classified=False``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..provenance import Provenance, UnitBasis
from ..registry import classify_column
from .config import DataConfig
from .discovery import SourceFile
from .errors import DataConfigError, ReaderError


@dataclass(frozen=True)
class ChannelInfo:
    name: str
    kind: str | None
    unit: str | None
    unit_basis: str
    provenance: str | None
    classified: bool


@dataclass(frozen=True)
class ChannelSet:
    file_key: str
    timestamp_column: str
    measurement_columns: tuple[str, ...]
    channels: dict[str, ChannelInfo]

    def info(self, column: str) -> ChannelInfo:
        return self.channels[column]


def resolve_channels(source: SourceFile, data_cfg: DataConfig) -> ChannelSet:
    ts = source.timestamp_column
    header = list(source.columns)
    if not header or source.delimiter is None:
        raise ReaderError(
            f"{source.key}: the header could not be split into columns (delimiter ambiguous); set reader.delimiter in the data config"
        )
    problems: list[str] = []
    if ts not in header:
        problems.append(f"{source.key}: timestamp column {ts!r} not in the header")
    configured = data_cfg.file(source.key).measurement_columns
    if configured:
        problems.extend(
            f"{source.key}: configured column {c!r} not in the header" for c in configured if c not in header
        )
        if ts in configured:
            problems.append(f"{source.key}: the timestamp column cannot be a measurement column")
        measurement = tuple(configured)
    else:
        measurement = tuple(c for c in header if c != ts)
    if len(set(header)) != len(header):
        problems.append(f"{source.key}: duplicate column names in the header")
    if problems:
        raise DataConfigError(problems)
    infos: dict[str, ChannelInfo] = {}
    for col in header:
        spec = classify_column(source.key, col)
        if spec is None:
            infos[col] = ChannelInfo(col, None, None, UnitBasis.UNCONFIRMED.value, None, False)
        else:
            prov = spec.provenance.value if isinstance(spec.provenance, Provenance) else None
            infos[col] = ChannelInfo(col, spec.kind, spec.unit, spec.unit_basis.value, prov, True)
    return ChannelSet(source.key, ts, measurement, infos)
