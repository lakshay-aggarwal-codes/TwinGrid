"""Phase 2: the alignment engine. Synthetic series only; no scientific comparison is made or implied."""

import json

import numpy as np
import p2_fixtures as p2
import pandas as pd
import pytest

from research.danish_aau.evaluation.data_layer.alignment import AlignmentSpec, TimedSeries, align
from research.danish_aau.evaluation.data_layer.errors import AlignmentError, ClockMismatchError, PolicyNotApproved
from research.danish_aau.evaluation.data_layer.vocabulary import (
    AlignmentStrategy,
    Layer,
    Provenance,
    TimeBasis,
)

EXACT, NEAREST = AlignmentStrategy.EXACT, AlignmentStrategy.NEAREST
BACKWARD, BUCKET = AlignmentStrategy.BACKWARD_ASOF, AlignmentStrategy.BUCKET


def obs(
    name, times, values, *, conflict=None, basis=TimeBasis.ELAPSED, clock="clk", layer=Layer.L1_OBSERVED, col="val"
):
    t = np.asarray(times, dtype=float)
    frame = pd.DataFrame(
        {
            "_src_row": np.arange(1, len(t) + 1),
            "_elapsed_s": t,
            "_ts_ns": np.where(np.isnan(t), np.iinfo(np.int64).min, np.round(np.nan_to_num(t) * 1e9)).astype(np.int64),
            col: np.asarray(values, dtype=float),
            "_dup_conflict": np.zeros(len(t), dtype=bool) if conflict is None else np.asarray(conflict, dtype=bool),
        }
    )
    return TimedSeries.from_observations(frame, layer=layer, basis=basis, clock_id=clock, name=name)


def sim(name, times, values, col="val"):
    return TimedSeries.from_simulated(
        pd.DataFrame({"t": np.asarray(times, dtype=float), col: np.asarray(values, dtype=float)}),
        elapsed_s_col="t",
        name=name,
        clock_id="clk",  # same clock id as obs(): clock relationships are tested explicitly in test_p2_review_corrections.py
    )


def run(target, source, **kw):
    return align(target, source, AlignmentSpec(**kw))


def col(res, name):
    return res.frame[name].tolist()


# ------------------------------------------------------------------------------------------------ exact
def test_exact_matching_with_unmatched_and_ambiguous_rows():
    target = sim("sim", [0, 1, 2, 3, 4, 5], [0, 0, 0, 0, 0, 0])
    source = obs("meas", [0, 1, 1, 3, 5], [10, 11, 12, 13, 15], conflict=[False, True, True, False, False])
    res = run(target, source, strategy=EXACT)
    assert col(res, "align_status") == ["matched", "ambiguous", "unmatched", "matched", "unmatched", "matched"]
    assert col(res, "align_reason") == ["", "conflicting_duplicates", "no_candidate", "", "no_candidate", ""]
    assert col(res, "align_source_rows") == [
        "1",
        "2;3",
        "",
        "4",
        "",
        "5",
    ]  # both conflicting duplicates are listed, none chosen
    assert col(res, "align_n_candidates") == [1, 2, 0, 1, 0, 1]
    vals = res.frame["source__val"].to_numpy()
    assert vals[0] == 10 and vals[3] == 13 and vals[5] == 15
    assert np.isnan(vals[[1, 2, 4]]).all()  # unmatched AND ambiguous rows carry no invented value
    assert col(res, "align_dt_s")[0] == 0.0


def test_identical_duplicates_are_still_ambiguous_but_not_labelled_conflicting():
    res = run(sim("s", [1], [0]), obs("m", [1, 1], [5, 5], conflict=[False, False]), strategy=EXACT)
    assert col(res, "align_status") == ["ambiguous"] and col(res, "align_reason") == ["multiple_candidates"]


