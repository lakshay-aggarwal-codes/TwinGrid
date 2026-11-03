"""Phase 2 review corrections: one regression group per correction. Synthetic fixtures only."""

import ast
import dataclasses
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import p2_fixtures as p2
import pandas as pd
import pytest
import synthetic_fixtures as fx

from research.danish_aau.evaluation import cli, stages  # noqa: F401  (registers 'preflight' and 'prepare')
from research.danish_aau.evaluation.config import load_config
from research.danish_aau.evaluation.data_layer import alignment as alignment_module
from research.danish_aau.evaluation.data_layer import timeparse
from research.danish_aau.evaluation.data_layer.alignment import AlignmentSpec, TimedSeries, align
from research.danish_aau.evaluation.data_layer.config import KNOWN_REDUCERS, load_data_config, parse_data_config
from research.danish_aau.evaluation.data_layer.errors import (
    AlignmentError,
    ClockMismatchError,
    DataConfigError,
    PolicyNotApproved,
    ReaderError,
)
from research.danish_aau.evaluation.data_layer.observations import ObservationStream
from research.danish_aau.evaluation.data_layer.policies import DerivedView
from research.danish_aau.evaluation.data_layer.vocabulary import AlignmentStrategy, Layer, Provenance, TimeBasis
from research.danish_aau.evaluation.manifest import CLAIMS, MANIFEST_NAME, verify_manifest
from research.danish_aau.evaluation.paths import DANISH_AAU_DIR, PACKAGE_DIR, REPO_ROOT
from research.danish_aau.evaluation.runner import RunContext, run_pipeline

NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
EXACT, NEAREST, BACKWARD, BUCKET = (
    AlignmentStrategy.EXACT,
    AlignmentStrategy.NEAREST,
    AlignmentStrategy.BACKWARD_ASOF,
    AlignmentStrategy.BUCKET,
)
DAMPER, P_SUP, P_EXT, F_SUP, F_EXT, T_SUP = p2.VENT_COLUMNS
E = ""


# ------------------------------------------------------------------------------------------------ helpers
def three_pattern_rows():
    """Ventilation-like file in the shape found locally: every row populates exactly one of three disjoint column sets."""
    a, b, c = ("1", E, E, E, E, E), (E, E, E, "2", "3", "4"), (E, "5", "6", E, E, E)
    layout = [a, a, b, c, a, b, c, a]
    return [[f"2024-09-16 16:{45 + 2 * i}:00", *cells] for i, cells in enumerate(layout)]


def vent_reader(tmp_path, chunksize=3):
    return p2.build_reader(tmp_path, p2.VENT_KEY, p2.VENT_HEADER, three_pattern_rows(), chunksize=chunksize)[0]


def obs(name, times, values, *, conflict=None, clock="clk", origin=None, basis=TimeBasis.ELAPSED):
    t = np.asarray(times, dtype=float)
    frame = pd.DataFrame(
        {
            "_src_row": np.arange(1, len(t) + 1),
            "_elapsed_s": t,
            "_ts_ns": np.where(
                np.isfinite(t), np.round(np.nan_to_num(t, posinf=0, neginf=0) * 1e9), np.iinfo(np.int64).min
            ).astype(np.int64),
            "val": np.asarray(values, dtype=float),
            "_dup_conflict": np.zeros(len(t), dtype=bool) if conflict is None else np.asarray(conflict, dtype=bool),
        }
    )
    return TimedSeries.from_observations(
        frame, layer=Layer.L1_OBSERVED, basis=basis, clock_id=clock, name=name, origin_text=origin
    )


def sim(name, times, *, clock="clk", origin=None):
    frame = pd.DataFrame({"t": np.asarray(times, dtype=float), "val": 0.0})
    return TimedSeries.from_simulated(frame, elapsed_s_col="t", name=name, clock_id=clock, origin_text=origin)


def bucket(**kw):
    return AlignmentSpec(
        BUCKET, bucket_width_s=4, reducer="count", approved_reducers=("count", "min", "max", "mean"), **kw
    )


def col(res, name):
    return res.frame[name].tolist()


# ================================================================================================ 1. population patterns
def test_census_lists_the_exact_populated_column_signatures(tmp_path):
    reader = vent_reader(tmp_path)
    census = reader.index.pattern_census()
    assert [p["populated_columns"] for p in census] == [
        [DAMPER],
        [F_SUP, F_EXT, T_SUP],
        [P_SUP, P_EXT],
    ]  # first appearance, file column order
    assert [(p["n_rows"], p["first_src_row"], p["last_src_row"]) for p in census] == [(4, 1, 8), (2, 3, 6), (2, 4, 7)]
    assert [(p["first_timestamp_text"], p["last_timestamp_text"]) for p in census] == [
        ("2024-09-16 16:45:00", "2024-09-16 16:59:00"),
        ("2024-09-16 16:49:00", "2024-09-16 16:55:00"),
        ("2024-09-16 16:51:00", "2024-09-16 16:57:00"),
    ]
    assert [p["n_populated_columns"] for p in census] == [1, 3, 2] and [p["pattern_id"] for p in census] == [0, 1, 2]


