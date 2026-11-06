from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research.danish_aau.adapter import (
    FILE_SPECS,
    AdapterDiscoveryError,
    AdapterError,
    AdapterReader,
    AdapterSchemaError,
    discover_all,
    make_source_ref,
)
from research.danish_aau.adapter.schema import column_meta, spec_for_key
from research.danish_aau.adapter.source import DEFAULT_MANIFEST, load_manifest
from research.danish_aau.contract.telemetry_contract import validate_record

EXAMPLES = Path(__file__).resolve().parents[2] / "contract" / "examples"


def _header(spec, cols=None):
    cols = list(spec.measurement_columns) if cols is None else cols
    return [spec.timestamp_column, *sorted(cols, key=_order(spec))]


def _order(spec):
    return lambda c: c  # deterministic synthetic header order


def _write(path: Path, spec, rows, cols=None, blank_after=None):
    header = _header(spec, cols)
    lines = [",".join(header)]
    for i, ts in enumerate(rows):
        vals = [
            ("" if (j + i) % 17 == 0 and spec.family == "ventilation" else f"{(i + 1) * 0.5 + j:.3f}")
            for j in range(len(header) - 1)
        ]
        lines.append(",".join([ts, *vals]))
        if blank_after == i:
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


TS = ["2000-01-01 00:00:00", "2000-01-01 00:00:01", "2000-01-01 00:00:01", "2000-01-01 00:00:03"]  # one repeated stamp


