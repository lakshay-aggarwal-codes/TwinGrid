"""Phase 2: the two-pass streaming reader, TimeIndex and the L1 observation stream (synthetic fixtures only)."""

import math

import numpy as np
import p2_fixtures as p2
import pandas as pd
import pytest

from research.danish_aau.evaluation.data_layer.config import parse_data_config
from research.danish_aau.evaluation.data_layer.errors import (
    DataConfigError,
    MaterialisationError,
    NumericParseError,
    ReaderError,
)
from research.danish_aau.evaluation.data_layer.observations import ObservationStream

CHUNK_SIZES = [1, 2, 3, 4, 7, 11, 50_000]


def _main(tmp_path, rows, chunksize=50_000, **kw):
    return p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, rows, chunksize=chunksize, **kw)[0]


# ------------------------------------------------------------------------------------------ chunk boundaries
@pytest.mark.parametrize("chunksize", CHUNK_SIZES)
def test_time_index_and_stream_are_independent_of_the_chunk_size(tmp_path, chunksize):
    ref = _main(tmp_path / "ref", p2.DUP_ROWS, 50_000)
    got = _main(tmp_path / "got", p2.DUP_ROWS, chunksize)
    pd.testing.assert_frame_equal(got.index.to_frame(), ref.index.to_frame())
    assert got.index.summary() == ref.index.summary()
    pd.testing.assert_frame_equal(p2.frame_of(got), p2.frame_of(ref))


def test_duplicate_groups_are_global_across_chunks_and_not_only_adjacent(tmp_path):
    reader = _main(tmp_path, p2.DUP_ROWS, chunksize=3)  # chunks: rows 1-3 | 4-6 | 7-9 | 10-11
    idx = reader.index
    # ts2 at rows 3 (chunk 1) and 9 (chunk 3): identical values, non-adjacent, different chunks -> group 0
    # ts3 at rows 4,5 (same chunk): conflicting values -> group 1 (numbered by first appearance)
    assert list(idx.dup_group) == [-1, -1, 0, 1, 1, -1, -1, -1, 0, -1, -1]
    assert list(idx.dup_size) == [0, 0, 2, 2, 2, 0, 0, 0, 2, 0, 0]
    assert list(idx.seq_in_group) == [0, 0, 1, 1, 2, 0, 0, 0, 2, 0, 0]
    assert list(idx.dup_conflict) == [False, False, False, True, True, False, False, False, False, False, False]
    s = idx.summary()
    assert (s["n_duplicate_groups"], s["n_duplicate_rows"], s["n_conflicting_duplicate_groups"]) == (2, 4, 1)
    assert s["duplicate_group_size_histogram"] == {"2": 2}


def test_a_duplicate_pair_split_exactly_at_a_chunk_boundary(tmp_path):
    reader = _main(tmp_path, p2.DUP_ROWS, chunksize=4)  # rows 4 | 5 straddle the boundary
    assert list(reader.index.dup_group[3:5]) == [1, 1] and bool(reader.index.dup_conflict[3])


def test_conflicting_duplicates_are_preserved_with_original_values(tmp_path):
    frame = p2.frame_of(_main(tmp_path, p2.DUP_ROWS, chunksize=2))
    pair = frame[frame["_ts_text"] == p2.ts(3)]
    assert list(pair["_src_row"]) == [4, 5]
    assert list(pair["Power Ch 1 (W)"]) == [103.0, 103.5]  # neither dropped, first-kept, last-kept nor averaged
    assert len(frame) == len(p2.DUP_ROWS)


def test_conflict_is_judged_on_raw_text(tmp_path):
    rows = [[p2.ts(0), "21.30", "1", "1"], [p2.ts(0), "21.3", "1", "1"]]
    assert bool(_main(tmp_path, rows).index.dup_conflict[0])  # same number, different text: reported, never merged
    rows = [[p2.ts(0), "21.3", "1", "1"], [p2.ts(0), "21.3", "1", "1"]]
    assert not _main(tmp_path / "b", rows).index.dup_conflict.any()


