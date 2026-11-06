"""Phase 2: sparse-ventilation completeness, L2 policies with exclusion ledgers, sorted views, derived-path safety."""

import json

import numpy as np
import p2_fixtures as p2
import pandas as pd
import pytest

from research.danish_aau.evaluation.data_layer.errors import (
    DataConfigError,
    MaterialisationError,
    PolicyNotApproved,
    UnsafeDerivedPath,
)
from research.danish_aau.evaluation.data_layer.observations import ObservationStream
from research.danish_aau.evaluation.data_layer.policies import (
    DerivedView,
    apply_order,
    plan_duplicate_policy,
    stable_time_order,
)
from research.danish_aau.evaluation.data_layer.provenance import ExclusionLedger, ProvenanceLog, safe_output_path
from research.danish_aau.evaluation.paths import REPO_ROOT

E = ""  # an empty (missing) cell
DAMPER, P_SUP, P_EXT, F_SUP, F_EXT, T_SUP = p2.VENT_COLUMNS
VENT_ROWS = [
    ["2024-09-16 16:45:00", E, E, E, E, E, E],  # 1 EMPTY
    ["2024-09-16 16:47:00", "0.0", E, E, E, E, E],  # 2 PARTIAL: the damper-only observation
    ["2024-09-16 16:49:00", E, E, E, E, E, E],  # 3 EMPTY
    ["2024-09-17 09:45:00", "10", "20", "30", "40", "50", "60"],  # 4 FULL
    ["2024-09-17 09:47:00", E, E, E, E, E, E],  # 5 EMPTY
    ["2024-09-17 10:00:00", "11", "21", "31", "41", "51", "61"],  # 6 FULL
    ["2024-09-17 10:15:00", "  ", " ", "  ", " ", "   ", " "],  # 7 whitespace only -> EMPTY
    ["2024-09-17 10:30:00", "0.0", "0.0", "0.0", "0.0", "0.0", "0.0"],  # 8 FULL: zero is a value, not missing
    ["2024-09-17 10:45:00", E, E, E, E, E, "9"],  # 9 PARTIAL
]


def _vent(tmp_path, chunksize=4, cfg=None, rows=None):
    return p2.build_reader(tmp_path, p2.VENT_KEY, p2.VENT_HEADER, rows or VENT_ROWS, chunksize=chunksize, cfg=cfg)[0]


# ------------------------------------------------------------------------------------------ completeness
def test_full_partial_empty_classification(tmp_path):
    idx = _vent(tmp_path).index
    assert idx.completeness_counts() == {"FULL": 3, "PARTIAL": 2, "EMPTY": 4}
    assert list(idx.completeness()) == [
        "EMPTY",
        "PARTIAL",
        "EMPTY",
        "FULL",
        "EMPTY",
        "FULL",
        "EMPTY",
        "FULL",
        "PARTIAL",
    ]
    assert list(idx.n_present) == [0, 1, 0, 6, 0, 6, 0, 6, 1]


def test_missing_counts_per_column_and_zero_is_not_missing(tmp_path):
    s = _vent(tmp_path).index.summary()
    assert s["missing_by_column"] == {DAMPER: 5, P_SUP: 6, P_EXT: 6, F_SUP: 6, F_EXT: 6, T_SUP: 5}
    assert s["n_missing_cells"] == 34 and s["n_expected_measurement_fields"] == 6


def test_the_damper_only_observation_is_preserved_in_l1_and_in_the_l2_valid_view(tmp_path):
    reader = _vent(tmp_path)
    l1 = p2.frame_of(reader)
    assert len(l1) == 9 and l1.loc[1, "_ts_text"] == "2024-09-16 16:47:00" and l1.loc[1, DAMPER] == 0.0
    assert l1.loc[1, "_completeness"] == "PARTIAL" and l1.loc[1, P_SUP:T_SUP].isna().all()
    view = DerivedView(ObservationStream.open(reader), "keep_all_ordered", "exclude_empty_rows")
    l2 = view.to_frame(confirm=True)
    assert 2 in set(l2["_src_row"]) and l2.loc[l2["_src_row"] == 2, "_valid_observation"].item() is True