def test_every_target_row_is_retained_in_order_even_with_invalid_times():
    target = sim("s", [3, np.nan, 1, 2], [30, 99, 10, 20])
    res = run(target, obs("m", [1, 2, 3], [1, 2, 3]), strategy=EXACT)
    assert len(res.frame) == 4 and col(res, "target__val") == [30, 99, 10, 20]  # original target order and values
    assert col(res, "align_status") == ["matched", "unmatched", "matched", "matched"]
    assert col(res, "align_reason")[1] == "target_time_invalid"


def test_source_rows_with_invalid_time_are_never_candidates_and_are_counted():
    source = obs("m", [1, np.nan, 2], [1, 2, 3])
    res = run(sim("s", [1, 2], [0, 0]), source, strategy=EXACT)
    assert col(res, "align_source_rows") == ["1", "3"] and res.provenance.config["n_source_rows_with_invalid_time"] == 1


def test_empty_source_gives_unmatched_not_an_error():
    res = run(sim("s", [1, 2], [0, 0]), obs("m", [], []), strategy=EXACT)
    assert set(col(res, "align_status")) == {"unmatched"} and set(col(res, "align_reason")) == {"no_source_rows"}


# ------------------------------------------------------------------------------------------------ nearest
def test_nearest_with_tolerance():
    target = sim("s", [0.0, 2.5, 4.0, 7.0, 9.0, 20.0], np.zeros(6))
    source = obs("m", [0, 3, 6, 6, 10], [10, 13, 16, 17, 20])
    res = run(target, source, strategy=NEAREST, tolerance_s=1.0)
    assert col(res, "align_status") == ["matched", "matched", "matched", "ambiguous", "matched", "unmatched"]
    assert col(res, "align_reason") == ["", "", "", "multiple_candidates", "", "outside_tolerance"]
    assert col(res, "align_dt_s")[:3] == [0.0, 0.5, -1.0] and col(res, "align_dt_s")[4] == 1.0
    assert col(res, "align_source_rows")[3] == "3;4"
    assert res.frame["source__val"].iloc[2] == 13


def test_nearest_equidistant_candidates_are_ambiguous_and_both_listed():
    res = run(sim("s", [1.0], [0]), obs("m", [0, 2], [10, 20]), strategy=NEAREST, tolerance_s=1.0)
    assert col(res, "align_status") == ["ambiguous"] and col(res, "align_reason") == ["equidistant_candidates"]
    assert col(res, "align_source_rows") == ["1;2"] and np.isnan(res.frame["source__val"].iloc[0])


def test_nearest_never_matches_outside_the_tolerance():
    res = run(sim("s", [10.0], [0]), obs("m", [0, 20], [1, 2]), strategy=NEAREST, tolerance_s=4.9)
    assert col(res, "align_status") == ["unmatched"] and np.isnan(res.frame["source__val"].iloc[0])
    assert col(
        run(sim("s", [10.0], [0]), obs("m", [0, 20], [1, 2]), strategy=NEAREST, tolerance_s=10.0), "align_status"
    ) == ["ambiguous"]


@pytest.mark.parametrize("kw", [{}, {"tolerance_s": -1.0}])
def test_nearest_requires_an_explicit_non_negative_tolerance(kw):
    with pytest.raises(AlignmentError):
        run(sim("s", [1], [0]), obs("m", [1], [1]), strategy=NEAREST, **kw)


# ------------------------------------------------------------------------------------------------ backward as-of
def test_backward_asof_with_tolerance():
    target = sim("s", [-5, 0, 5, 10, 15, 25, 100], np.zeros(7))
    source = obs("m", [0, 10, 10, 20], [1, 2, 3, 4], conflict=[False, True, True, False])
    res = run(target, source, strategy=BACKWARD, tolerance_s=8.0)
    assert col(res, "align_status") == [
        "unmatched",
        "matched",
        "matched",
        "ambiguous",
        "ambiguous",
        "matched",
        "unmatched",
    ]
    assert col(res, "align_reason") == [
        "no_candidate",
        "",
        "",
        "conflicting_duplicates",
        "conflicting_duplicates",
        "",
        "outside_tolerance",
    ]
    assert (
        col(res, "align_dt_s")[2] == -5.0 and col(res, "align_dt_s")[5] == -5.0
    )  # source time minus target time (never in the future)
    assert (
        res.frame["source__val"].iloc[1] == 1
        and res.frame["source__val"].iloc[2] == 1
        and res.frame["source__val"].iloc[5] == 4
    )


