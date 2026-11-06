from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from research.danish_aau.adapter import AdapterReader, discover_all
from research.danish_aau.adapter.schema import spec_for_key
from research.danish_aau.cleaning import (
    CATALOGUE,
    TIER1_COLUMNS,
    CleanConfig,
    CleaningError,
    RawRowIn,
    apply_flags,
    clean_file,
    clean_rows,
    ledger_entries,
    ledger_summary,
    reconcile,
    validate_catalogue,
    verify_l1,
    write_l1,
)
from research.danish_aau.cleaning.cadence import cadence_profile
from research.danish_aau.cleaning.catalogue import (
    D_CONFLICT_MISSING,
    D_EXACT_DUP,
    D_FLAGGED,
    D_RETAINED,
    REASON_BLANK,
    REASON_RE,
    REASON_TIE,
)
from research.danish_aau.cleaning.flags import flatline_report, flatline_runs
from research.danish_aau.cleaning.reference import TASK4, TASK6, compare_ledger, compare_profile
from research.danish_aau.cleaning.resolve import naive_seconds, scale_for, ticks_from_floats
from research.danish_aau.cleaning.tier1 import NOT_TIER1_TEMPERATURE_COLUMNS, check_selection, column_slug
from research.danish_aau.contract.telemetry_contract import PROTOCOL_SHA256_V5, validate_ledger_entry
from research.danish_aau.protocol.protocol import load_protocol, protocol_sha256
from research.danish_aau.protocol.rules import to_ticks

PROTO = load_protocol()
FILE = "AAU_temperature_and_power_use.csv"
P1, T1, T3 = "Power Ch 1 (W)", "Temperature mod 1 ch 1", "Temperature mod 3 ch 1"  # T3 is NOT Tier 1
SMALL_ALL = (P1, T1, T3)
SMALL_T1 = (P1, T1)
SMALL_RES = {c: PROTO.resolution(c, FILE) for c in SMALL_ALL}


def rows(*specs):
    """specs: (row_ordinal, ts, power, temp, temp3) texts."""
    return [RawRowIn(r, ts, {P1: p, T1: t, T3: t3}) for r, ts, p, t, t3 in specs]


def small(specs, **kw):
    return clean_rows(rows(*specs), SMALL_ALL, SMALL_RES, PROTO, tier1=SMALL_T1, **kw)


# ---------------------------------------------------------------------------------------------- catalogue and selection
def test_catalogue_is_closed_unique_and_contract_shaped():
    validate_catalogue()
    codes = [c.code for c in CATALOGUE]
    assert len(codes) == len(set(codes)) and all(REASON_RE.match(c) for c in codes)
    assert "conflict_unresolved_tie" in codes and PROTO["duplicates"]["tie_reason"] in codes
    # only the tie and blank reasons are produced without owner input
    assert {c.code for c in CATALOGUE if c.used_for == "record_missing"} == {"conflict_unresolved_tie", "blank_cell"}
    assert {c.code for c in CATALOGUE if c.status == "needs_owner"} == {"out_of_range", "flatline_run"}


def test_tier1_selection_is_40_columns_and_matches_runner_and_adapter():
    check_selection()
    from research.danish_aau.screening.run_task6_screen import REGISTER

    assert len(TIER1_COLUMNS) == 40 and len(NOT_TIER1_TEMPERATURE_COLUMNS) == 11
    assert set(TIER1_COLUMNS) == {c for c, s in REGISTER.items() if s.cls in ("R", "P")}
    assert set(NOT_TIER1_TEMPERATURE_COLUMNS) == {c for c, s in REGISTER.items() if s.cls == "F"}
    assert set(TIER1_COLUMNS) | set(NOT_TIER1_TEMPERATURE_COLUMNS) == set(
        spec_for_key("temperature_power").measurement_columns
    )
    assert (
        column_slug("Power Ch 1 (W)") == "power_ch_1_w"
        and column_slug("Temperature mod 7 ch 3") == "temperature_mod_7_ch_3"
    )


# ---------------------------------------------------------------------------------------------- exact ticks
@pytest.mark.parametrize(
    "text,res,expected",
    [
        ("0.005", "0.01", 0),
        ("0.015", "0.01", 2),
        ("0.025", "0.01", 2),
        ("-0.005", "0.01", 0),
        ("100.05", "0.1", 1000),
        ("100.15", "0.1", 1002),
    ],
)
def test_half_even_on_source_text(text, res, expected):
    assert to_ticks(text, Decimal(res)) == expected