def test_every_row_keeps_its_source_identity_and_pattern_id(tmp_path):
    reader = vent_reader(tmp_path)
    assert list(reader.index.pattern_id) == [0, 0, 1, 2, 0, 1, 2, 0]
    assert list(reader.index.pattern_rows(0)) == [1, 2, 5, 8] and list(reader.index.pattern_rows(2)) == [4, 7]
    frame = p2.frame_of(reader)
    assert list(frame["_src_row"]) == list(range(1, 9)) and list(frame["_pattern_id"]) == [0, 0, 1, 2, 0, 1, 2, 0]
    assert list(reader.index.to_frame()["_pattern_id"]) == list(
        frame["_pattern_id"]
    )  # the same ids are in the time-index sidecar


def test_no_row_is_full_or_empty_in_the_locally_observed_shape(tmp_path):
    idx = vent_reader(tmp_path).index
    assert idx.completeness_counts() == {"FULL": 0, "PARTIAL": 8, "EMPTY": 0}


def test_per_column_missing_counts_are_preserved_and_agree_with_the_patterns(tmp_path):
    idx = vent_reader(tmp_path).index
    assert idx.summary()["missing_by_column"] == {DAMPER: 4, P_SUP: 6, P_EXT: 6, F_SUP: 6, F_EXT: 6, T_SUP: 6}
    for column, missing in idx.missing_by_column.items():  # missing = rows whose pattern does not contain the column
        rows_with_column = sum(p["n_rows"] for p in idx.pattern_census() if column in p["populated_columns"])
        assert missing == idx.n_rows - rows_with_column


@pytest.mark.parametrize("chunksize", [1, 2, 3, 5, 50_000])
def test_the_census_does_not_depend_on_the_chunk_size(tmp_path, chunksize):
    ref = vent_reader(tmp_path / "ref", 50_000).index.pattern_census()
    assert vent_reader(tmp_path / "got", chunksize).index.pattern_census() == ref


def test_the_census_describes_and_does_not_interpret(tmp_path):
    census = vent_reader(tmp_path).index.pattern_census()
    forbidden = ("simultan", "schedule", "cadence", "interval", "synchron", "downtime", "mcar", "mechanism", "reason")
    assert not [k for p in census for k in p if any(w in k.lower() for w in forbidden)]
    assert set(census[0]) == {
        "pattern_id",
        "populated_columns",
        "n_populated_columns",
        "n_rows",
        "first_src_row",
        "last_src_row",
        "first_timestamp_text",
        "last_timestamp_text",
    }


def test_window_counts_per_pattern_are_descriptive(tmp_path):
    reader = vent_reader(tmp_path)
    win = reader.window_ns(("2024-09-16 16:47:00", "2024-09-16 16:53:00"))  # rows 2 (A), 3 (B), 4 (C), 5 (A)
    assert [p["n_rows_in_window"] for p in reader.index.summary(win)["population_patterns"]] == [2, 1, 1]
    assert "in_window_full_rows" not in reader.index.summary(win)


def test_a_single_fully_populated_file_has_one_pattern_listing_every_column(tmp_path):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.main_rows(4), chunksize=2)[0]
    census = reader.index.pattern_census()
    assert len(census) == 1 and census[0]["populated_columns"] == p2.MAIN_HEADER[1:] and census[0]["n_rows"] == 4


def test_empty_rows_form_their_own_pattern_and_the_l2_view_excludes_nothing_when_there_are_none(tmp_path):
    reader = vent_reader(tmp_path)
    view = DerivedView(ObservationStream.open(reader), "keep_all_ordered", "exclude_empty_rows")
    assert view.empty_ledger.count == 0 and len(view.to_frame(confirm=True)) == 8  # PARTIAL rows are all kept
    with_empty = p2.build_reader(
        tmp_path / "e", p2.VENT_KEY, p2.VENT_HEADER, [["2024-09-16 16:45:00", *([E] * 6)], *three_pattern_rows()[:1]]
    )[0]
    assert [p["populated_columns"] for p in with_empty.index.pattern_census()] == [[], [DAMPER]]