def test_backward_asof_requires_a_tolerance_or_an_explicit_unbounded_opt_in():
    with pytest.raises(AlignmentError):
        run(sim("s", [1], [0]), obs("m", [0], [1]), strategy=BACKWARD)
    res = run(sim("s", [100.0], [0]), obs("m", [0, 20], [1, 4]), strategy=BACKWARD, allow_unbounded=True)
    assert col(res, "align_status") == ["matched"] and col(res, "align_dt_s") == [-80.0]
    assert res.provenance.config["allow_unbounded"] is True


def test_backward_asof_never_uses_a_future_observation():
    res = run(sim("s", [5.0], [0]), obs("m", [6], [1]), strategy=BACKWARD, tolerance_s=100)
    assert col(res, "align_status") == ["unmatched"] and col(res, "align_reason") == ["no_candidate"]


# ------------------------------------------------------------------------------------------------ bucket
APPROVED = ("count", "min", "max", "mean")  # D3: exactly these four are authorised


def _bucket(reducer, source=None, **kw):
    source = source or obs("m", np.arange(1, 11), np.arange(1, 11))
    return run(
        sim("s", [5, 10, 0.5, 20], np.zeros(4)),
        source,
        strategy=BUCKET,
        bucket_width_s=4,
        reducer=reducer,
        approved_reducers=APPROVED,
        **kw,
    )


@pytest.mark.parametrize(
    ("reducer", "expected"),
    [("count", [4, 4]), ("mean", [3.5, 8.5]), ("min", [2, 7]), ("max", [5, 10])],
)
def test_bucket_reduction_with_an_approved_reducer(reducer, expected):
    res = _bucket(reducer)
    assert col(res, "align_status") == ["matched", "matched", "unmatched", "unmatched"]
    assert col(res, "source__val")[:2] == expected and np.isnan(res.frame["source__val"].iloc[2:]).all()
    assert (
        col(res, "align_reason")[2:] == ["no_candidate", "no_candidate"]
        and col(res, "align_source_rows")[0] == "2;3;4;5"
    )


def test_bucket_ignores_nan_values_and_never_fills_them():
    source = obs("m", np.arange(1, 11), [1, 2, np.nan, 4, 5, 6, 7, 8, 9, 10])
    assert _bucket("mean", source).frame["source__val"].iloc[0] == pytest.approx((2 + 4 + 5) / 3)
    assert _bucket("count", source).frame["source__val"].iloc[0] == 3


def test_a_bucket_with_conflicting_duplicate_timestamps_is_ambiguous_not_aggregated():
    source = obs("m", [1, 2, 2, 3], [1, 2, 3, 4], conflict=[False, True, True, False])
    res = run(
        sim("s", [3.0], [0]), source, strategy=BUCKET, bucket_width_s=5, reducer="mean", approved_reducers=APPROVED
    )
    assert col(res, "align_status") == ["ambiguous"] and col(res, "align_reason") == ["conflicting_duplicates"]
    assert col(res, "align_n_conflict_rows") == [2] and col(res, "align_source_rows") == [
        "1;2;3;4"
    ]  # every row id preserved
    assert np.isnan(res.frame["source__val"].iloc[0])  # nothing was reduced


def test_bucket_reduction_requires_an_approved_reducer():
    for approved in ((), ("count",)):
        with pytest.raises(PolicyNotApproved):
            run(
                sim("s", [1], [0]),
                obs("m", [1], [1]),
                strategy=BUCKET,
                bucket_width_s=2,
                reducer="mean",
                approved_reducers=approved,
            )