def test_vector_ticks_equal_decimal_ticks_including_near_ties():
    rng = random.Random(7)
    base = [f"{rng.uniform(5, 40):.6f}" for _ in range(3000)]
    for res in (Decimal("0.01"), Decimal("0.1")):
        ties = (
            [f"{rng.randrange(500, 4000)}.{rng.randrange(100):02d}5" for _ in range(1500)]  # exact .xx5 ties at 0.01
            if res == Decimal("0.01")
            else [f"{rng.randrange(500, 4000)}.{rng.randrange(10)}5" for _ in range(1500)]  # exact .x5 ties at 0.1
        )
        texts = base + ties + ["21.305", "21.295", "0.005", "38.885", "100.05", "100.15"]
        scale = np.array([float(scale_for(res))])
        vals = np.array([float(t) for t in texts]).reshape(-1, 1)
        ticks, finite, amb = ticks_from_floats(vals, scale)
        ticks = ticks.copy()
        for i in np.flatnonzero(amb[:, 0]):
            ticks[i, 0] = to_ticks(texts[i], res)
        assert [int(t) for t in ticks[:, 0]] == [to_ticks(t, res) for t in texts]
        assert amb.any()  # the fixture really exercises the Decimal fallback


# ---------------------------------------------------------------------------------------------- group rules (reference path)
def test_single_rows_are_retained_and_values_kept_at_resolution():
    r = small(
        [(1, "2000-01-01 00:00:00", "100.04", "21.301", "5.0"), (2, "2000-01-01 00:00:01", "100.06", "21.299", "5.0")]
    )
    assert r.n_seconds == 2 and r.n_rows == 2
    assert r.ticks[:, 0].tolist() == [1000, 1001] and r.ticks[:, 1].tolist() == [2130, 2130]
    assert r.valid.all() and (r.row_disp == D_RETAINED).all() and (r.sec_disp == D_RETAINED).all()


def test_exact_duplicate_keeps_value_and_lowest_row_is_bookkeeping_only():
    a = small(
        [(5, "2000-01-01 00:00:00", "100.04", "21.301", "5.0"), (9, "2000-01-01 00:00:00", "100.02", "21.299", "5.0")]
    )
    b = small(
        [(9, "2000-01-01 00:00:00", "100.04", "21.301", "5.0"), (5, "2000-01-01 00:00:00", "100.02", "21.299", "5.0")]
    )
    for r in (a, b):
        assert r.n_seconds == 1 and r.n_rows == 2 and r.valid.all()
        assert r.ticks[0].tolist() == [1000, 2130] and int(r.first_row[0]) == 5
        assert sorted(r.row_disp.tolist()) == [D_RETAINED, D_EXACT_DUP]
        assert r.row_ordinal.tolist() == [5, 9]
        assert reconcile(r) == []
    assert a.ticks.tolist() == b.ticks.tolist()  # which duplicate row is kept never changes the value


def test_unresolved_tie_is_missing_never_imputed_and_other_cells_survive():
    r = small(
        [(1, "2000-01-01 00:00:00", "100.0", "21.30", "5.0"), (2, "2000-01-01 00:00:00", "100.0", "21.50", "5.0")]
    )
    assert r.valid[0].tolist() == [True, False]
    assert r.reason[0].tolist() == [0, REASON_TIE]
    assert r.ticks[0, 1] == 0  # no first/last/mean/median value is carried
    assert r.ticks[0, 0] == 1000
    assert (r.row_disp == D_CONFLICT_MISSING).all() and int(r.sec_disp[0]) == D_CONFLICT_MISSING
    assert r.stats["cells_made_missing_tier1"] == 1 and r.stats["cells_made_missing_all_columns"] == 1


def test_no_majority_vote_and_large_groups_work():
    specs = [(i, "2000-01-01 00:00:00", "100.0", "21.30" if i < 3 else "21.50", "5.0") for i in range(1, 5)]
    r = small(specs)  # 2 rows say 21.30, 2 say 21.50: still a tie. Majority 3-1 must also be a tie:
    assert not r.valid[0, 1]
    r3 = small([(i, "2000-01-01 00:00:00", "100.0", "21.50" if i == 1 else "21.30", "5.0") for i in range(1, 4)])
    assert not r3.valid[0, 1] and r3.stats["group_sizes"] == {3: 1}
    big = small([(i, "2000-01-01 00:00:00", "100.0", "21.30", "5.0") for i in range(1, 75)])
    assert big.valid.all() and big.stats["group_sizes"] == {74: 1} and int(big.first_row[0]) == 1
    assert int((big.row_disp == D_EXACT_DUP).sum()) == 73
    one = small([(i, "2000-01-01 00:00:00", "100.0", "21.50" if i == 40 else "21.30", "5.0") for i in range(1, 75)])
    assert not one.valid[0, 1] and (one.row_disp == D_CONFLICT_MISSING).all()