# ------------------------------------------------------------------------------------------ row numbers
def test_src_rows_are_stable_one_based_ordinals_in_source_order(tmp_path):
    frame = p2.frame_of(_main(tmp_path, p2.DUP_ROWS, chunksize=4))
    assert list(frame["_src_row"]) == list(range(1, 12))


def test_blank_lines_do_not_consume_row_numbers_and_match_the_phase1_row_count(tmp_path):
    text = (
        "\n".join([",".join(p2.MAIN_HEADER), ",".join(p2.main_rows(1)[0]), "", ",".join(p2.main_rows(2)[1]), ""])
        + "\n\n"
    )
    reader, raw = p2.build_reader_from_text(tmp_path, p2.MAIN_KEY, text, chunksize=1)
    assert list(p2.frame_of(reader)["_src_row"]) == [1, 2]
    from research.danish_aau.evaluation.inventory import count_data_rows

    assert count_data_rows(reader.source.path, raw) == reader.index.n_rows == 2


def test_selection_by_src_row_keeps_the_original_numbers(tmp_path):
    reader = _main(tmp_path, p2.DUP_ROWS, chunksize=3)
    frame = p2.frame_of(reader, ["Power Ch 1 (W)"], src_rows=[9, 3, 5])
    assert list(frame["_src_row"]) == [3, 5, 9]  # file order, original ids
    assert list(frame["Power Ch 1 (W)"]) == [102.0, 103.5, 102.0]


def test_crlf_and_bom_and_semicolon_files(tmp_path):
    body = "\r\n".join([";".join(p2.MAIN_HEADER), *(";".join(r) for r in p2.main_rows(3))]) + "\r\n"
    reader, _ = p2.build_reader_from_text(tmp_path, p2.MAIN_KEY, b"\xef\xbb\xbf" + body.encode("utf-8"), chunksize=2)
    assert reader.delimiter == ";" and reader.index.n_rows == 3
    assert list(reader.index.ts_text) == [r[0] for r in p2.main_rows(3)]  # no '\r', no BOM in the original text
    assert p2.frame_of(reader)["Power Ch 1 (W)"].tolist() == [100.0, 101.0, 102.0]


def test_ambiguous_delimiter_is_an_error_unless_configured(tmp_path):
    from research.danish_aau.evaluation.data_layer.reader import AauCsvReader

    text = "Time [Date/Time],a;b\n2024-09-17 09:40:00,1;2\n"
    with pytest.raises(ReaderError):
        p2.build_reader_from_text(tmp_path, p2.MAIN_KEY, text)
    cfg = p2.make_cfg(reader={"delimiter": ","})
    reader, _ = p2.build_reader_from_text(tmp_path / "ok", p2.MAIN_KEY, text, cfg=cfg)
    assert isinstance(reader, AauCsvReader) and reader.index.n_rows == 1


# ------------------------------------------------------------------------------------------ timestamps
def test_parse_failures_are_recorded_and_the_rows_and_text_are_kept(tmp_path):
    rows = [
        [p2.ts(0), "1", "1", "1"],
        ["garbage", "2", "2", "2"],
        ["", "3", "3", "3"],
        [" " + p2.ts(3) + " ", "4", "4", "4"],
        ["2024-09-17T09:40:04", "5", "5", "5"],
        [p2.ts(5), "6", "6", "6"],
    ]
    reader = _main(tmp_path, rows, chunksize=2)
    idx = reader.index
    assert [("ok", "parse_error", "empty", "ok", "parse_error", "ok")[i] for i in range(6)] == p2.frame_of(reader)[
        "_ts_status"
    ].tolist()
    assert idx.summary()["n_timestamp_parse_errors"] == 2 and idx.summary()["n_timestamp_empty"] == 1
    assert list(idx.ts_text) == [
        "2024-09-17 09:40:00",
        "garbage",
        "",
        " 2024-09-17 09:40:03 ",
        "2024-09-17T09:40:04",
        "2024-09-17 09:40:05",
    ]
    assert math.isnan(idx.elapsed_s[1]) and math.isnan(idx.delta_s[1]) and idx.order_flag[1] == 3
    assert idx.delta_s[3] == 3.0 and idx.delta_s[5] == 2.0  # deltas skip unparseable rows
    assert len(p2.frame_of(reader)) == 6  # nothing dropped