def test_prepare_reports_the_census_and_writes_the_pattern_id_sidecar(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    p2.write_source(raw, p2.VENT_KEY, p2.VENT_HEADER, three_pattern_rows())
    cfg = fx.write_config(tmp_path / "c.toml", raw)
    ctx = _ctx(tmp_path, raw, cfg)
    run_pipeline(ctx, ["prepare"], [], now=NOW)
    report = json.loads((ctx.run_dir / "stage_prepare.json").read_text(encoding="utf-8"))
    ti = report["files"][p2.VENT_KEY]["time_index"]
    assert ti["n_population_patterns"] == 3 and ti["completeness_counts"] == {"FULL": 0, "PARTIAL": 8, "EMPTY": 0}
    assert "_pattern_id" in pd.read_csv(ctx.run_dir / f"time_index_{p2.VENT_KEY}.csv").columns


# ================================================================================================ 2. reducers and bucket duplicates
def test_only_the_four_authorised_reducers_exist():
    assert KNOWN_REDUCERS == ("count", "min", "max", "mean")
    assert load_data_config(DANISH_AAU_DIR / "config" / "data.toml").policies.approved_bucket_reducers == ()


@pytest.mark.parametrize("name", ["first", "last", "median", "sum", "std"])
def test_other_reducers_are_rejected_everywhere(name):
    with pytest.raises(DataConfigError):
        parse_data_config({"policies": {"approved_bucket_reducers": [name]}})
    with pytest.raises(AlignmentError):  # reducer unknown, even if someone lists it as approved
        align(
            sim("s", [1]),
            obs("m", [1], [1]),
            AlignmentSpec(BUCKET, bucket_width_s=2, reducer=name, approved_reducers=(name, "count")),
        )
    with pytest.raises(AlignmentError):  # approving a non-existent reducer is itself an error
        align(
            sim("s", [1]),
            obs("m", [1], [1]),
            AlignmentSpec(BUCKET, bucket_width_s=2, reducer="count", approved_reducers=("count", name)),
        )
    with pytest.raises(AlignmentError):  # and the implementation has no such branch
        alignment_module._reduce(name, np.array([1.0, 2.0]))


@pytest.mark.parametrize(("reducer", "value"), [("count", 4.0), ("min", 2.0), ("max", 5.0), ("mean", 3.5)])
def test_authorised_reducers_still_work_and_each_needs_its_own_approval(reducer, value):
    src = obs("m", np.arange(1, 11), np.arange(1, 11))
    spec = AlignmentSpec(BUCKET, bucket_width_s=4, reducer=reducer, approved_reducers=(reducer,))
    assert align(sim("s", [5.0]), src, spec).frame["source__val"].iloc[0] == value
    with pytest.raises(PolicyNotApproved):
        align(sim("s", [5.0]), src, AlignmentSpec(BUCKET, bucket_width_s=4, reducer=reducer, approved_reducers=()))


@pytest.mark.parametrize("reducer", ["count", "min", "max", "mean"])
@pytest.mark.parametrize(
    ("flags", "reason"), [([False, False], "duplicate_source_timestamps"), ([True, True], "conflicting_duplicates")]
)
def test_a_bucket_containing_duplicate_timestamps_is_ambiguous_and_never_reduced(reducer, flags, reason):
    src = obs("m", [1, 2, 2, 3], [10, 20, 30, 40], conflict=[False, *flags, False])  # rows 2 and 3 share a timestamp
    spec = AlignmentSpec(BUCKET, bucket_width_s=4, reducer=reducer, approved_reducers=(reducer,))
    res = align(sim("s", [3.0]), src, spec)
    assert col(res, "align_status") == ["ambiguous"] and col(res, "align_reason") == [reason]
    assert col(res, "align_source_rows") == ["1;2;3;4"] and col(res, "align_n_candidates") == [
        4
    ]  # all row ids preserved
    assert np.isnan(res.frame["source__val"].iloc[0])  # no count, min, max or mean of the duplicates
    assert col(res, "align_n_conflict_rows") == [sum(flags)]


def test_duplicates_only_make_the_buckets_that_contain_them_ambiguous():
    src = obs("m", [1, 1, 5, 6], [10, 11, 50, 60], conflict=[True, True, False, False])
    res = align(sim("s", [1.0, 5.0, 6.0, 20.0]), src, bucket())
    # (−3,1] holds both rows at t=1; (1,5] holds only the row at 5; (2,6] holds rows 5 and 6; (16,20] is empty.
    assert col(res, "align_status") == ["ambiguous", "matched", "matched", "unmatched"]
    assert col(res, "align_reason") == ["conflicting_duplicates", "", "", "no_candidate"]
    assert col(res, "source__val")[1:3] == [1.0, 2.0] and np.isnan(res.frame["source__val"].iloc[0])


def test_distinct_timestamps_in_a_bucket_are_still_reduced():
    res = align(
        sim("s", [5.0]),
        obs("m", np.arange(1, 11), np.arange(1, 11)),
        AlignmentSpec(BUCKET, bucket_width_s=4, reducer="mean", approved_reducers=("mean",)),
    )
    assert col(res, "align_status") == ["matched"] and col(res, "source__val") == [3.5]


# ================================================================================================ 3. elapsed clocks and finite numbers
def test_elapsed_series_on_different_clocks_need_an_explicit_relationship():
    with pytest.raises(ClockMismatchError) as e:
        align(sim("s", [1.0], clock="twin"), obs("m", [1.0], [1.0], clock="aau"), AlignmentSpec(EXACT))
    assert "no relationship is stated" in str(e.value)


def test_a_declared_offset_is_an_explicit_relationship_and_zero_is_a_deliberate_claim():
    for offset in (0.0, -100.0):
        res = align(
            sim("s", [1.0], clock="twin"),
            obs("m", [101.0 + offset], [1.0], clock="aau"),
            AlignmentSpec(EXACT, source_offset_s=offset),
        )
        clock = res.provenance.config["clock"]
        assert (
            clock["offset_basis"] == "declared_offset"
            and clock["source_offset_declared"] is True
            and clock["source_offset_s"] == offset
        )
    assert col(
        align(
            sim("s", [1.0], clock="twin"),
            obs("m", [1.0], [1.0], clock="aau"),
            AlignmentSpec(EXACT, source_offset_s=0.0),
        ),
        "align_status",
    ) == ["matched"]


def test_an_equal_stated_origin_is_an_explicit_relationship():
    origin = "2024-09-17 09:40:00"
    res = align(
        sim("s", [1.0], clock="twin", origin=origin),
        obs("m", [1.0], [1.0], clock="aau", origin=origin),
        AlignmentSpec(EXACT),
    )
    assert res.provenance.config["clock"]["offset_basis"] == "shared_origin_text" and col(res, "align_status") == [
        "matched"
    ]


@pytest.mark.parametrize(
    ("t_origin", "s_origin"),
    [
        (None, None),
        ("2024-09-17 09:40:00", None),
        (None, "2024-09-17 09:40:00"),
        ("2024-09-17 09:40:00", "2024-09-17 09:41:00"),
    ],
)
def test_different_clocks_without_a_shared_origin_or_offset_are_refused(t_origin, s_origin):
    with pytest.raises(ClockMismatchError):
        align(
            sim("s", [1.0], clock="twin", origin=t_origin),
            obs("m", [1.0], [1.0], clock="aau", origin=s_origin),
            AlignmentSpec(EXACT),
        )


def test_the_same_clock_id_with_conflicting_origins_is_refused():
    with pytest.raises(ClockMismatchError):
        align(
            sim("s", [1.0], origin="2024-09-17 09:40:00"),
            obs("m", [1.0], [1.0], origin="2024-09-18 00:00:00"),
            AlignmentSpec(EXACT, source_offset_s=0.0),
        )


def test_the_same_clock_id_needs_no_declaration_and_is_recorded_as_such():
    res = align(sim("s", [1.0]), obs("m", [1.0], [1.0]), AlignmentSpec(EXACT))
    assert (
        res.provenance.config["clock"]["offset_basis"] == "same_clock_id"
        and res.provenance.config["source_offset_s"] is None
    )


@pytest.mark.parametrize("field", ["tolerance_s", "source_offset_s", "bucket_width_s"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "1.0", True])
def test_non_finite_and_non_numeric_parameters_are_rejected(field, bad):
    good = AlignmentSpec(
        BUCKET, bucket_width_s=4.0, reducer="count", approved_reducers=("count",), tolerance_s=1.0, source_offset_s=0.0
    )
    good.validate()  # the baseline is valid
    spec = dataclasses.replace(good, **{field: bad})
    with pytest.raises(AlignmentError):
        spec.validate()
    with pytest.raises(AlignmentError):
        align(sim("s", [1.0]), obs("m", [1.0], [1.0]), spec)


def test_validation_applies_whatever_the_strategy():
    for kw in ({"tolerance_s": float("nan")}, {"source_offset_s": float("inf")}):
        with pytest.raises(AlignmentError):
            AlignmentSpec(EXACT, **kw).validate()
    with pytest.raises(AlignmentError):
        AlignmentSpec(EXACT, source_offset_s=1e12).validate()


def test_infinity_is_only_available_through_the_explicit_opt_in():
    with pytest.raises(AlignmentError):
        AlignmentSpec(BACKWARD, tolerance_s=float("inf")).validate()
    res = align(sim("s", [100.0]), obs("m", [0.0], [1.0]), AlignmentSpec(BACKWARD, allow_unbounded=True))
    assert col(res, "align_status") == ["matched"]


def test_non_finite_elapsed_values_are_invalid_times_not_garbage():
    target = sim("s", [1.0, np.inf, -np.inf, np.nan, 1e12])
    source = obs("m", [1.0, np.inf, np.nan, -np.inf], [1, 2, 3, 4])
    res = align(target, source, AlignmentSpec(EXACT))
    assert col(res, "align_status") == ["matched", "unmatched", "unmatched", "unmatched", "unmatched"]
    assert (
        col(res, "align_reason")[1:] == ["target_time_invalid"] * 4
        and res.provenance.config["n_source_rows_with_invalid_time"] == 3
    )
    assert (target.frame["_t_ns"].iloc[1:] == np.iinfo(np.int64).min).all()


def test_timezone_aware_series_remain_blocked():
    frame = pd.DataFrame({"_src_row": [1], "_t_ns": [0], "v": [1.0]})
    aware = TimedSeries("aw", Layer.L1_OBSERVED, Provenance.MEASURED, TimeBasis.TZ_AWARE, "c", frame)
    with pytest.raises(ClockMismatchError) as e:
        align(aware, aware, AlignmentSpec(EXACT, source_offset_s=0.0))
    assert "TimeMapping" in str(e.value)


# ================================================================================================ 4. two-pass content integrity
def _reader(tmp_path, chunksize=2, n=6):
    return p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.main_rows(n), chunksize=chunksize)[0]