@pytest.mark.parametrize(
    "kw",
    [{"reducer": "median"}, {"reducer": None}, {"bucket_width_s": None}, {"bucket_width_s": 0}, {"bucket_width_s": -3}],
)
def test_bucket_requires_a_width_and_a_known_reducer(kw):
    params = {"strategy": BUCKET, "bucket_width_s": 2, "reducer": "count", "approved_reducers": APPROVED} | kw
    with pytest.raises(AlignmentError):
        run(sim("s", [1], [0]), obs("m", [1], [1]), **params)


def test_bucket_rejects_non_numeric_source_columns():
    frame = pd.DataFrame({"_src_row": [1], "_elapsed_s": [1.0], "_ts_ns": [10**9], "label": ["x"]})
    src = TimedSeries.from_observations(
        frame, layer=Layer.L1_OBSERVED, basis=TimeBasis.ELAPSED, clock_id="clk", name="m"
    )
    with pytest.raises(AlignmentError) as e:
        run(sim("s", [1], [0]), src, strategy=BUCKET, bucket_width_s=2, reducer="count", approved_reducers=APPROVED)
    assert "numeric" in str(e.value)  # the clocks match, so this is really the column check


# ------------------------------------------------------------------------------------------------ namespaces & provenance
def test_measured_and_simulated_values_stay_in_separate_namespaces():
    target, source = sim("sim", [1, 2], [100, 200]), obs("meas", [1, 2], [1, 2])
    before = source.frame.copy()
    res = run(target, source, strategy=EXACT)
    assert (
        "target__val" in res.frame and "source__val" in res.frame and "val" not in res.frame
    )  # same name, no collision, no merge
    assert col(res, "target__val") == [100, 200] and col(res, "source__val") == [1, 2]
    assert res.frame.attrs["target_layer"] == "L3" and res.frame.attrs["source_layer"] == "L1"
    pd.testing.assert_frame_equal(source.frame, before)  # inputs are never modified


def test_provenance_labels_cannot_be_relabelled():
    frame = pd.DataFrame({"_src_row": [1], "_t_ns": [0], "v": [1.0]})
    with pytest.raises(AlignmentError):
        TimedSeries("x", Layer.L3_SIMULATED, Provenance.MEASURED, TimeBasis.ELAPSED, "c", frame)
    with pytest.raises(AlignmentError):
        TimedSeries("x", Layer.L1_OBSERVED, Provenance.SIMULATED, TimeBasis.ELAPSED, "c", frame)
    with pytest.raises(AlignmentError):
        TimedSeries("x", Layer.L0_RAW, Provenance.MEASURED, TimeBasis.ELAPSED, "c", frame)
    s = sim("s", [1], [1])
    assert (s.layer, s.provenance, s.time_basis) == (Layer.L3_SIMULATED, Provenance.SIMULATED, TimeBasis.ELAPSED)
    with pytest.raises(AlignmentError):
        TimedSeries.from_observations(
            s.frame, layer=Layer.L3_SIMULATED, basis=TimeBasis.ELAPSED, clock_id="c", name="x"
        )


def test_source_column_selection_and_validation():
    source = obs("m", [1], [5])
    source.frame["other"] = 9.0
    res = run(sim("s", [1], [0]), source, strategy=EXACT, source_columns=("other",))
    assert "source__other" in res.frame and "source__val" not in res.frame
    with pytest.raises(AlignmentError):
        run(sim("s", [1], [0]), source, strategy=EXACT, source_columns=("nope",))


