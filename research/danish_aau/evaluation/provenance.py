"""Provenance and unit-confidence vocabulary (context doc, sections 5 and 7).

Every quantity that enters a derived artifact or report carries one ``Provenance`` label and, for measured
columns, a ``UnitBasis`` saying HOW the unit is known. Simulated values are never relabelled as measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Provenance(str, Enum):
    MEASURED = "measured"  # produced by a documented physical measurement system, subject to its uncertainty
    ESTIMATED = "estimated"  # inferred from another measurement (e.g. server power = rack PDU power / n servers)
    DERIVED = "derived"  # computed from other quantities; the formula and input provenance must be recorded
    SIMULATED = "simulated"  # produced by TwinGrid's model or synthetic-data generator


class UnitBasis(str, Enum):
    CSV_HEADER = "csv_header"  # the CSV column header states the unit
    PAPER_CONTEXT = "paper_context"  # supported by the paper's methodology; the header omits it
    UNCONFIRMED = "unconfirmed"  # no source established the unit; do not assume one


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    kind: str  # timestamp | power | temperature | velocity | boundary_temperature | ventilation
    provenance: Provenance | None  # None for the timestamp column (not a measurement)
    unit: str | None  # None when UnitBasis.UNCONFIRMED
    unit_basis: UnitBasis
    note: str = ""

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "kind": self.kind,
            "provenance": self.provenance.value if self.provenance else None,
            "unit": self.unit,
            "unit_basis": self.unit_basis.value,
            "note": self.note,
        }