def _edit_cell(reader, row, old, new):
    """Replace one cell text with another of the SAME length, byte-exactly (no newline translation, so the file length is
    unchanged on every platform; text-mode rewrites turn LF into CRLF on Windows)."""
    path = reader.source.path
    data = path.read_bytes()
    lines = data.split(b"\n")
    old_b, new_b = old.encode("utf-8"), new.encode("utf-8")
    assert old_b in lines[row], lines[row]  # data row k is line k (line 0 is the header)
    assert len(old_b) == len(new_b)
    lines[row] = lines[row].replace(old_b, new_b, 1)
    path.write_bytes(b"\n".join(lines))
    assert len(path.read_bytes()) == len(data)  # the edit really did not change the file length


@pytest.mark.parametrize("row", [1, 2, 3, 4, 5, 6])
def test_a_changed_measurement_with_an_unchanged_timestamp_and_length_is_detected(tmp_path, row):
    reader = _reader(tmp_path)
    original = p2.main_rows(6)[row - 1][1]  # "100.0", "101.0", ...
    _edit_cell(reader, row, f",{original},", f",{int(float(original)) + 800}.0,")  # same cell length, same timestamp
    with pytest.raises(ReaderError) as e:
        list(reader.iter_chunks())
    assert "content of column 'Power Ch 1 (W)'" in str(e.value) and "changed between passes" in str(e.value)