def test_blank_never_conflicts_and_all_blank_is_missing_blank_cell():
    r = small([(1, "2000-01-01 00:00:00", "", "21.30", "5.0"), (2, "2000-01-01 00:00:00", "100.0", "21.30", "5.0")])
    assert r.valid[0].tolist() == [True, True] and r.ticks[0, 0] == 1000
    assert int(r.sec_disp[0]) == D_RETAINED  # blank + value agrees: an exact duplicate group, not a conflict
    b = small([(1, "2000-01-01 00:00:00", "", "21.30", "5.0"), (2, "2000-01-01 00:00:00", "", "21.30", "5.0")])
    assert b.valid[0].tolist() == [False, True] and b.reason[0, 0] == REASON_BLANK
    s = small([(1, "2000-01-01 00:00:00", "", "21.30", "5.0")])
    assert not s.valid[0, 0] and s.reason[0, 0] == REASON_BLANK


def test_tie_outside_tier1_is_counted_and_does_not_make_tier1_cells_missing():
    r = small(
        [(1, "2000-01-01 00:00:00", "100.0", "21.30", "5.00"), (2, "2000-01-01 00:00:00", "100.0", "21.30", "6.00")]
    )
    assert r.valid.all()
    assert r.stats["cells_made_missing_tier1"] == 0 and r.stats["cells_made_missing_all_columns"] == 1
    assert r.stats["groups_with_ties_only_outside_tier1"] == 1
    assert (r.row_disp == D_CONFLICT_MISSING).all()  # protocol: file-level label, all columns


def test_input_order_never_matters_and_output_is_sorted():
    rng = random.Random(3)
    specs = []
    for i in range(1, 60):
        ts = f"2000-01-01 00:{i // 60:02d}:{(i * 7) % 60:02d}"
        specs.append((i, ts, f"{100 + i}.04", f"{20 + i * 0.01:.3f}", "5.0"))
    specs += [(100, "2000-01-01 00:00:03", "1.0", "2.0", "3.0"), (101, "2000-01-01 00:00:03", "1.0", "2.5", "3.0")]
    base = small(specs).digest()
    for seed in range(8):
        sh = specs[:]
        rng.shuffle(sh)
        assert small(sh).digest() == base
    r = small(specs)
    assert np.all(np.diff(r.t_sec) > 0) and np.all(np.diff(r.row_ordinal) > 0)


def test_refusals_are_typed():
    with pytest.raises(CleaningError):
        small(
            [(1, "2000-01-01 00:00:00", "1", "2", "3"), (1, "2000-01-01 00:00:01", "1", "2", "3")]
        )  # duplicate ordinal
    with pytest.raises(CleaningError):
        small([(1, "not a time", "1", "2", "3")])
    with pytest.raises(CleaningError):
        clean_rows([RawRowIn(1, "2000-01-01 00:00:00", {P1: "1"})], SMALL_ALL, SMALL_RES, PROTO, tier1=SMALL_T1)
    with pytest.raises(CleaningError):
        clean_rows([], SMALL_ALL, SMALL_RES, PROTO, tier1=SMALL_T1)


def test_no_timezone_or_utc_text_anywhere_and_seconds_are_naive():
    assert naive_seconds(["2000-01-01 00:00:00", "2000-01-01 00:00:01"]).tolist() == [946684800, 946684801]
    r = small([(1, "2000-01-01 00:00:00", "1.0", "2.0", "3.0")])
    assert "Z" not in str(r.ts_text[0]) and "+" not in str(r.ts_text[0])


# ---------------------------------------------------------------------------------------------- flags
def _series(vals, start=0, step=1):
    specs = [
        (i + 1, f"2000-01-01 00:{(start + i * step) // 60:02d}:{(start + i * step) % 60:02d}", "100.0", v, "5.0")
        for i, v in enumerate(vals)
    ]
    return small(specs)


def test_defaults_produce_no_flags_and_range_is_not_evaluated():
    r = _series(["21.30", "999.99", "21.30"])
    a = apply_flags(r, PROTO, CleanConfig())
    assert (a.flag == 0).all() and a.digest() == r.digest()