def test_timezone_suffixed_text_is_rejected_not_silently_converted(tmp_path):
    rows = [[p2.ts(0) + "Z", "1", "1", "1"], [p2.ts(1) + "+02:00", "2", "2", "2"]]
    idx = _main(tmp_path, rows).index
    s = idx.summary()
    assert list(idx.ts_status) == [3, 3] and s["n_timestamp_ok"] == 0 and s["n_timestamp_tz_suffix_rejected"] == 2
    assert s["n_timestamp_parse_errors"] == 0  # a distinct, explicit status


def test_the_timestamp_state_is_always_naive_unspecified(tmp_path):
    idx = _main(tmp_path, p2.main_rows(2)).index
    assert idx.summary()["timestamp_state"] == "naive_unspecified" == idx.timestamp_state
    assert "_ts_ns" in idx.to_frame().columns and "utc" not in " ".join(idx.to_frame().columns).lower()


def test_explicit_alternative_format_from_the_configuration(tmp_path):
    cfg = parse_data_config({"reader": {"timestamp_formats": ["%d/%m/%Y %H:%M:%S"]}})
    rows = [["17/09/2024 09:40:00", "1", "1", "1"], ["17/09/2024 09:40:01", "2", "2", "2"]]
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, rows, cfg=cfg)[0]
    assert reader.index.delta_s[1] == 1.0
    default_cfg_reader = p2.build_reader(tmp_path / "x", p2.MAIN_KEY, p2.MAIN_HEADER, rows)[0]
    assert default_cfg_reader.index.summary()["n_timestamp_parse_errors"] == 2  # nothing is inferred


# ------------------------------------------------------------------------------------------ ordering
def test_ordering_violations_are_flagged_and_the_original_order_is_kept(tmp_path):
    rows = [[p2.ts(5), "1", "1", "1"], [p2.ts(3), "2", "2", "2"], [p2.ts(4), "3", "3", "3"]]
    reader = _main(tmp_path, rows, chunksize=2)
    idx = reader.index
    assert [("first", "ok", "backward")[0]] and list(p2.frame_of(reader)["_order_flag"]) == ["first", "backward", "ok"]
    assert list(idx.delta_s[1:]) == [-2.0, 1.0] and idx.summary()["n_ordering_violations"] == 1
    assert list(p2.frame_of(reader)["_ts_text"]) == [r[0] for r in rows]  # never sorted
    assert list(p2.frame_of(reader)["Power Ch 1 (W)"]) == [1.0, 2.0, 3.0]


def test_elapsed_time_is_relative_to_the_first_parseable_row_in_source_order(tmp_path):
    rows = [[p2.ts(5), "1", "1", "1"], [p2.ts(3), "2", "2", "2"], [p2.ts(9), "3", "3", "3"]]
    assert list(_main(tmp_path, rows).index.elapsed_s) == [0.0, -2.0, 4.0]


def test_interval_distribution_summary_format(tmp_path):
    rows = [[p2.ts(s), "1", "1", "1"] for s in (0, 1, 1, 2, 4)]
    s = _main(tmp_path, rows, chunksize=2).index.summary()
    assert s["delta_seconds_counts"] == {"0.0": 1, "1.0": 2, "2.0": 1}


# ------------------------------------------------------------------------------------------ values
def test_values_are_converted_without_alteration_and_text_can_be_kept(tmp_path):
    rows = [[p2.ts(0), "21.30", "1e2", " 7 "]]
    reader = _main(tmp_path, rows)
    frame = p2.frame_of(reader, include_text=True)
    assert (
        frame.loc[0, "Power Ch 1 (W)"] == 21.3
        and frame.loc[0, "Power Ch 2 (W)"] == 100.0
        and frame.loc[0, "Temperature mod 1 ch 1"] == 7.0
    )
    assert frame.loc[0, "Power Ch 1 (W)__text"] == "21.30"