def test_the_documented_scenario_exactly(tmp_path):
    """Change one measurement value after pass 1 without changing the timestamp or the cell (or file) length.
    Run on LF files (as the fixtures write them) and on CRLF files (as a Windows checkout has them)."""
    for name, newline in (("lf", "\n"), ("crlf", "\r\n")):
        reader = p2.build_reader(
            tmp_path / name, p2.MAIN_KEY, p2.MAIN_HEADER, p2.main_rows(6), chunksize=3, newline=newline
        )[0]
        before = reader.source.path.read_bytes()
        _edit_cell(reader, 2, ",101.0,", ",901.0,")
        after = reader.source.path.read_bytes()
        assert len(before) == len(after) and before != after, name  # same length, one measurement value different
        assert (b"\r\n" in before) == (newline == "\r\n"), name  # the fixture really has the requested line endings
        assert reader.index.ts_text[1] == p2.main_rows(6)[1][0], name  # the timestamp is the same
        with pytest.raises(ReaderError):
            list(reader.iter_chunks(["Power Ch 1 (W)"]))


@pytest.mark.parametrize("chunksize", [1, 2, 4, 50_000])
def test_detection_does_not_depend_on_the_chunk_size(tmp_path, chunksize):
    reader = _reader(tmp_path, chunksize)
    _edit_cell(reader, 5, ",104.0,", ",904.0,")
    with pytest.raises(ReaderError):
        list(reader.iter_chunks())


def test_a_changed_row_that_the_row_selection_would_skip_is_still_detected(tmp_path):
    reader = _reader(tmp_path)
    _edit_cell(reader, 6, ",105.0,", ",905.0,")
    with pytest.raises(ReaderError):
        list(reader.iter_chunks(src_rows=[1]))  # the chunk holding row 6 is read and verified


def test_swapping_two_values_within_a_column_is_detected(tmp_path):
    reader = _reader(tmp_path)
    path = reader.source.path
    lines = path.read_text(encoding="utf-8").split("\n")
    lines[1], lines[2] = lines[1].replace(",100.0,", ",101.0,", 1), lines[2].replace(",101.0,", ",100.0,", 1)
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ReaderError):
        list(reader.iter_chunks(["Power Ch 1 (W)"]))


def test_an_unchanged_file_passes_and_the_timestamp_check_is_kept(tmp_path):
    reader = _reader(tmp_path)
    assert sum(len(c) for c in reader.iter_chunks()) == 6
    summary = reader.verify_integrity()
    assert summary == {"columns_verified": 3, "rows": 6, "chunks": 3, "timestamp_column_verified": True}
    path = reader.source.path
    path.write_text(path.read_text(encoding="utf-8").replace(p2.ts(2), p2.ts(9)), encoding="utf-8")
    with pytest.raises(ReaderError) as e:
        list(reader.iter_chunks())
    assert "timestamps differ from pass 1" in str(e.value)


def test_pass_two_does_not_claim_to_verify_columns_it_does_not_read(tmp_path):
    """Honest scope: a change in an UNREAD column is not seen by pass 2; verify_integrity() covers every column."""
    reader = _reader(tmp_path)
    _edit_cell(reader, 3, ",202.0,", ",902.0,")  # 'Power Ch 2 (W)'
    assert sum(len(c) for c in reader.iter_chunks(["Power Ch 1 (W)"])) == 6  # not detected: that column was not read
    with pytest.raises(ReaderError) as e:
        reader.verify_integrity()
    assert "Power Ch 2 (W)" in str(e.value)
    with pytest.raises(ReaderError):
        list(reader.iter_chunks(["Power Ch 2 (W)"]))  # but reading it does detect the change


def test_verify_integrity_can_be_limited_and_validates_its_arguments(tmp_path):
    reader = _reader(tmp_path)
    assert reader.verify_integrity(["Power Ch 1 (W)"])["columns_verified"] == 1
    for bad in (["nope"], ["Time [Date/Time]"]):
        with pytest.raises(DataConfigError):
            reader.verify_integrity(bad)


def test_added_or_removed_rows_and_changed_headers_are_detected(tmp_path):
    reader = _reader(tmp_path)
    path = reader.source.path
    original = path.read_text(encoding="utf-8")
    path.write_text(original + ",".join(p2.main_rows(1, start=30)[0]) + "\n", encoding="utf-8")
    with pytest.raises(ReaderError):
        list(reader.iter_chunks())
    path.write_text("\n".join(original.split("\n")[:-2]) + "\n", encoding="utf-8")
    with pytest.raises(ReaderError):
        list(reader.iter_chunks())
    path.write_text(original.replace("Power Ch 1 (W)", "Power Ch 9 (W)", 1), encoding="utf-8")
    with pytest.raises(ReaderError):
        list(reader.iter_chunks(["Power Ch 1 (W)"]))