@pytest.fixture
def raw(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    for s in FILE_SPECS:
        _write(d / s.filename, s, TS)
    return d


@pytest.fixture
def manifest(tmp_path, raw):
    files = []
    for s in FILE_SPECS:
        p = raw / s.filename
        files.append(
            {
                "filename": s.filename,
                "size_bytes": p.stat().st_size,
                "zenodo_md5": "md5:x",
                "local_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "md5_verified": True,
            }
        )
    m = tmp_path / "manifest.json"
    m.write_text("\ufeff" + json.dumps({"files": files}), encoding="utf-8")
    return m


# ------------------------------------------------------------------ schema
def test_schema_matches_task4_profile_and_manifest():
    assert len(FILE_SPECS) == 16 and len({s.key for s in FILE_SPECS}) == 16
    counts = {s.family: s.n_columns for s in FILE_SPECS}
    assert counts == {"temperature_power": 52, "air_speed": 17, "surrounding_temperatures": 7, "ventilation": 7}
    names = {s.filename.lower() for s in FILE_SPECS}
    assert names == {n for n in load_manifest(DEFAULT_MANIFEST) if n.endswith(".csv")}


def test_schema_equals_task6_runner_register():
    from research.danish_aau.screening.run_task6_screen import REGISTER

    assert spec_for_key("temperature_power").measurement_columns == frozenset(REGISTER)


def test_units_come_only_from_documented_rules():
    tp, air, sur = spec_for_key("temperature_power"), spec_for_key("air_speed"), spec_for_key("ventilation")
    assert column_meta(tp, "Power Ch 2 (W)").unit == "W"
    assert column_meta(tp, "Temperature mod 1 ch 1").unit == "degC"
    assert column_meta(air, "velocity 3").measurand == "air_speed"
    assert column_meta(sur, "Room_damper_opening").unit == "not_established"
    assert column_meta(tp, "Power Ch 2 (kW)") is None  # a different unit is not recognised


# ------------------------------------------------------------------ discovery / rejection
def test_discover_all_is_deterministic_and_complete(raw, manifest):
    a, b = discover_all(raw, manifest_path=manifest), discover_all(raw, manifest_path=manifest)
    assert list(a) == [s.key for s in FILE_SPECS] == list(b)
    assert all(v.file_sha256 and len(v.file_sha256) == 64 for v in a.values())


def test_missing_file_rejected(raw, manifest):
    (raw / FILE_SPECS[3].filename).unlink()
    with pytest.raises(AdapterDiscoveryError):
        discover_all(raw, manifest_path=manifest)


def test_unexpected_csv_rejected_in_strict_mode(raw, manifest):
    (raw / "AAU_extra.csv").write_text("a,b\n1,2\n")
    with pytest.raises(AdapterDiscoveryError, match="unexpected CSV"):
        discover_all(raw, manifest_path=manifest)
    assert discover_all(raw, manifest_path=manifest, strict=False)


def test_size_mismatch_with_manifest_rejected(raw, manifest):
    p = raw / FILE_SPECS[0].filename
    p.write_text(p.read_text() + "2000-01-01 00:00:09," + ",".join("1" for _ in range(51)) + "\n")
    with pytest.raises(AdapterDiscoveryError, match="differs from the manifest"):
        discover_all(raw, manifest_path=manifest)


def test_unexpected_unit_column_rejected(raw):
    s = spec_for_key("temperature_power_25")
    cols = [c.replace("Power Ch 1 (W)", "Power Ch 1 (kW)") for c in s.measurement_columns]
    _write(raw / s.filename, s, TS, cols=cols)
    with pytest.raises(AdapterSchemaError, match=r"unexpected column.*kW.*|missing column"):
        discover_all(raw, ["temperature_power_25"], manifest_path=None)


def test_extra_missing_and_duplicate_columns_rejected(raw):
    s = spec_for_key("air_speed_25")
    _write(raw / s.filename, s, TS, cols=[*s.measurement_columns, "velocity 17"])
    with pytest.raises(AdapterSchemaError, match="velocity 17"):
        discover_all(raw, ["air_speed_25"], manifest_path=None)
    _write(raw / s.filename, s, TS, cols=[c for c in s.measurement_columns if c != "velocity 1"])
    with pytest.raises(AdapterSchemaError, match="missing column"):
        discover_all(raw, ["air_speed_25"], manifest_path=None)
    _write(raw / s.filename, s, TS)
    p = raw / s.filename
    p.write_text(p.read_text().replace("velocity 2", "velocity 1", 1))
    with pytest.raises(AdapterSchemaError, match="duplicate header"):
        discover_all(raw, ["air_speed_25"], manifest_path=None)


def test_wrong_first_column_and_delimiter_rejected(raw):
    s = spec_for_key("ventilation")
    p = raw / s.filename
    p.write_text(p.read_text().replace("time,", "when,", 1))
    with pytest.raises(AdapterSchemaError, match="first column"):
        discover_all(raw, ["ventilation"], manifest_path=None)
    p.write_text(p.read_text().replace(",", ";"))
    with pytest.raises(AdapterSchemaError, match="delimiter"):
        discover_all(raw, ["ventilation"], manifest_path=None)


def test_non_numeric_cell_and_bad_timestamp_rejected(raw):
    s = spec_for_key("surrounding_temperatures")
    p = raw / s.filename
    lines = p.read_text().splitlines()
    parts = lines[1].split(",")
    parts[2] = "abc"
    lines[1] = ",".join(parts)
    p.write_text("\n".join(lines) + "\n")
    rd = AdapterReader(discover_all(raw, ["surrounding_temperatures"], manifest_path=None)["surrounding_temperatures"])
    rd.build_index()
    with pytest.raises(AdapterError, match="non-numeric"):
        list(rd.iter_cells())
    _write(p, s, ["2000-01-01 00:00:00", "01/01/2000 00:00:01"])
    with pytest.raises(AdapterError, match="timestamp"):
        AdapterReader(
            discover_all(raw, ["surrounding_temperatures"], manifest_path=None)["surrounding_temperatures"]
        ).build_index()


# ------------------------------------------------------------------ reading
def _reader(raw, key, **kw):
    r = AdapterReader(discover_all(raw, [key], manifest_path=None)[key], **kw)
    r.build_index()
    return r


def test_cells_have_stable_refs_and_keep_duplicates(raw):
    r = _reader(raw, "air_speed_25")
    cells = list(r.iter_cells(["velocity 1"]))
    assert [(c.row_ordinal, c.ts_text) for c in cells] == [(1, TS[0]), (2, TS[1]), (3, TS[2]), (4, TS[3])]
    assert cells[1].value_text != cells[2].value_text  # same timestamp, two rows, nothing resolved
    assert cells[0].file == "AAU_air_speed_25_percent_load_period.csv" and cells[0].value == float(cells[0].value_text)


def test_blank_cells_are_none_and_text_preserved(raw):
    r = _reader(raw, "ventilation")
    cells = list(r.iter_cells())
    blanks = [c for c in cells if c.value_text == ""]
    assert blanks and all(c.value is None for c in blanks)


def test_reruns_and_chunk_sizes_give_identical_output(raw):
    f1 = _reader(raw, "temperature_power_25").fingerprint()
    f2 = _reader(raw, "temperature_power_25").fingerprint()
    f3 = _reader(raw, "temperature_power_25", chunksize=2).fingerprint()
    assert f1 == f2 == f3
    r = _reader(raw, "temperature_power_25", chunksize=3)
    assert r.verify_integrity()["rows"] == 4


def test_cell_order_is_file_row_then_header_column(raw):
    r = _reader(raw, "air_speed_25", chunksize=2)
    cells = list(r.iter_cells(["velocity 2", "velocity 1"]))
    assert [(c.row_ordinal, c.column) for c in cells[:4]] == [
        (1, "velocity 2"),
        (1, "velocity 1"),
        (2, "velocity 2"),
        (2, "velocity 1"),
    ]


def test_unknown_column_selection_rejected(raw):
    with pytest.raises(AdapterError):
        list(_reader(raw, "air_speed_25").iter_cells(["velocity 99"]))


def test_raw_files_unchanged_by_reading(raw, manifest):
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in raw.iterdir()}
    for k, v in discover_all(raw, manifest_path=manifest).items():
        r = AdapterReader(v)
        r.build_index()
        r.fingerprint()
        r.verify_integrity()
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in raw.iterdir()}
    assert sorted(p.name for p in raw.iterdir()) == sorted(before)