def test_empty_rows_stay_in_l1_but_leave_the_l2_valid_view_with_a_ledger(tmp_path):
    reader = _vent(tmp_path)
    assert list(p2.frame_of(reader)["_src_row"]) == list(range(1, 10))  # L1 untouched
    view = DerivedView(ObservationStream.open(reader), "keep_all_ordered", "exclude_empty_rows")
    assert list(view.to_frame(confirm=True)["_src_row"]) == [2, 4, 6, 8, 9]
    led = view.empty_ledger
    assert led.excluded_rows == {1, 3, 5, 7} and {e["reason"] for e in led.entries} == {"empty_observation"}
    assert led.summary()["n_excluded"] == 4 and led.summary()["by_reason"] == {"empty_observation": 4}
    assert view.duplicate_ledger.count == 0  # keep_all_ordered removes nothing


def test_keep_empty_flagged_keeps_everything_and_flags_validity(tmp_path):
    view = DerivedView(ObservationStream.open(_vent(tmp_path)), "keep_all_ordered", "keep_empty_flagged")
    frame = view.to_frame(confirm=True)
    assert len(frame) == 9 and view.empty_ledger.count == 0
    assert frame["_valid_observation"].tolist() == [False, True, False, True, False, True, False, True, True]


def test_values_are_never_filled(tmp_path):
    frame = p2.frame_of(_vent(tmp_path))
    assert frame.loc[0, [DAMPER, T_SUP]].isna().all() and frame.loc[3, DAMPER] == 10.0
    assert frame.loc[7, DAMPER] == 0.0 and not np.isnan(frame.loc[7, F_EXT])
    assert frame[DAMPER].isna().sum() == 5  # exactly the missing cells; no forward fill


def test_expected_fields_come_from_the_configuration(tmp_path):
    cfg = p2.make_cfg(files={p2.VENT_KEY: {"measurement_columns": [DAMPER]}})
    idx = _vent(tmp_path, cfg=cfg).index
    assert idx.n_expected == 1 and idx.completeness_counts() == {"FULL": 4, "PARTIAL": 0, "EMPTY": 5}


def test_missing_tokens_are_explicit(tmp_path):
    rows = [["2024-09-17 09:45:00", "NA", "1", "1", "1", "1", "1"]]
    assert _vent(tmp_path, rows=rows).index.completeness_counts()["FULL"] == 1  # default: only "" is missing
    cfg = p2.make_cfg(reader={"na_values": ["", "NA"]}, files={p2.VENT_KEY: {"measurement_columns": p2.VENT_COLUMNS}})
    idx = _vent(tmp_path / "b", cfg=cfg, rows=rows).index
    assert idx.completeness_counts()["PARTIAL"] == 1 and idx.missing_by_column[DAMPER] == 1


def test_no_missingness_mechanism_is_inferred(tmp_path):
    s = _vent(tmp_path).index.summary()
    assert not any(k for k in s if any(w in k.lower() for w in ("mcar", "mar", "downtime", "schedule", "mechanism")))


def test_in_window_counts_use_naive_text_only(tmp_path):
    reader = _vent(tmp_path)
    win = reader.window_ns(("2024-09-17 09:40:00", "2024-09-17 10:20:00"))
    s = reader.index.summary(win)
    assert s["in_window_rows"] == 4 and "in_window_full_rows" not in s  # rows in the window; no FULL interpretation


# ------------------------------------------------------------------------------------------ L2 duplicate policy
def _dup_view(tmp_path, duplicate="keep_all_ordered", approved=(), chunksize=3, empty="keep_empty_flagged"):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.DUP_ROWS, chunksize=chunksize)[0]
    return DerivedView(ObservationStream.open(reader), duplicate, empty, tuple(approved))


def test_keep_all_ordered_is_the_primary_policy_and_removes_nothing(tmp_path):
    view = _dup_view(tmp_path)
    frame = view.to_frame(confirm=True)
    assert list(frame["_src_row"]) == list(range(1, 12))  # all 11 rows, original order
    assert view.duplicate_ledger.count == 0 and view.duplicate_ledger.summary()["n_excluded"] == 0
    rep = view.report()
    assert (
        rep["n_rows_in_view"] == 11
        and rep["n_conflicting_rows_kept"] == 2
        and rep["n_rows_in_duplicate_groups_kept"] == 4
    )
    assert frame.loc[frame["_dup_conflict"], "_src_row"].tolist() == [4, 5]
    assert set(frame["_policy_duplicates"]) == {"keep_all_ordered"}