def test_the_stage_reports_which_columns_pass_two_verified(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    p2.write_source(raw, p2.MAIN_KEY, p2.MAIN_HEADER, p2.main_rows(5))
    cfg = fx.write_config(tmp_path / "c.toml", raw)
    ctx = _ctx(tmp_path, raw, cfg)
    run_pipeline(ctx, ["prepare"], [], now=NOW)
    sc = json.loads((ctx.run_dir / "stage_prepare.json").read_text(encoding="utf-8"))["files"][p2.MAIN_KEY][
        "stream_check"
    ]
    assert sc["content_integrity_verified_columns"] == 3 and sc["content_integrity_unverified_columns"] == []


# ================================================================================================ 5. timezone-suffixed text
LITERAL_Z = ("%Y-%m-%dT%H:%M:%SZ",)
NAIVE = ("%Y-%m-%d %H:%M:%S",)


def _status(text, formats=NAIVE):
    return int(timeparse.parse_naive_timestamps(pd.Series([text]), formats)[1][0])


@pytest.mark.parametrize(
    ("text", "formats"),
    [
        ("2024-01-01T12:00:00Z", LITERAL_Z),  # the configured format itself contains a literal Z
        ("2024-01-01T12:00:00z", ("%Y-%m-%dT%H:%M:%Sz",)),
        ("2024-01-01 12:00:00Z", ("%Y-%m-%d %H:%M:%SZ",)),
        ("2024-01-01 12:00:00+02:00", ("%Y-%m-%d %H:%M:%S+02:00",)),  # a literal offset in the format
        ("2024-01-01 12:00:00-0500", ("%Y-%m-%d %H:%M:%S-0500",)),
        ("2024-01-01 12:00:00 -0500", ("%Y-%m-%d %H:%M:%S -0500",)),
        ("2024-01-01 12:00:00+02", ("%Y-%m-%d %H:%M:%S+02",)),
        ("2024-01-01 12:00:00 UTC", ("%Y-%m-%d %H:%M:%S UTC",)),
        ("2024-01-01 12:00:00.5Z", ("%Y-%m-%d %H:%M:%S.%fZ",)),
        ("2024-01-01 12:00Z", ("%Y-%m-%d %H:%MZ",)),
        ("2024-01-01 12:00:00Z", NAIVE),
        ("2024-01-01 12:00:00+02:00", NAIVE),
        ("2024-01-01 12:00:00-0500", NAIVE),
    ],
)
def test_timezone_suffixed_text_is_rejected_whatever_the_configured_format(text, formats):
    ns, status = timeparse.parse_naive_timestamps(pd.Series([text]), formats)
    assert status[0] == timeparse.TZ_SUFFIX and ns[0] == timeparse.NAT_NS
    assert timeparse.STATUS_NAMES[timeparse.TZ_SUFFIX] == "tz_suffix_rejected"


@pytest.mark.parametrize(
    ("text", "formats"),
    [
        ("2024-01-01 12:00:00", NAIVE),
        ("2024-09-17 09:40:00", NAIVE),
        ("2024-09-17 09:40", ("%Y-%m-%d %H:%M",)),
        ("2024-09-17", ("%Y-%m-%d",)),  # a date alone has no time component, so its "-17" is not an offset
        ("2024-01-01 12:00:00.250", ("%Y-%m-%d %H:%M:%S.%f",)),
        ("17/09/2024 09:40:00", ("%d/%m/%Y %H:%M:%S",)),
    ],
)
def test_normal_naive_timestamps_are_still_accepted(text, formats):
    assert _status(text, formats) == timeparse.OK


def test_rejected_text_is_kept_and_counted_in_the_time_index(tmp_path):
    rows = [
        [p2.ts(0), "1", "1", "1"],
        ["2024-09-17 09:40:01Z", "2", "2", "2"],
        ["2024-09-17 09:40:02+02:00", "3", "3", "3"],
        ["2024-09-17 09:40:03-0500", "4", "4", "4"],
        [p2.ts(4), "5", "5", "5"],
    ]
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, rows, chunksize=2)[0]
    s = reader.index.summary()
    assert s["n_timestamp_ok"] == 2 and s["n_timestamp_tz_suffix_rejected"] == 3 and s["n_timestamp_parse_errors"] == 0
    frame = p2.frame_of(reader)
    assert frame["_ts_status"].tolist() == [
        "ok",
        "tz_suffix_rejected",
        "tz_suffix_rejected",
        "tz_suffix_rejected",
        "ok",
    ]
    assert frame["_ts_text"].tolist()[1:4] == [r[0] for r in rows[1:4]]  # original text untouched
    assert len(frame) == 5 and frame["_ts_ns"].iloc[1] == np.iinfo(np.int64).min  # no value was derived from it
    assert list(reader.index.delta_s[~np.isnan(reader.index.delta_s)]) == [
        4.0
    ]  # rejected rows are not part of the time axis


def test_a_data_config_with_a_literal_z_format_still_cannot_admit_a_zone(tmp_path):
    cfg = parse_data_config({"reader": {"timestamp_formats": ["%Y-%m-%dT%H:%M:%SZ"]}})
    rows = [["2024-01-01T12:00:00Z", "1", "1", "1"], ["2024-01-01T12:00:01Z", "2", "2", "2"]]
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, rows, cfg=cfg)[0]
    assert (
        reader.index.summary()["n_timestamp_ok"] == 0 and reader.index.summary()["n_timestamp_tz_suffix_rejected"] == 2
    )


