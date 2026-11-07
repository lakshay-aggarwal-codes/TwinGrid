"""Cleaning ledger: exactly one disposition per raw row, a reconciliation check and contract 1.0.0 ledger entries."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from .catalogue import (
    D_CONFLICT_MISSING,
    D_CONFLICT_RULE,
    D_DROPPED,
    D_EXACT_DUP,
    D_FLAGGED,
    D_RETAINED,
    FLAG_TEXT,
    ROW_DISPOSITIONS,
)
from .resolve import CleanResult

ROW_NUMBERING = "data_row_ordinal_excluding_header"  # contract section 8; confirmed by Task 11


def disposition_counts(result: CleanResult) -> dict[str, int]:
    c = np.bincount(result.row_disp.astype(np.int64), minlength=len(ROW_DISPOSITIONS))
    return {name: int(c[i]) for i, name in enumerate(ROW_DISPOSITIONS)}


def reconcile(result: CleanResult) -> list[str]:
    """Return a list of problems (empty = the ledger reconciles)."""
    problems: list[str] = []
    counts = disposition_counts(result)
    if sum(counts.values()) != result.n_rows:
        problems.append("dispositions do not sum to the raw row count")
    if result.n_rows != int(result.group_size.sum()):
        problems.append("raw rows differ from the sum of group sizes")
    per_sec = np.bincount(result.row_sec.astype(np.int64), minlength=result.n_seconds)
    if not np.array_equal(per_sec, result.group_size.astype(np.int64)):
        problems.append("rows per stored second differ from group_size")
    d = result.row_disp.astype(np.int64)
    s = result.row_sec.astype(np.int64)
    for code, name in (
        (D_CONFLICT_MISSING, "conflict_cell_missing"),
        (D_CONFLICT_RULE, "conflict_resolved_by_source_rule"),
    ):
        in_conflict = np.bincount(s[d == code], minlength=result.n_seconds)
        bad = (in_conflict != 0) & (in_conflict != result.group_size)
        if bad.any():
            problems.append(f"{name}: a group is only partly labelled")
    representatives = np.bincount(s[(d == D_RETAINED) | (d == D_FLAGGED)], minlength=result.n_seconds)
    dup = np.bincount(s[d == D_EXACT_DUP], minlength=result.n_seconds)
    plain = result.sec_disp == D_RETAINED
    if (representatives[plain] != 1).any():
        problems.append("a non-conflict group does not have exactly one retained row")
    if ((dup + representatives)[plain] != result.group_size[plain]).any():
        problems.append("a non-conflict group has rows that are neither retained nor exact_duplicate")
    return problems


def ledger_summary(result: CleanResult) -> dict:
    counts = disposition_counts(result)
    return {
        "file": result.file,
        "raw_rows": result.n_rows,
        "unique_seconds": result.n_seconds,
        "by_disposition": counts,
        "repeated_timestamp_groups": {str(k): v for k, v in result.stats.get("group_sizes", {}).items()},
        "cells_made_missing_all_columns": result.stats.get("cells_made_missing_all_columns"),
        "cells_made_missing_tier1": result.stats.get("cells_made_missing_tier1"),
        "reconciles": not reconcile(result),
    }


def _reason_for(result: CleanResult, row: int) -> str | None:
    d = int(result.row_disp[row])
    if d == D_CONFLICT_MISSING:
        return "conflict_unresolved_tie"
    if d == D_CONFLICT_RULE:
        return "source_authority_rule"
    if d == D_FLAGGED:
        f = result.flag[int(result.row_sec[row])]
        return FLAG_TEXT[int(f[f > 0].min())]
    if d == D_DROPPED:
        return "dropped_row_reason_undefined"
    return None


def ledger_entries(
    result: CleanResult, *, dataset_id: str, protocol_sha256: str, contract_version: str = "1.0.0"
) -> Iterator[dict]:
    """Contract 1.0.0 ``ledger_entry`` objects (exactly the 11 contract keys), ascending by source row."""
    for i in range(result.n_rows):
        s = int(result.row_sec[i])
        yield {
            "contract_version": contract_version,
            "record_kind": "ledger_entry",
            "dataset_id": dataset_id,
            "file": result.file,
            "row_ordinal": int(result.row_ordinal[i]),
            "row_numbering": ROW_NUMBERING,
            "ts_source_text": str(result.ts_text[s]),
            "disposition": ROW_DISPOSITIONS[int(result.row_disp[i])],
            "reason_code": _reason_for(result, i),
            "group_size": int(result.group_size[s]),
            "protocol_sha256": protocol_sha256,
        }
