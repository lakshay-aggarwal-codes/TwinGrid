"""L2: policy-controlled DERIVED observations.

Decisions come from configuration and are recorded; nothing is decided silently.

  duplicates   keep_all_ordered   PRIMARY. Every row is kept in source order with duplicate-group ids and conflict flags.
               exclude_ambiguous  SENSITIVITY. Needs explicit approval; removes every row of a CONFLICTING duplicate group
                                  and records each one in a complete exclusion ledger. Never replaces the primary policy.
  empty rows   exclude_empty_rows EMPTY rows (no measurement field populated) stay in L1 but are not valid measurement
                                  observations: excluded from the L2 view with a ledger.
               keep_empty_flagged EMPTY rows are kept and flagged ``_valid_observation = False``.

keep-first / keep-last / averaging do not exist here. A PARTIAL row (e.g. a damper-only observation) is always kept.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .. import _reuse
from .errors import DataConfigError, PolicyNotApproved
from .observations import ObservationStream, check_materialisation
from .provenance import DerivationRecord, ExclusionLedger, output_descriptor, row_summary
from .time_index import TimeIndex
from .vocabulary import Completeness, Layer, PolicyId, Provenance


def plan_duplicate_policy(
    index: TimeIndex, rows: np.ndarray, policy: str, approved: tuple[str, ...]
) -> ExclusionLedger:
    """Exclusion ledger of the duplicate policy over the selected ``rows`` (empty for keep_all_ordered)."""
    if policy not in PolicyId.DUPLICATE_POLICIES:
        raise DataConfigError(f"unknown duplicate policy {policy!r}")
    ledger = ExclusionLedger(policy, index.file_key)
    if policy == PolicyId.KEEP_ALL_ORDERED:
        return ledger
    if policy not in approved:
        raise PolicyNotApproved(
            f"{policy!r} is a sensitivity policy and is not approved in policies.approved_sensitivity"
        )
    for r in rows:
        i = int(r) - 1
        if index.dup_group[i] >= 0 and index.dup_conflict[i]:
            ledger.add(
                r,
                "conflicting_duplicate_group",
                dup_group=int(index.dup_group[i]),
                seq_in_group=int(index.seq_in_group[i]),
            )
    return ledger


def plan_empty_policy(index: TimeIndex, rows: np.ndarray, policy: str) -> ExclusionLedger:
    if policy not in PolicyId.EMPTY_POLICIES:
        raise DataConfigError(f"unknown empty-row policy {policy!r}")
    ledger = ExclusionLedger(policy, index.file_key)
    if policy == PolicyId.KEEP_EMPTY_FLAGGED:
        return ledger
    comp = index.completeness()
    for r in rows:
        if comp[int(r) - 1] == Completeness.EMPTY.value:
            ledger.add(r, "empty_observation", n_expected_fields=index.n_expected)
    return ledger


@dataclass
class DerivedView:
    """L2 view over an L1 stream. The exclusion plan is computed from the TimeIndex alone (no value I/O)."""

    stream: ObservationStream
    duplicate_policy: str
    empty_policy: str
    approved_sensitivity: tuple[str, ...] = ()

    layer = Layer.L2_DERIVED
    provenance = Provenance.DERIVED

    def __post_init__(self) -> None:
        index = self.stream.reader.require_index()
        rows = self.stream.selected_rows()
        self.duplicate_ledger = plan_duplicate_policy(index, rows, self.duplicate_policy, self.approved_sensitivity)
        self.empty_ledger = plan_empty_policy(index, rows, self.empty_policy)
        self._excluded = self.duplicate_ledger.excluded_rows | self.empty_ledger.excluded_rows
        self._rows = rows

    @property
    def ledgers(self) -> list[ExclusionLedger]:
        return [self.duplicate_ledger, self.empty_ledger]

    def kept_rows(self) -> np.ndarray:
        return np.asarray([r for r in self._rows if int(r) not in self._excluded], dtype=np.int64)

    def iter_chunks(self) -> Iterator[pd.DataFrame]:
        for chunk in self.stream.iter_chunks():
            valid = (chunk["_completeness"] != Completeness.EMPTY.value).to_numpy()
            chunk = chunk.assign(
                _valid_observation=valid,
                _policy_duplicates=self.duplicate_policy,
                _policy_empty_rows=self.empty_policy,
            )
            keep = ~chunk["_src_row"].isin(self._excluded).to_numpy()
            if keep.any():
                yield chunk[keep].reset_index(drop=True)

    def to_frame(self, *, confirm: bool = False, allow_large: bool = False) -> pd.DataFrame:
        """Guarded materialisation of the L2 view (same confirmation and size limit as L1)."""
        check_materialisation(
            self.stream.reader.cfg.reader.materialise_cell_limit, self.stream.estimated_cells(), confirm, allow_large
        )
        parts = list(self.iter_chunks())
        frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        frame.attrs.update(
            {"layer": self.layer.value, "provenance": self.provenance.value, "file_key": self.stream.reader.source.key}
        )
        return frame

    def derivation_records(self) -> list[DerivationRecord]:
        kept = self.kept_rows()
        reader = self.stream.reader
        out = []
        for ledger, label in ((self.duplicate_ledger, "duplicate policy"), (self.empty_ledger, "empty-row policy")):
            out.append(
                DerivationRecord(
                    operation="l2_policy_view",
                    policy_id=ledger.policy_id,
                    transformation=f"{label}: {ledger.policy_id}; rows are never reordered, averaged or filled",
                    source_files=(reader.source.relpath,),
                    source_rows=row_summary(self._rows),
                    config={
                        "duplicate_policy": self.duplicate_policy,
                        "empty_policy": self.empty_policy,
                        "approved_sensitivity": list(self.approved_sensitivity),
                        "data_config_sha256": reader.cfg.sha256,
                    },
                    exclusions=ledger.summary(),
                    output=output_descriptor(self.layer, self.provenance, kept.size, list(self.stream.columns)),
                )
            )
        return out

    def report(self) -> dict[str, Any]:
        index = self.stream.reader.require_index()
        in_view = self.kept_rows()
        return {
            "layer": self.layer.value,
            "provenance": self.provenance.value,
            "duplicate_policy": self.duplicate_policy,
            "empty_policy": self.empty_policy,
            "n_selected_l1_rows": int(self._rows.size),
            "n_rows_in_view": int(in_view.size),
            "n_excluded": len(self._excluded),
            "ledgers": [ledger.summary() for ledger in self.ledgers],
            "n_rows_in_duplicate_groups_kept": int(sum(1 for r in in_view if index.dup_group[int(r) - 1] >= 0)),
            "n_conflicting_rows_kept": int(
                sum(1 for r in in_view if index.dup_group[int(r) - 1] >= 0 and index.dup_conflict[int(r) - 1])
            ),
        }


# ------------------------------------------------------------------------------------------------ sorted view
@dataclass(frozen=True)
class SortedViewRecord:
    """A sorted DERIVED view of the rows: the permutation is recorded so the original order is always recoverable."""

    file_key: str
    order: tuple[
        int, ...
    ]  # src_row ids in the new order (stable sort by parsed time; unparsed rows last, source order)
    n_unparsed_last: int
    permutation_sha256: str
    policy_id: str = PolicyId.STABLE_TIME_ORDER
    layer: str = Layer.L2_DERIVED.value
    provenance: str = Provenance.DERIVED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "file_key": self.file_key,
            "layer": self.layer,
            "provenance": self.provenance,
            "n_rows": len(self.order),
            "n_unparsed_last": self.n_unparsed_last,
            "permutation_sha256": self.permutation_sha256,
        }


def stable_time_order(index: TimeIndex, rows: np.ndarray | None = None) -> SortedViewRecord:
    """Stable ascending order by parsed time; ties keep source order; unparsed rows go last in source order."""
    sel = index.src_rows() if rows is None else np.asarray(rows, dtype=np.int64)
    ns = index.ts_ns[sel - 1]
    unparsed = index.ts_status[sel - 1] != 0
    key = np.where(unparsed, np.iinfo(np.int64).max, ns)
    order = sel[np.argsort(key, kind="stable")]
    ids = [int(r) for r in order]
    return SortedViewRecord(index.file_key, tuple(ids), int(unparsed.sum()), str(_reuse.canonical().sha256_json(ids)))


def apply_order(frame: pd.DataFrame, record: SortedViewRecord) -> pd.DataFrame:
    """Reorder a frame with ``_src_row`` by a recorded permutation (rows absent from the frame are skipped)."""
    pos = {r: i for i, r in enumerate(record.order)}
    missing = [r for r in frame["_src_row"] if r not in pos]
    if missing:
        raise DataConfigError("frame contains rows that are not part of the recorded permutation")
    out = frame.iloc[np.argsort(frame["_src_row"].map(pos).to_numpy(), kind="stable")].reset_index(drop=True)
    out.attrs.update(
        {"layer": record.layer, "provenance": record.provenance, "permutation_sha256": record.permutation_sha256}
    )
    return out