def test_missing_cells_become_nan_and_are_never_filled(tmp_path):
    rows = [[p2.ts(0), "1", "", "3"], [p2.ts(1), "", "", ""], [p2.ts(2), "4", "5", "6"]]
    frame = p2.frame_of(_main(tmp_path, rows))
    assert frame["Power Ch 2 (W)"].isna().tolist() == [True, True, False]
    assert frame["Power Ch 1 (W)"].isna().tolist() == [False, True, False]  # no forward fill, no interpolation


def test_non_numeric_cells_raise_by_default_naming_the_row(tmp_path):
    rows = [[p2.ts(0), "1", "2", "3"], [p2.ts(1), "oops", "2", "3"]]
    with pytest.raises(NumericParseError) as e:
        p2.frame_of(_main(tmp_path, rows))
    assert "src_row 2" in str(e.value) and "Power Ch 1 (W)" in str(e.value)


@pytest.mark.parametrize("bad", ["oops", "nan", "inf", "-inf", '"1,5"', "--1"])
def test_non_numeric_or_non_finite_cells_are_flagged_not_silently_accepted(tmp_path, bad):
    cfg = p2.make_cfg(reader={"non_numeric": "flag"})
    rows = [[p2.ts(0), "1", "2", "3"], [p2.ts(1), bad, "2", "3"]]
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, rows, cfg=cfg)[0]
    frame = p2.frame_of(reader)
    assert math.isnan(frame.loc[1, "Power Ch 1 (W)"])
    d = reader.diagnostics
    assert (
        d["non_numeric_cells"] == 1
        and d["non_numeric_by_column"] == {"Power Ch 1 (W)": 1}
        and d["first_non_numeric"] == [(2, "Power Ch 1 (W)")]
    )


# ------------------------------------------------------------------------------------------ selection / streaming
def test_only_selected_columns_are_returned(tmp_path):
    frame = p2.frame_of(_main(tmp_path, p2.main_rows(3)), ["Power Ch 2 (W)"])
    assert "Power Ch 2 (W)" in frame and "Power Ch 1 (W)" not in frame and "Temperature mod 1 ch 1" not in frame


def test_invalid_column_selections_are_errors(tmp_path):
    reader = _main(tmp_path, p2.main_rows(3))
    for bad in (["nope"], ["Time [Date/Time]"], ["Power Ch 1 (W)", "Power Ch 1 (W)"]):
        with pytest.raises(DataConfigError):
            list(reader.iter_chunks(bad))


def test_window_selection_is_inclusive_and_validated(tmp_path):
    reader = _main(tmp_path, p2.DUP_ROWS)
    frame = p2.frame_of(reader, ["Power Ch 1 (W)"], window=(p2.ts(3), p2.ts(5)))
    assert list(frame["_src_row"]) == [4, 5, 6, 7]
    with pytest.raises(DataConfigError):
        list(reader.iter_chunks(window=("bad", p2.ts(5))))
    with pytest.raises(DataConfigError):
        list(reader.iter_chunks(window=(p2.ts(5), p2.ts(3))))


@pytest.mark.parametrize("chunksize", [1, 3, 5])
def test_pass_two_really_streams_in_bounded_chunks(tmp_path, chunksize):
    reader = _main(tmp_path, p2.main_rows(11), chunksize)
    stream = ObservationStream.open(reader)
    sizes = [len(c) for c in stream.iter_chunks()]
    assert max(sizes) <= chunksize and sum(sizes) == 11
    assert reader.diagnostics["chunks"] == math.ceil(11 / chunksize) and reader.diagnostics["rows_streamed"] == 11