def test_numeric_timezone_directives_in_a_format_are_still_rejected_by_the_config():
    with pytest.raises(DataConfigError):
        parse_data_config({"reader": {"timestamp_formats": ["%Y-%m-%d %H:%M:%S%z"]}})


# ================================================================================================ 6. generated-artifact integrity
def _ctx(tmp_path, raw, cfg, run_id="r1"):
    return RunContext(
        config=load_config(cfg),
        config_path="c.toml",
        repo_root=REPO_ROOT,
        raw_dir=raw,
        raw_dir_source="cli",
        run_dir=tmp_path / "out" / run_id,
        run_id=run_id,
    )


@pytest.fixture
def artifact_run(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    p2.write_source(raw, p2.MAIN_KEY, p2.MAIN_HEADER, p2.DUP_ROWS)
    p2.write_source(raw, p2.VENT_KEY, p2.VENT_HEADER, [["2024-09-16 16:45:00", *([E] * 6)], *three_pattern_rows()])
    cfg = fx.write_config(tmp_path / "c.toml", raw)
    ctx = _ctx(tmp_path, raw, cfg)
    manifest, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    assert code == 0
    return ctx, raw, cfg, manifest


def _report(ctx):
    return json.loads((ctx.run_dir / "stage_prepare.json").read_text(encoding="utf-8"))


def test_each_generated_artifact_has_a_relative_path_size_and_sha256(artifact_run):
    ctx, raw, _, _ = artifact_run
    arts = _report(ctx)["artifacts"]
    assert [a["path"] for a in arts] == sorted(a["path"] for a in arts) and len(arts) >= 5
    assert {a["kind"] for a in arts} == {"time_index", "duplicate_groups", "exclusion_ledger", "provenance"}
    for a in arts:
        data = (ctx.run_dir / a["path"]).read_bytes()
        assert a["size_bytes"] == len(data) and a["sha256"] == hashlib.sha256(data).hexdigest()
        assert not a["path"].startswith(("/", "\\")) and ":" not in a["path"] and ".." not in a["path"].split("/")
    assert sorted(_report(ctx)["outputs"]) == [a["path"] for a in arts]


def test_artifacts_never_include_the_raw_dataset_the_report_or_the_manifest(artifact_run):
    ctx, raw, _, _ = artifact_run
    paths = {a["path"] for a in _report(ctx)["artifacts"]}
    assert (
        not paths & {f.name for f in raw.iterdir()} and "stage_prepare.json" not in paths and MANIFEST_NAME not in paths
    )
    assert not any(str(raw) in json.dumps(a) for a in _report(ctx)["artifacts"])


def test_artifact_listings_are_deterministic_across_runs(artifact_run):
    ctx, raw, cfg, _ = artifact_run
    other = _ctx(ctx.run_dir.parent.parent, raw, cfg, "r2")
    run_pipeline(other, ["prepare"], ["different", "argv"], now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert _report(ctx)["artifacts"] == _report(other)["artifacts"]
    assert (ctx.run_dir / "stage_prepare.json").read_bytes() == (other.run_dir / "stage_prepare.json").read_bytes()


def test_verify_passes_on_an_untouched_run(artifact_run):
    ctx, raw, _, _ = artifact_run
    results = verify_manifest(ctx.run_dir / MANIFEST_NAME, raw)
    assert {r["status"] for r in results} == {"pass"} and next(
        r for r in results if r["check"] == "artifacts_unchanged"
    )["detail"].endswith("verified")


def test_verify_detects_a_modified_artifact(artifact_run):
    ctx, raw, _, _ = artifact_run
    target = ctx.run_dir / _report(ctx)["artifacts"][0]["path"]
    data = bytearray(target.read_bytes())
    data[0] ^= 0x01  # same size, one bit different
    target.write_bytes(bytes(data))
    bad = next(r for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw) if r["check"] == "artifacts_unchanged")
    assert bad["status"] == "fail" and "content changed" in bad["detail"] and target.name in bad["detail"]
    target.write_bytes(bytes(data) + b"x")
    assert (
        "size"
        in next(r for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw) if r["check"] == "artifacts_unchanged")[
            "detail"
        ]
    )


def test_verify_detects_a_missing_artifact(artifact_run):
    ctx, raw, _, _ = artifact_run
    target = ctx.run_dir / _report(ctx)["artifacts"][-1]["path"]
    target.unlink()
    bad = next(r for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw) if r["check"] == "artifacts_unchanged")
    assert bad["status"] == "fail" and f"{target.name}: missing" in bad["detail"]


def test_verify_detects_an_added_output(artifact_run):
    ctx, raw, _, _ = artifact_run
    (ctx.run_dir / "notes.txt").write_text("stray", encoding="utf-8")
    (ctx.run_dir / "sub").mkdir()
    (ctx.run_dir / "sub" / "extra.csv").write_text("a\n", encoding="utf-8")
    bad = next(r for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw) if r["check"] == "artifacts_unchanged")
    assert bad["status"] == "fail" and "notes.txt: added" in bad["detail"] and "sub/extra.csv: added" in bad["detail"]


def test_tampering_with_the_recorded_hashes_is_caught_twice(artifact_run):
    ctx, raw, _, _ = artifact_run
    report_file = ctx.run_dir / "stage_prepare.json"
    doc = json.loads(report_file.read_text(encoding="utf-8"))
    doc["artifacts"][0]["sha256"] = "0" * 64
    report_file.write_text(json.dumps(doc), encoding="utf-8")
    checks = {r["check"]: r["status"] for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw)}
    assert checks["stage_reports_unchanged"] == "fail" and checks["artifacts_unchanged"] == "fail"