def test_out_of_range_is_flagged_never_clipped_and_marks_the_row():
    r = _series(["21.30", "999.99", "21.40"])
    a = apply_flags(r, PROTO, CleanConfig(range_limits={"temperature": ("0", "100")}))
    assert a.flag[:, 1].tolist() == [0, 1, 0]
    assert a.ticks[:, 1].tolist() == [2130, 99999, 2140]  # value kept exactly
    assert a.valid[:, 1].all()
    assert a.row_disp.tolist() == [D_RETAINED, D_FLAGGED, D_RETAINED]
    assert r.row_disp.tolist() == [D_RETAINED] * 3  # the input result is untouched
    entries = list(ledger_entries(a, dataset_id="danish-aau-v5", protocol_sha256=PROTOCOL_SHA256_V5))
    assert entries[1]["disposition"] == "flagged" and entries[1]["reason_code"] == "out_of_range"
    assert all(validate_ledger_entry(e) == [] for e in entries)
    with pytest.raises(ValueError):
        apply_flags(r, PROTO, CleanConfig(range_limits={"temperature": ("100", "0")}))


def test_conflict_dispositions_are_never_overwritten_by_flags():
    r = small(
        [
            (1, "2000-01-01 00:00:00", "100.0", "999.0", "5.0"),
            (2, "2000-01-01 00:00:00", "100.0", "999.0", "6.0"),
            (3, "2000-01-01 00:00:01", "100.0", "999.0", "5.0"),
        ]
    )
    a = apply_flags(r, PROTO, CleanConfig(range_limits={"temperature": ("0", "100")}))
    assert a.row_disp.tolist() == [D_CONFLICT_MISSING, D_CONFLICT_MISSING, D_FLAGGED]


def test_flatline_runs_gap_and_blank_break_runs_and_off_by_default():
    valid = np.array([1, 1, 1, 1, 1, 0, 1, 1, 1, 1], dtype=bool)
    ticks = np.array([5, 5, 5, 5, 5, 5, 5, 5, 5, 6])
    t = np.arange(10)
    m = flatline_runs(valid, ticks, t, 4, 3)
    assert m.tolist() == [True] * 5 + [False] * 5  # the blank breaks the run; the tail run has only 3 equal samples
    t2 = np.array([0, 1, 2, 3, 10, 11, 12, 13, 14, 15])
    assert (
        flatline_runs(np.ones(10, bool), np.full(10, 7), t2, 5, 3).tolist() == [False] * 4 + [True] * 6
    )  # gap > 3 s breaks it
    r = _series(["21.30"] * 6 + ["21.31"])
    assert (apply_flags(r, PROTO, CleanConfig()).flag == 0).all()
    on = apply_flags(r, PROTO, CleanConfig(flatline_min_run=5))
    assert on.flag[:6, 1].tolist() == [2] * 6 and on.flag[6, 1] == 0
    both = apply_flags(r, PROTO, CleanConfig(flatline_min_run=5, range_limits={"temperature": ("0", "10")}))
    assert (both.flag[:, 1] == 1).all()  # out_of_range has priority
    rep = flatline_report(r, 5, 3)
    assert rep["by_column"][T1]["cells"] == 6 and (r.flag == 0).all()  # report never applies anything
    with pytest.raises(ValueError):
        CleanConfig(flatline_min_run=1)


# ---------------------------------------------------------------------------------------------- ledger
def test_ledger_reconciles_validates_against_the_contract_and_detects_tampering():
    r = small(
        [
            (1, "2000-01-01 00:00:00", "100.0", "21.30", "5.0"),
            (2, "2000-01-01 00:00:01", "100.0", "21.30", "5.0"),
            (3, "2000-01-01 00:00:01", "100.0", "21.31", "5.0"),
            (4, "2000-01-01 00:00:02", "100.0", "21.30", "5.0"),
            (5, "2000-01-01 00:00:02", "100.0", "21.30", "5.0"),
            (6, "2000-01-01 00:00:02", "100.0", "21.30", "5.0"),
        ]
    )
    s = ledger_summary(r)
    assert s["raw_rows"] == 6 and s["unique_seconds"] == 3 and s["reconciles"]
    assert s["by_disposition"] == {
        "retained": 2,
        "exact_duplicate": 2,
        "conflict_resolved_by_source_rule": 0,
        "conflict_cell_missing": 2,
        "flagged": 0,
        "dropped_with_reason": 0,
    }
    assert s["repeated_timestamp_groups"] == {"2": 1, "3": 1}
    entries = list(ledger_entries(r, dataset_id="danish-aau-v5", protocol_sha256=PROTOCOL_SHA256_V5))
    assert len(entries) == 6 and [e["row_ordinal"] for e in entries] == [1, 2, 3, 4, 5, 6]
    assert all(validate_ledger_entry(e) == [] for e in entries)
    assert {e["disposition"] for e in entries if e["group_size"] == 2} == {"conflict_cell_missing"}
    assert {e["reason_code"] for e in entries if e["group_size"] == 2} == {"conflict_unresolved_tie"}
    bad = r.row_disp.copy()
    bad[0] = D_EXACT_DUP
    from dataclasses import replace

    assert reconcile(replace(r, row_disp=bad))  # a lying ledger is detected