def test_alignment_provenance_record():
    spec = AlignmentSpec(NEAREST, tolerance_s=2.0)
    res = align(sim("sim", [1.0, 50.0], [0, 0]), obs("meas", [1, 2], [5, 6]), spec)
    rec = res.provenance.to_dict()
    assert rec["operation"] == "alignment" and rec["policy_id"] == "align_nearest" and rec["source_files"] == ["meas"]
    assert (
        rec["config"]["tolerance_s"] == 2.0
        and rec["config"]["strategy"] == "nearest"
        and rec["config"]["source_sorted_internally_by_time"] is True
    )
    clock = rec["config"]["clock"]
    assert clock["time_basis"] == "elapsed_from_origin" and clock["source_offset_s"] == 0.0
    assert (
        rec["config"]["source_offset_s"] is None and rec["config"]["effective_source_offset_s"] == 0.0
    )  # not declared
    assert clock["offset_basis"] == "same_clock_id" and clock["source_offset_declared"] is False
    assert (
        rec["source_rows"]["source"]["count"] == 1 and rec["source_rows"]["target"]["count"] == 2
    )  # only source row 1 was used
    assert rec["exclusions"]["n_excluded"] == 0
    out = rec["output"]
    assert (out["target_layer"], out["target_provenance"], out["source_layer"], out["source_provenance"]) == (
        "L3",
        "simulated",
        "L1",
        "measured",
    )
    assert (
        res.summary()["by_status"] == {"matched": 1, "unmatched": 1, "ambiguous": 0}
        and res.summary()["n_target_rows"] == 2
    )
    assert "\\" not in json.dumps(rec) and len(rec["record_sha256"]) == 64


# ------------------------------------------------------------------------------------------------ clocks and time bases
def test_naive_clocks_must_be_declared_equivalent():
    a = obs("a", [1], [1], basis=TimeBasis.NAIVE_WALLCLOCK, clock="main_logger")
    b = obs("b", [1], [2], basis=TimeBasis.NAIVE_WALLCLOCK, clock="supplementary_logger")
    with pytest.raises(ClockMismatchError):
        run(a, b, strategy=EXACT)
    res = run(a, b, strategy=EXACT, clock_equivalence_note="same site wall clock, declared by the user")
    assert res.provenance.config["clock"]["clock_equivalence_note"].startswith("same site") and col(
        res, "align_status"
    ) == ["matched"]
    same = run(a, obs("c", [1], [3], basis=TimeBasis.NAIVE_WALLCLOCK, clock="main_logger"), strategy=EXACT)
    assert col(same, "align_status") == ["matched"]


def test_naive_and_elapsed_bases_are_never_mixed():
    with pytest.raises(ClockMismatchError):
        run(
            obs("a", [1], [1], basis=TimeBasis.NAIVE_WALLCLOCK),
            obs("b", [1], [1], basis=TimeBasis.ELAPSED),
            strategy=EXACT,
        )


def test_timezone_aware_series_are_refused_and_never_assumed_to_share_a_clock():
    frame = pd.DataFrame({"_src_row": [1], "_ts_ns": [0], "_elapsed_s": [0.0]})
    with pytest.raises(ClockMismatchError):
        TimedSeries.from_observations(frame, layer=Layer.L1_OBSERVED, basis=TimeBasis.TZ_AWARE, clock_id="c", name="x")
    aware = TimedSeries("aw", Layer.L1_OBSERVED, Provenance.MEASURED, TimeBasis.TZ_AWARE, "c", frame.assign(_t_ns=[0]))
    naive = obs("n", [0], [1], basis=TimeBasis.NAIVE_WALLCLOCK)
    for a, b in ((naive, aware), (aware, naive), (aware, aware)):
        with pytest.raises(ClockMismatchError) as e:
            run(a, b, strategy=EXACT)
        assert "TimeMapping" in str(e.value)


def test_a_clock_offset_between_naive_clocks_is_a_time_mapping_and_is_refused():
    a = obs("a", [1], [1], basis=TimeBasis.NAIVE_WALLCLOCK)
    with pytest.raises(AlignmentError):
        run(a, obs("b", [1], [1], basis=TimeBasis.NAIVE_WALLCLOCK), strategy=EXACT, source_offset_s=7200)