def test_pass_two_requires_pass_one(tmp_path):
    reader = _main(tmp_path, p2.main_rows(2), build_index=False)
    with pytest.raises(ReaderError):
        list(reader.iter_chunks())


def test_a_file_that_changes_between_passes_is_detected(tmp_path):
    reader = _main(tmp_path, p2.main_rows(4), chunksize=2)
    path = reader.source.path
    text = path.read_text(encoding="utf-8").replace(p2.ts(2), p2.ts(9))
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ReaderError) as e:
        list(reader.iter_chunks())
    assert "changed between passes" in str(e.value)
    reader2 = _main(tmp_path / "two", p2.main_rows(4), chunksize=2)
    reader2.source.path.write_text(
        reader2.source.path.read_text(encoding="utf-8") + ",".join(p2.main_rows(1, start=30)[0]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ReaderError):
        list(reader2.iter_chunks())


# ------------------------------------------------------------------------------------------ guarded materialisation
def test_to_frame_requires_explicit_confirmation(tmp_path):
    stream = ObservationStream.open(_main(tmp_path, p2.main_rows(3)))
    with pytest.raises(MaterialisationError) as e:
        stream.to_frame()
    assert "confirm=True" in str(e.value)
    assert len(stream.to_frame(confirm=True)) == 3


def test_to_frame_refuses_over_the_cell_limit_unless_allowed(tmp_path):
    cfg = p2.make_cfg(reader={"materialise_cell_limit": 20})
    reader = p2.build_reader(tmp_path, p2.MAIN_KEY, p2.MAIN_HEADER, p2.main_rows(5), cfg=cfg)[0]
    stream = ObservationStream.open(reader)
    assert stream.estimated_cells() > 20
    with pytest.raises(MaterialisationError) as e:
        stream.to_frame(confirm=True)
    assert "allow_large" in str(e.value)
    assert len(stream.to_frame(confirm=True, allow_large=True)) == 5
    small = ObservationStream.open(reader, ["Power Ch 1 (W)"], src_rows=[1])
    assert len(small.to_frame(confirm=True)) == 1  # a narrow selection fits under the same limit


def test_materialised_frame_is_labelled_l1_measured_and_matches_the_chunks(tmp_path):
    stream = ObservationStream.open(_main(tmp_path, p2.DUP_ROWS, 3))
    frame = stream.to_frame(confirm=True)
    assert frame.attrs["layer"] == "L1" and frame.attrs["provenance"] == "measured"
    chunks = pd.concat(list(stream.iter_chunks()), ignore_index=True)
    pd.testing.assert_frame_equal(frame.copy().rename_axis(None), chunks.rename_axis(None))  # attrs are not compared
    assert np.array_equal(frame["_src_row"].to_numpy(), np.arange(1, 12))


def test_l1_derivation_record_states_source_selection_and_config(tmp_path):
    reader = _main(tmp_path, p2.DUP_ROWS, 3)
    rec = ObservationStream.open(reader, ["Power Ch 1 (W)"], src_rows=[1, 2, 3]).derivation_record().to_dict()
    assert rec["operation"] == "l1_observation_view" and rec["source_files"] == [reader.source.relpath]
    assert (
        rec["source_rows"]["count"] == 3
        and rec["output"]["layer"] == "L1"
        and rec["output"]["provenance"] == "measured"
    )
    assert (
        rec["config"]["timestamp_state"] == "naive_unspecified"
        and rec["config"]["data_config_sha256"] == reader.cfg.sha256
    )
    assert rec["exclusions"] is None and len(rec["record_sha256"]) == 64


def test_a_structurally_malformed_row_is_a_typed_reader_error(tmp_path):
    text = ",".join(p2.MAIN_HEADER) + "\n" + ",".join(p2.main_rows(1)[0]) + "\n" + p2.ts(1) + ",1,2,3,4\n"
    with pytest.raises(ReaderError) as e:
        p2.build_reader_from_text(tmp_path, p2.MAIN_KEY, text)
    assert "malformed" in str(e.value) and str(tmp_path) not in str(e.value)
