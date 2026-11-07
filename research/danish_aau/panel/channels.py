"""Tier 1 column set versus the approved mapping, and the per-channel provenance/quality table."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import numpy as np

from ..cleaning.catalogue import REASON_BLANK, REASON_TIE
from ..cleaning.resolve import CleanResult
from ..cleaning.tier1 import POWER_COLUMNS, RACK_PROBE_COLUMNS, TIER1_COLUMNS, column_slug
from .errors import PanelError

FAMILY = "temperature_power"


def decimals_of(resolution_text: str) -> int:
    return -Decimal(resolution_text).as_tuple().exponent


def check_tier1_against_mapping(registry: Any, protocol: Any, filename: str) -> list[dict]:
    """The Tier 1 cleaning columns must be exactly the mapping's mapped, load-in-v1 Tier 1 columns of this file family.

    Returns the mapping entities in cleaning-column order. Raises PanelError listing every problem.
    """
    ents = [e for e in registry.entities(tier="tier1", load_in_v1=True) if e["source_file_family"] == FAMILY]
    by_col = {e["source_column"]: e for e in ents}
    problems: list[str] = []
    if len(by_col) != len(ents):
        problems.append("two mapping entities share one source column")
    only_clean = sorted(set(TIER1_COLUMNS) - set(by_col))
    only_map = sorted(set(by_col) - set(TIER1_COLUMNS))
    if only_clean:
        problems.append(f"cleaning Tier 1 columns not in the mapping: {only_clean[:5]}")
    if only_map:
        problems.append(f"mapping Tier 1 columns not in cleaning: {only_map[:5]}")
    if len(TIER1_COLUMNS) != 40 or len(RACK_PROBE_COLUMNS) != 37 or len(POWER_COLUMNS) != 3:
        problems.append("cleaning Tier 1 must be 37 rack probes + 3 power channels")
    ordered: list[dict] = []
    for col in TIER1_COLUMNS:
        e = by_col.get(col)
        if e is None:
            continue
        cls = e["source_entity_class"]
        if (col in POWER_COLUMNS) != (cls == "power_channel") or (col in RACK_PROBE_COLUMNS) != (cls == "rack_probe"):
            problems.append(f"{col}: entity class {cls!r} disagrees with the cleaning column group")
        if e["mapping_state"] != "mapped" or not e["sensor_external_id"]:
            problems.append(f"{col}: mapping_state {e['mapping_state']!r} or no sensor id")
        want = -protocol.resolution(col, filename).as_tuple().exponent
        if e["resolution_decimals"] != want:
            problems.append(f"{col}: mapping resolution {e['resolution_decimals']} vs protocol {want} decimals")
        ordered.append(e)
    if problems:
        raise PanelError("Tier 1 column set does not match the mapping: " + "; ".join(problems))
    return ordered


def channel_table(
    result: CleanResult, entities: list[dict], l1_files: dict[str, dict], mapping_sha256: str
) -> list[dict]:
    """One provenance + quality entry per Tier 1 channel, in cleaning-column order. Counts come from the arrays."""
    out: list[dict] = []
    ts = result.ts_text
    for j, (col, e) in enumerate(zip(result.columns, entities, strict=True)):
        if e["source_column"] != col:
            raise PanelError(f"channel order mismatch at {j}: {col!r} vs {e['source_column']!r}")
        valid = result.valid[:, j]
        obs_idx = np.flatnonzero(valid)
        rel = f"observations/{column_slug(col)}.tsv"
        meta = l1_files[rel]
        out.append(
            {
                "source_column": col,
                "sensor_external_id": e["sensor_external_id"],
                "entity_id": e["entity_id"],
                "provenance": "measured",
                "storage_class": "research_import_file",
                "measurand": e["measurand"],
                "unit": e["unit"],
                "resolution_decimals": e["resolution_decimals"],
                "asset_external_id": e["asset_external_id"],
                "target_asset_external_ids": list(e["target_asset_external_ids"]),
                "attribution": {
                    "scope": e["attribution"]["scope"],
                    "member_source_rack_ids": list(e["attribution"]["member_source_rack_ids"]),
                    "split_allowed": bool(e["attribution"]["split_allowed"]),
                },
                "mapping": {
                    "mapping_id": e["mapping_id"],
                    "mapping_version": e["mapping_version"],
                    "method": e["method"],
                    "label_evidence": e["label_evidence"],
                    "evidence_status": e["evidence_status"],
                    "valid_time_status": e["valid_time_status"],
                    "mapping_file_sha256_lf": mapping_sha256,
                },
                "quality": {
                    "stored_seconds": int(result.n_seconds),
                    "observed": int(valid.sum()),
                    "observed_ok": int((valid & (result.flag[:, j] == 0)).sum()),
                    "observed_flagged": int((valid & (result.flag[:, j] > 0)).sum()),
                    "missing_conflict_unresolved_tie": int(((~valid) & (result.reason[:, j] == REASON_TIE)).sum()),
                    "missing_blank_cell": int(((~valid) & (result.reason[:, j] == REASON_BLANK)).sum()),
                    "first_observed_ts_text": str(ts[obs_idx[0]]) if len(obs_idx) else None,
                    "last_observed_ts_text": str(ts[obs_idx[-1]]) if len(obs_idx) else None,
                },
                "l1_file": rel,
                "l1_file_sha256": meta["sha256"],
                "l1_file_rows": meta["rows"],
            }
        )
    return out