def test_elapsed_alignment_uses_a_declared_offset():
    target, source = sim("s", [0, 1], [0, 0]), obs("m", [100, 101], [7, 8])
    assert set(col(run(target, source, strategy=EXACT), "align_status")) == {
        "unmatched"
    }  # no offset declared: no silent shifting
    res = run(target, source, strategy=EXACT, source_offset_s=-100.0)
    assert col(res, "source__val") == [7, 8] and res.provenance.config["source_offset_s"] == -100.0


# ------------------------------------------------------------------------------------------------ no row-index joins
@pytest.mark.parametrize("strategy,kw", [(EXACT, {}), (NEAREST, {"tolerance_s": 0.6}), (BACKWARD, {"tolerance_s": 5})])
def test_results_do_not_depend_on_the_row_order_of_the_source(strategy, kw):
    times, vals = [0, 1, 2, 3, 4, 5, 6], [10, 11, 12, 13, 14, 15, 16]
    target = sim("s", [0, 2, 4, 6, 7], np.zeros(5))
    ref = run(target, obs("m", times, vals), strategy=strategy, **kw)
    perm = np.random.default_rng(0).permutation(len(times))
    shuffled = obs("m", np.array(times)[perm], np.array(vals)[perm])
    got = run(target, shuffled, strategy=strategy, **kw)
    assert col(got, "source__val") == col(ref, "source__val") or np.allclose(
        got.frame["source__val"], ref.frame["source__val"], equal_nan=True
    )
    assert col(got, "align_status") == col(ref, "align_status")


def test_series_of_different_lengths_align_by_time_not_by_position():
    res = run(sim("s", [10, 20, 30], [0, 0, 0]), obs("m", [20], [99]), strategy=EXACT)
    assert col(res, "align_status") == ["unmatched", "matched", "unmatched"] and col(res, "source__val")[1] == 99


# ------------------------------------------------------------------------------------------------ with the reader
def test_reader_output_aligns_with_a_simulated_series_in_elapsed_time(tmp_path):
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.DUP_ROWS, chunksize=3)[0]
    l1 = p2.frame_of(reader, ["Power Ch 1 (W)"])
    measured = TimedSeries.from_observations(
        l1,
        layer=Layer.L1_OBSERVED,
        basis=TimeBasis.ELAPSED,
        clock_id="aau_main",
        name="measured_main",
        origin_text="2024-09-17 09:40:00",
    )
    target = TimedSeries.from_simulated(
        pd.DataFrame({"t": np.arange(0, 9, 1.0), "val": np.zeros(9)}),
        elapsed_s_col="t",
        name="twin",
        clock_id="twingrid_simulation",
        origin_text="2024-09-17 09:40:00",  # the simulation is declared to start at the measurement's origin
    )
    res = run(target, measured, strategy=EXACT, source_columns=("Power Ch 1 (W)",))
    assert res.provenance.config["clock"]["offset_basis"] == "shared_origin_text"
    # elapsed 2 s: source rows 3 and 9 (identical duplicate group); elapsed 3 s: rows 4 and 5 (conflicting)
    assert col(res, "align_status") == [
        "matched",
        "matched",
        "ambiguous",
        "ambiguous",
        "matched",
        "matched",
        "matched",
        "matched",
        "matched",
    ]
    assert (
        col(res, "align_reason")[2:4] == ["multiple_candidates", "conflicting_duplicates"]
        and col(res, "align_source_rows")[3] == "4;5"
    )
    assert res.provenance.config["clock"]["source_origin"] == "2024-09-17 09:40:00"
    naive = TimedSeries.from_observations(
        l1, layer=Layer.L1_OBSERVED, basis=TimeBasis.NAIVE_WALLCLOCK, clock_id="aau_main", name="m"
    )
    with pytest.raises(
        ClockMismatchError
    ):  # measured naive wall clock vs simulated elapsed time: no shared clock is assumed
        run(target, naive, strategy=EXACT)