def test_unsafe_artifact_paths_in_a_report_are_refused(artifact_run):
    ctx, raw, _, _ = artifact_run
    doc = _report(ctx)
    doc["artifacts"][0]["path"] = "../../etc/passwd"
    (ctx.run_dir / "stage_prepare.json").write_text(json.dumps(doc), encoding="utf-8")
    bad = next(r for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw) if r["check"] == "artifacts_unchanged")
    assert bad["status"] == "fail" and "not a safe relative path" in bad["detail"]


def test_a_preflight_only_run_still_verifies_and_a_stray_file_is_caught(
    tmp_path, raw_dir, fixture_registry, fixture_config
):
    ctx = RunContext(
        config=load_config(fixture_config),
        config_path="f.toml",
        repo_root=REPO_ROOT,
        raw_dir=raw_dir,
        raw_dir_source="cli",
        run_dir=tmp_path / "out" / "pf",
        run_id="pf",
        registry=fixture_registry,
    )
    run_pipeline(ctx, ["preflight"], [], now=NOW)
    assert {r["status"] for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw_dir)} == {"pass"}
    (ctx.run_dir / "stray.json").write_text("{}", encoding="utf-8")
    assert (
        next(r for r in verify_manifest(ctx.run_dir / MANIFEST_NAME, raw_dir) if r["check"] == "artifacts_unchanged")[
            "status"
        ]
        == "fail"
    )


# ================================================================================================ 7. integration corrections
def test_the_claims_notice_and_parser_description_no_longer_say_phase_1():
    assert "Phase 1 harness" not in CLAIMS["notice"] and "Phases 1-2" in CLAIMS["notice"]
    assert CLAIMS["calibrated"] is False and CLAIMS["validated_against_real_data"] is False
    description = cli.build_parser().description
    assert "Phase 1)" not in description and "Phases 1-2" in description


def test_the_vocabulary_module_replaced_types_and_nothing_imports_the_old_name():
    data_layer = PACKAGE_DIR / "data_layer"
    assert (data_layer / "vocabulary.py").is_file() and not (data_layer / "types.py").exists()
    offenders = []
    for path in list((PACKAGE_DIR).rglob("*.py")) + list((DANISH_AAU_DIR / "tests").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[-1] == "types"
                and (node.level or "data_layer" in node.module)
            ):
                offenders.append(path.name)
    assert offenders == []


def test_no_module_in_the_evaluation_tree_shadows_the_standard_library():
    assert cli.find_shadowing_modules(PACKAGE_DIR) == []


def test_the_shadowing_check_flags_a_stale_types_module_and_ignores_dunder_files(tmp_path):
    (tmp_path / "pkg").mkdir()
    for name in ("types.py", "json.py", "__init__.py", "__main__.py", "reader.py"):
        (tmp_path / "pkg" / name).write_text("", encoding="utf-8")
    assert cli.find_shadowing_modules(tmp_path) == ["pkg/json.py", "pkg/types.py"]


def test_doctor_fails_on_a_stale_shadowing_file_and_says_how_to_fix_it(tmp_path, monkeypatch, capsys, fixture_config):
    stale = tmp_path / "evaluation"
    (stale / "data_layer").mkdir(parents=True)
    (stale / "data_layer" / "types.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "PACKAGE_DIR", stale)
    code = cli.main(["doctor", "--config", str(fixture_config)])
    out = capsys.readouterr().out
    assert (
        code == 2
        and "FAIL  no evaluation module shadows a standard-library module" in out
        and "data_layer/types.py" in out
    )
    assert "Remove-Item" in out and out.isascii()


# ================================================================================================ 8. configuration decisions are preserved
def test_the_authorised_configuration_decisions_are_unchanged():
    p1 = load_config(DANISH_AAU_DIR / "config" / "default.toml")
    assert (
        p1.policies.duplicate_timestamps == "undeclared" and p1.timestamps.timezone == "undeclared"
    )  # Phase 1 default untouched
    cfg = load_data_config(DANISH_AAU_DIR / "config" / "data.toml")
    assert cfg.policies.duplicates == "keep_all_ordered"  # Phase 2 data.toml is authoritative for Phase 2
    assert cfg.policies.approved_bucket_reducers == () and cfg.policies.approved_sensitivity == ()  # nothing approved
    assert (
        cfg.reader.non_numeric == "raise"
        and cfg.reader.chunksize == 50_000
        and cfg.timestamps.state == "naive_unspecified"
    )
    raw = (DANISH_AAU_DIR / "config" / "data.toml").read_text(encoding="utf-8")
    assert "timezone" not in raw.replace(
        "no timezone assumed", ""
    )  # no timezone is declared anywhere in the data config


def test_exclude_ambiguous_and_mean_remain_unapproved_by_default(tmp_path):
    with pytest.raises(DataConfigError):
        parse_data_config({"policies": {"duplicates": "exclude_ambiguous"}})
    with pytest.raises(PolicyNotApproved):
        align(sim("s", [1.0]), obs("m", [1.0], [1.0]), AlignmentSpec(BUCKET, bucket_width_s=2, reducer="mean"))