@pytest.mark.parametrize("policy", ["keep_first", "keep_last", "mean", "average", "dedupe"])
def test_there_is_no_keep_first_keep_last_or_averaging(tmp_path, policy):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.DUP_ROWS)[0]
    with pytest.raises(DataConfigError):
        DerivedView(ObservationStream.open(reader), policy, "keep_empty_flagged")


def test_exclude_ambiguous_requires_explicit_approval(tmp_path):
    with pytest.raises(PolicyNotApproved):
        _dup_view(tmp_path, "exclude_ambiguous")
    with pytest.raises(PolicyNotApproved):
        _dup_view(tmp_path, "exclude_ambiguous", approved=("something_else",))


def test_exclude_ambiguous_produces_a_complete_exclusion_ledger(tmp_path):
    view = _dup_view(tmp_path, "exclude_ambiguous", approved=("exclude_ambiguous",))
    led = view.duplicate_ledger
    assert led.excluded_rows == {4, 5}  # only the CONFLICTING group; the identical pair (rows 3, 9) is not ambiguous
    assert [(e["src_row"], e["dup_group"], e["seq_in_group"], e["reason"]) for e in led.entries] == [
        (4, 1, 1, "conflicting_duplicate_group"),
        (5, 1, 2, "conflicting_duplicate_group"),
    ]
    assert all(e["policy_id"] == "exclude_ambiguous" and e["file_key"] == p2.MAIN_KEY for e in led.entries)
    assert list(view.to_frame(confirm=True)["_src_row"]) == [1, 2, 3, 6, 7, 8, 9, 10, 11]
    assert view.report()["n_excluded"] == 2


def test_the_sensitivity_policy_never_alters_the_primary_view_or_l1(tmp_path):
    primary = _dup_view(tmp_path / "a")
    sens = _dup_view(tmp_path / "b", "exclude_ambiguous", approved=("exclude_ambiguous",))
    assert len(primary.to_frame(confirm=True)) == 11 and len(sens.to_frame(confirm=True)) == 9
    assert len(p2.frame_of(sens.stream.reader)) == 11  # L1 still has everything


def test_ledger_is_independent_of_chunking(tmp_path):
    a = _dup_view(tmp_path / "a", "exclude_ambiguous", ("exclude_ambiguous",), chunksize=1).duplicate_ledger
    b = _dup_view(tmp_path / "b", "exclude_ambiguous", ("exclude_ambiguous",), chunksize=50_000).duplicate_ledger
    assert a.entries == b.entries and a.summary()["sha256"] == b.summary()["sha256"]


def test_plan_duplicate_policy_rejects_unknown_names(tmp_path):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.DUP_ROWS)[0]
    with pytest.raises(DataConfigError):
        plan_duplicate_policy(reader.index, reader.index.src_rows(), "keep_first", ())


def test_l2_to_frame_is_guarded_like_l1(tmp_path):
    view = _dup_view(tmp_path)
    with pytest.raises(MaterialisationError):
        view.to_frame()
    frame = view.to_frame(confirm=True)
    assert frame.attrs["layer"] == "L2" and frame.attrs["provenance"] == "derived"


# ------------------------------------------------------------------------------------------ provenance & ledgers
def test_every_derived_operation_records_its_provenance(tmp_path):
    view = _dup_view(tmp_path, "exclude_ambiguous", ("exclude_ambiguous",), empty="exclude_empty_rows")
    dup_rec, empty_rec = (r.to_dict() for r in view.derivation_records())
    for rec, policy in ((dup_rec, "exclude_ambiguous"), (empty_rec, "exclude_empty_rows")):
        assert rec["operation"] == "l2_policy_view" and rec["policy_id"] == policy
        assert rec["source_files"] == [view.stream.reader.source.relpath]
        assert rec["source_rows"]["count"] == 11 and len(rec["source_rows"]["sha256"]) == 64
        assert rec["transformation"] and rec["config"]["data_config_sha256"] == view.stream.reader.cfg.sha256
        assert rec["output"]["layer"] == "L2" and rec["output"]["provenance"] == "derived"
        assert len(rec["config_sha256"]) == 64 and len(rec["record_sha256"]) == 64
    assert dup_rec["exclusions"]["n_excluded"] == 2 and dup_rec["exclusions"]["by_reason"] == {
        "conflicting_duplicate_group": 2
    }
    assert empty_rec["exclusions"]["n_excluded"] == 0
    assert dup_rec["output"]["n_rows"] == 9