# ---------------------------------------------------------------------------------------------- cadence and references
def test_cadence_profile_reports_steps_and_large_steps_without_filling():
    ts = [
        "2000-01-01 00:00:00",
        "2000-01-01 00:00:10",
        "2000-01-01 00:00:10",
        "2000-01-01 00:00:21",
        "2000-01-01 00:20:00",
        "2000-01-01 00:20:10",
    ]
    ns = naive_seconds(ts) * 1_000_000_000
    p = cadence_profile(ns, np.array(ts, dtype=object), 10)
    assert p["distinct_timestamps"] == 5 and p["backward_steps"] == 0 and p["max_step_s"] == 1179.0
    assert p["max_step_between"] == ["2000-01-01 00:00:21", "2000-01-01 00:20:00"]
    assert p["steps_above_threshold"] == 1 and p["largest_steps"][0]["step_s"] == 1179.0
    back = cadence_profile(np.array([5, 3, 4]) * 1_000_000_000, np.array(["a", "b", "c"], dtype=object), 1)
    assert back["backward_steps"] == 1


def test_reference_tables_are_internally_consistent_and_comparison_reports_differences():
    for key, t in TASK6.items():
        assert t["retained"] + t["dup"] + t["conflict"] == t["raw"]
        assert t["raw"] - t["unique"] == sum((k - 1) * v for k, v in t["sizes"].items())
    for key, t in TASK4.items():
        if key.startswith("temperature_power"):
            assert t["extra"] >= t["groups"] >= 0
    assert compare_profile("temperature_power", 1, "x", "y", 0, 0)
    assert (
        compare_profile(
            "temperature_power",
            **{
                "rows": 1_371_363,
                "first": "2024-09-16 16:58:30",
                "last": "2024-10-02 13:53:02",
                "groups": 499,
                "extra": 575,
            },
        )
        == []
    )
    st = {
        "raw_rows": 1_371_363,
        "group_sizes": {2: 497, 6: 1, 74: 1},
        "cells_made_missing_all_columns": 10_602,
        "blank_cells_all_columns": 0,
    }
    counts = {"retained": 1_370_289, "exact_duplicate": 0, "conflict_cell_missing": 1_074}
    assert compare_ledger("temperature_power", st, counts, 1_370_788) == []
    assert compare_ledger("temperature_power", {**st, "cells_made_missing_all_columns": 1}, counts, 1_370_788)


# ---------------------------------------------------------------------------------------------- production path through the adapter
TS0 = 946684800


def _ts(sec):
    s = int(sec)
    return f"2000-01-01 {s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def synth_rows(all_cols):
    """Deterministic synthetic rows with: singles, exact duplicate, tier-1 tie, outside-tier-1 tie, blank, near ties, 2 s step."""
    out = []
    ordinal = 0

    def add(sec, mutate=None, base=0.0):
        nonlocal ordinal
        ordinal += 1
        cells = {}
        for j, c in enumerate(all_cols):
            v = (100.0 if c.startswith("Power") else 20.0) + (sec % 7) * 0.5 + j * 0.01 + base
            cells[c] = f"{v:.4f}"
        if mutate:
            mutate(cells)
        out.append((ordinal, _ts(sec), cells))

    for sec in range(0, 6):
        add(sec)
    add(
        6,
        lambda c: c.update(
            {
                "Temperature mod 1 ch 1": "21.305",
                "Power Ch 1 (W)": "100.05",
                "Power Ch 2 (W)": "100.15",
                "Temperature mod 1 ch 3": "1.015",
            }
        ),
    )
    add(7, lambda c: c.update({"Temperature mod 1 ch 2": ""}))  # blank single (Tier 1)
    add(9)  # 2 s step
    for _ in range(2):  # exact duplicate pair at sec 10 (identical after rounding)
        add(10, lambda c: c.update({"Temperature mod 1 ch 1": "21.301", "Power Ch 1 (W)": "100.04"}))
    out[-1][2]["Temperature mod 1 ch 1"] = "21.299"
    add(11, lambda c: c.update({"Temperature mod 2 ch 1": "20.00"}))
    add(11, lambda c: c.update({"Temperature mod 2 ch 1": "20.50"}))  # tie in a Tier 1 column
    add(12, lambda c: c.update({"Temperature mod 3 ch 1": "5.00"}))
    add(12, lambda c: c.update({"Temperature mod 3 ch 1": "6.00"}))  # tie only OUTSIDE Tier 1
    add(12, lambda c: c.update({"Temperature mod 3 ch 1": "7.00"}))
    for sec in range(13, 20):
        add(sec)
    return out


