"""The one owner-approved derivation (Task 13 Q-1): derived.rack_power_total_1_6 = Power Ch 1 + Ch 2 + Ch 3.

Defined at a stored second only when all three inputs are observed with quality ok; otherwise the value is absent (never a
partial sum, never imputed). Computed in integer 0.1 W ticks, so the result is exact. Attributed to Racks 1-6 as a group.
Nothing is split per rack. Temperatures are never combined.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..cleaning.resolve import CleanResult
from .channels import decimals_of
from .errors import PanelError

DERIVED_HEADER = ["ts_text", "value_ticks", "state", "quality", "reason_code"]
REASON_INPUTS_ABSENT = "inputs_not_all_observed"


def input_columns(defn: dict[str, Any], registry: Any, result: CleanResult) -> list[int]:
    if defn.get("operation") != "sum" or defn.get("provenance") != "derived":
        raise PanelError(f"only the approved 'sum' derivation is implemented, got {defn.get('operation')!r}")
    idx: list[int] = []
    decimals: set[int] = set()
    for sid in defn["inputs"]:
        ent = registry.sensor(sid)
        col = ent["source_column"]
        if col not in result.columns:
            raise PanelError(f"derivation input {sid!r} ({col!r}) is not a Tier 1 column of the cleaned file")
        if ent["measurand"] != "power" or ent["unit"] != "W":
            raise PanelError(f"derivation input {sid!r} is not a measured power channel in W")
        decimals.add(decimals_of(result.resolutions[col]))
        idx.append(result.columns.index(col))
    if len(decimals) != 1:
        raise PanelError("derivation inputs have different resolutions; ticks cannot be added")
    if defn["output_unit"] != "W" or defn["output_measurand"] != "power":
        raise PanelError("derivation output must be power in W")
    return idx


def derive_sum(result: CleanResult, registry: Any, defn: dict[str, Any]) -> pd.DataFrame:
    idx = input_columns(defn, registry, result)
    ok = result.valid[:, idx].all(axis=1) & (result.flag[:, idx] == 0).all(axis=1)
    total = result.ticks[:, idx].astype(np.int64).sum(axis=1)
    ticks = pd.array(np.where(ok, total, 0), dtype="Int64")
    ticks[~ok] = pd.NA
    return pd.DataFrame(
        {
            "ts_text": result.ts_text.astype(str),
            "value_ticks": ticks,
            "state": np.where(ok, "observed", "missing"),
            "quality": np.where(ok, "ok", ""),
            "reason_code": np.where(ok, "", REASON_INPUTS_ABSENT),
        }
    )[DERIVED_HEADER]