def test_ledger_csv_and_provenance_json_are_written_under_the_run_directory(tmp_path):
    view = _dup_view(tmp_path, "exclude_ambiguous", ("exclude_ambiguous",))
    raw = view.stream.reader.source.raw_dir
    out = tmp_path / "run"
    path = view.duplicate_ledger.write_csv(out / "ledger.csv", raw)
    table = pd.read_csv(path)
    assert list(table["src_row"]) == [4, 5] and {"file_key", "reason", "policy_id"} <= set(table.columns)
    log = ProvenanceLog()
    for rec in view.derivation_records():
        log.add(rec)
    doc = json.loads(log.write_json(out / "prov.json", raw).read_text(encoding="utf-8"))
    assert len(doc["records"]) == 2 and str(tmp_path) not in json.dumps(doc)


def test_derived_outputs_can_never_overlap_the_raw_dataset_or_production_paths(tmp_path):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.main_rows(2))[0]
    raw = reader.source.raw_dir
    ledger = ExclusionLedger("x", "k")
    ledger.add(1, "r")
    for bad in (
        raw / "ledger.csv",
        raw / "sub" / "ledger.csv",
        REPO_ROOT / "src" / "ledger.csv",
        REPO_ROOT / "realData" / "x.csv",
    ):
        with pytest.raises(UnsafeDerivedPath):
            ledger.write_csv(bad, raw)
        with pytest.raises(UnsafeDerivedPath):
            ProvenanceLog().write_json(bad, raw)
    assert sorted(p.name for p in raw.iterdir()) == [reader.source.filename]  # nothing was created next to the raw file
    assert not (raw / "sub").exists() and not (REPO_ROOT / "src" / "ledger.csv").exists()
    assert safe_output_path(tmp_path / "ok" / "f.csv", raw).parent.is_dir()


# ------------------------------------------------------------------------------------------ sorted derived view
def test_sorted_view_is_stable_and_records_its_permutation(tmp_path):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.DUP_ROWS, chunksize=3)[0]
    rec = stable_time_order(reader.index)
    assert list(rec.order) == [1, 2, 3, 9, 4, 5, 6, 7, 8, 10, 11]  # ties keep source order
    assert (
        rec.policy_id == "stable_time_order"
        and rec.layer == "L2"
        and rec.provenance == "derived"
        and len(rec.permutation_sha256) == 64
    )
    assert stable_time_order(reader.index).permutation_sha256 == rec.permutation_sha256
    l1 = p2.frame_of(reader)
    before = l1.copy()
    srt = apply_order(l1, rec)
    assert list(srt["_src_row"]) == list(rec.order) and srt.attrs["permutation_sha256"] == rec.permutation_sha256
    pd.testing.assert_frame_equal(l1, before)  # the original L1 frame is untouched
    assert list(srt.sort_values("_src_row")["_src_row"]) == list(
        range(1, 12)
    )  # original order is recoverable from _src_row


def test_unparsed_rows_sort_last_in_source_order(tmp_path):
    rows = [["garbage", "1", "1", "1"], [p2.ts(5), "1", "1", "1"], ["", "1", "1", "1"], [p2.ts(1), "1", "1", "1"]]
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, rows)[0]
    rec = stable_time_order(reader.index)
    assert list(rec.order) == [4, 2, 1, 3] and rec.n_unparsed_last == 2
    assert rec.to_dict()["n_unparsed_last"] == 2


def test_apply_order_rejects_rows_outside_the_permutation(tmp_path):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.main_rows(4))[0]
    rec = stable_time_order(reader.index, np.array([1, 2]))
    with pytest.raises(DataConfigError):
        apply_order(p2.frame_of(reader), rec)