def write_synth_csv(raw_dir: Path, rows_, all_cols):
    spec = spec_for_key("temperature_power")
    header = [spec.timestamp_column, *all_cols]
    lines = [",".join(header)]
    for _, ts, cells in rows_:
        lines.append(",".join([ts, *[cells[c] for c in all_cols]]))
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / spec.filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def synth(tmp_path):
    all_cols = sorted(spec_for_key("temperature_power").measurement_columns)
    rows_ = synth_rows(all_cols)
    raw = tmp_path / "raw"
    write_synth_csv(raw, rows_, all_cols)
    src = discover_all(raw, ["temperature_power"], manifest_path=None)["temperature_power"]
    return all_cols, rows_, src


@pytest.mark.parametrize("chunk", [2, 3, 5, None])
def test_file_path_equals_reference_path_for_every_chunking(synth, chunk):
    all_cols, rows_, src = synth
    reader = AdapterReader(src, chunksize=chunk)
    res_all = {c: PROTO.resolution(c, FILE) for c in reader.columns}
    got = clean_file(reader, PROTO)
    ref = clean_rows([RawRowIn(r, t, c) for r, t, c in rows_], list(reader.columns), res_all, PROTO, file=FILE)
    assert got.digest() == ref.digest()
    assert got.stats["group_sizes"] == {2: 2, 3: 1} == ref.stats["group_sizes"]
    assert got.stats["cells_made_missing_tier1"] == 1 == ref.stats["cells_made_missing_tier1"]
    assert got.stats["cells_made_missing_all_columns"] == 2  # one in Tier 1, one outside (3-row group, one column)
    assert got.stats["groups_with_ties_only_outside_tier1"] == 1
    assert got.stats["ambiguous_cells_all_columns"] >= 3  # 21.305 / 100.05 / 100.15 take the Decimal path
    assert got.stats["blank_cells_all_columns"] == 1
    assert reconcile(got) == []
    # the near-tie singles are exactly the protocol's half-even results
    j1, j2 = got.columns.index("Temperature mod 1 ch 1"), got.columns.index("Power Ch 2 (W)")
    k = list(got.ts_text).index(_ts(6))
    assert got.ticks[k, j1] == to_ticks("21.305", Decimal("0.01")) == 2130
    assert got.ticks[k, j2] == to_ticks("100.15", Decimal("0.1")) == 1002
    j3 = got.columns.index("Temperature mod 1 ch 3")
    assert got.ticks[k, j3] == to_ticks("1.015", Decimal("0.01")) == 102  # plain float rounding would give 101
    # blank single: missing with reason blank_cell
    kb = list(got.ts_text).index(_ts(7))
    jb = got.columns.index("Temperature mod 1 ch 2")
    assert not got.valid[kb, jb] and got.reason[kb, jb] == REASON_BLANK
    # the tie cell
    kt = list(got.ts_text).index(_ts(11))
    jt = got.columns.index("Temperature mod 2 ch 1")
    assert not got.valid[kt, jt] and got.reason[kt, jt] == REASON_TIE and got.valid[kt].sum() == 39
    # the 2 s step leaves an absent second (no row, no fill)
    assert _ts(8) not in set(got.ts_text)


def test_file_path_is_read_only_and_repeatable(synth, tmp_path):
    all_cols, rows_, src = synth
    before = src.source.path.read_bytes()
    a = clean_file(AdapterReader(src), PROTO)
    b = clean_file(AdapterReader(src, chunksize=4), PROTO)
    assert a.digest() == b.digest() and src.source.path.read_bytes() == before
    assert {p.name for p in src.source.path.parent.iterdir()} == {FILE}