# ------------------------------------------------------------------ row ordinal vs Task 6 runner; contract
def test_row_ordinal_matches_task6_runner_including_blank_lines(tmp_path):
    from research.danish_aau.protocol.protocol import load_protocol
    from research.danish_aau.screening.run_task6_screen import read_panel

    raw = tmp_path / "r"
    raw.mkdir()
    s = spec_for_key("temperature_power_25")
    ts = [f"2000-01-01 00:00:{i:02d}" for i in range(6)]
    _write(raw / s.filename, s, ts, blank_after=2)  # a blank line in the middle
    panel = read_panel(raw / s.filename, load_protocol())
    r = _reader(raw, "temperature_power_25")
    ordinals = {c.row_ordinal: c.ts_text for c in r.iter_cells([next(iter(sorted(s.measurement_columns)))])}
    assert len(panel["secs"]) == len(ordinals) == 6
    import numpy as np

    for k, text in ordinals.items():  # runner position k-1 <-> adapter ordinal k (1-based, header excluded)
        assert int(panel["secs"][k - 1]) == int(np.datetime64(text.replace(" ", "T"), "s").astype("int64"))


def test_source_ref_passes_contract_validator():
    rec = json.loads((EXAMPLES / "record_observed_temperature.json").read_text())
    assert validate_record(rec) == []
    ref = make_source_ref(rec["source_ref"]["file"], rec["source_ref"]["column"], 1, rec["ts_source_text"], "a" * 64)
    ok = copy.deepcopy(rec)
    ok["source_ref"] = ref
    assert validate_record(ok) == []
    assert set(ref) == set(rec["source_ref"])
    with pytest.raises(AdapterError):
        make_source_ref("a|b.csv", "c", 1, "t", None)
    bad = copy.deepcopy(ok)
    bad["source_ref"]["key"] = "wrong"
    assert any("E_SOURCE_REF" in e for e in validate_record(bad))


def test_local_check_on_fixture(raw, manifest):
    import research.danish_aau.adapter.local_check as lc

    rep = lc.run(raw, rerun=True, keys=["air_speed_25", "ventilation"], manifest_path=manifest)
    assert rep["raw_directory_unchanged"] and set(rep["files"]) == {"air_speed_25", "ventilation"}
    f = rep["files"]["air_speed_25"]
    assert f["rows"] == 4 and f["rows_in_repeated_timestamp_groups"] == 2 and f["fingerprint_rerun_identical"]
    assert set(f) >= {"integrity", "fingerprint", "first_ts_text", "last_ts_text"}  # aggregates only, no cell values