def test_non_numeric_cell_is_refused_not_coerced(tmp_path):
    all_cols = sorted(spec_for_key("temperature_power").measurement_columns)
    rows_ = synth_rows(all_cols)
    rows_[0][2][all_cols[0]] = "abc"
    raw = tmp_path / "raw"
    write_synth_csv(raw, rows_, all_cols)
    src = discover_all(raw, ["temperature_power"], manifest_path=None)["temperature_power"]
    from research.danish_aau.adapter import AdapterError

    with pytest.raises(AdapterError):
        clean_file(AdapterReader(src), PROTO)


# ---------------------------------------------------------------------------------------------- L1 files
def _l1(res, out):
    return write_l1(
        res, out, dataset_id="danish-aau-v5", protocol_sha256=protocol_sha256(), source_file_sha256="0" * 64
    )


def test_l1_is_byte_identical_on_rerun_and_independent_of_input_order(synth, tmp_path):
    all_cols, rows_, src = synth
    res = clean_file(AdapterReader(src), PROTO)
    m1 = _l1(res, tmp_path / "a")
    m2 = _l1(clean_file(AdapterReader(src, chunksize=3), PROTO), tmp_path / "b")
    sh = rows_[:]
    random.Random(1).shuffle(sh)
    res_all = {c: PROTO.resolution(c, FILE) for c in all_cols}
    m3 = _l1(clean_rows([RawRowIn(r, t, c) for r, t, c in sh], all_cols, res_all, PROTO, file=FILE), tmp_path / "c")
    assert m1 == m2 == m3
    for rel in m1["files"]:
        assert (
            (tmp_path / "a" / rel).read_bytes()
            == (tmp_path / "b" / rel).read_bytes()
            == (tmp_path / "c" / rel).read_bytes()
        )
    assert verify_l1(tmp_path / "a") == []


def test_l1_content_format_and_no_local_text(synth, tmp_path):
    all_cols, rows_, src = synth
    res = clean_file(AdapterReader(src), PROTO)
    m = _l1(res, tmp_path / "o")
    assert len(m["files"]) == 41 and m["raw_rows"] == res.n_rows and m["unique_seconds"] == res.n_seconds
    obs = (tmp_path / "o" / "observations" / "temperature_mod_2_ch_1.tsv").read_bytes()
    assert b"\r" not in obs and obs.endswith(b"\n")
    lines = obs.decode("utf-8").split("\n")[:-1]
    assert lines[0] == "ts_text\tvalue_ticks\tstate\tquality\treason_code\tdisposition\tgroup_size\tfirst_row_ordinal"
    assert len(lines) == res.n_seconds + 1
    tie = [ln for ln in lines if ln.startswith(_ts(11))][0].split("\t")
    assert tie == [
        _ts(11),
        "",
        "missing",
        "",
        "conflict_unresolved_tie",
        "conflict_cell_missing",
        "2",
        str(res.first_row[list(res.ts_text).index(_ts(11))]),
    ]
    ok = [ln for ln in lines if ln.startswith(_ts(0))][0].split("\t")
    assert ok[2:6] == ["observed", "ok", "", "retained"] and ok[1].isdigit()
    ledger = (
        (tmp_path / "o" / "ledger" / "AAU_temperature_and_power_use.tsv").read_text(encoding="utf-8").split("\n")[:-1]
    )
    assert ledger[0].split("\t") == [
        "row_ordinal",
        "ts_text",
        "disposition",
        "reason_code",
        "group_size",
        "first_row_ordinal",
    ]
    assert len(ledger) == res.n_rows + 1
    manifest_text = (tmp_path / "o" / "l1_manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in manifest_text and "\\r" not in manifest_text
    mf = json.loads(manifest_text)
    assert (
        mf["time_basis"] == "source_text_undeclared_tz"
        and mf["protocol_sha256"] == protocol_sha256() == PROTOCOL_SHA256_V5
    )
    assert mf["tier1_columns"] == list(TIER1_COLUMNS) and "utc" not in manifest_text.lower()


def test_l1_verify_detects_tampering(synth, tmp_path):
    all_cols, rows_, src = synth
    _l1(clean_file(AdapterReader(src), PROTO), tmp_path / "o")
    p = tmp_path / "o" / "observations" / "power_ch_1_w.tsv"
    data = p.read_bytes()
    p.write_bytes(data.replace(b"observed", b"missing!", 1))
    assert any("sha256" in x for x in verify_l1(tmp_path / "o"))
    p.unlink()
    assert any("missing" in x for x in verify_l1(tmp_path / "o"))


# ---------------------------------------------------------------------------------------------- local script
def test_local_run_emits_aggregates_only(synth, tmp_path, monkeypatch):
    all_cols, rows_, src = synth
    from research.danish_aau.cleaning import local_run

    out = local_run.run(src.source.path.parent, keys=["temperature_power"], manifest_path=None, rerun=True)
    text = json.dumps(out, sort_keys=True)
    assert out["raw_directory_unchanged"] is True and out["protocol"]["sha256_lf"] == PROTOCOL_SHA256_V5
    c = out["cleaning"]["temperature_power"]
    assert c["tier1"]["cells_made_missing_by_tie"] == 1 and c["tier1"]["columns"] == 40
    assert c["tier1"]["groups_with_ties_only_outside_tier1"] == 1 and c["rerun_digest_identical"] is True
    assert c["ledger"]["reconciles"] and c["ledger_problems"] == []
    assert out["profile"]["temperature_power"]["repeated_timestamp_groups"] == 3
    assert out["profile"]["temperature_power"]["extra_rows"] == 4
    assert out["task4_differences"]  # the synthetic file deliberately differs from the real Task 4 table
    # no cell values: none of the synthetic cell texts appears in the JSON
    for _, _, cells in rows_[:5]:
        for v in list(cells.values())[:3]:
            assert f'"{v}"' not in text


# ---------------------------------------------------------------------------------------------- contract-shaped output rules
def test_observation_rows_obey_the_contract_state_reason_and_ledger_rules(synth, tmp_path):
    """Mirrors telemetry_contract.validate_record rules that depend only on cleaning output (E_STATE_REASON, E_LEDGER)."""
    import pandas as pd

    from research.danish_aau.cleaning.l1 import observation_frame

    all_cols, rows_, src = synth
    res = apply_flags(
        clean_file(AdapterReader(src), PROTO),
        PROTO,
        CleanConfig(range_limits={"temperature": ("0", "21.0")}, flatline_min_run=2),
    )
    assert (res.flag > 0).any()
    seen = set()
    for j in range(len(res.columns)):
        df = observation_frame(res, j)
        for st, q, rc, disp, gs in zip(
            df.state, df.quality, df.reason_code, df.disposition, df.group_size, strict=True
        ):
            seen.add((st, q, rc, disp))
            if st == "observed":
                assert q in ("ok", "flagged")
                assert (q == "flagged") == (rc != "")  # flagged requires a reason code; ok forbids it
                assert (disp == "flagged") == (q == "flagged")  # contract: disposition 'flagged' <=> quality 'flagged'
                assert rc in ("", "out_of_range", "flatline_run")
            else:
                assert st == "missing" and q == "" and rc in ("conflict_unresolved_tie", "blank_cell")
                if rc == "conflict_unresolved_tie":
                    assert disp == "conflict_cell_missing" and gs >= 2
        assert df.value_ticks.isna().tolist() == (df.state == "missing").tolist()
        assert not pd.isna(df.first_row_ordinal).any()
    assert ("missing", "", "conflict_unresolved_tie", "conflict_cell_missing") in seen
    assert any(s[2] == "out_of_range" for s in seen) and any(s[2] == "blank_cell" for s in seen)


def test_local_run_covers_all_sixteen_files_and_period_cleaning(tmp_path):
    from research.danish_aau.adapter.schema import FILE_SPECS
    from research.danish_aau.cleaning import local_run

    raw = tmp_path / "raw"
    raw.mkdir()
    ts = [
        "2000-01-01 00:00:00",
        "2000-01-01 00:00:01",
        "2000-01-01 00:00:01",
        "2000-01-01 00:00:03",
        "2000-01-01 00:20:00",
    ]
    for s in FILE_SPECS:
        cols = sorted(s.measurement_columns)
        lines = [",".join([s.timestamp_column, *cols])]
        for i, t in enumerate(ts):
            lines.append(
                ",".join([t, *[f"{(i + 1) * 0.5 + j + (0.5 if i == 2 else 0):.3f}" for j in range(len(cols))]])
            )
        (raw / s.filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = local_run.run(raw, include_periods=True, rerun=True, manifest_path=None)
    assert len(out["profile"]) == 16 and len(out["cleaning"]) == 7
    assert all(c["rerun_digest_identical"] and c["ledger"]["reconciles"] for c in out["cleaning"].values())
    gap = out["air_speed_50_cadence_gap"]
    assert gap["max_step_between"] == ["2000-01-01 00:00:03", "2000-01-01 00:20:00"] and gap["max_step_s"] == 1197.0
    json.dumps(out)  # serialisable aggregates
