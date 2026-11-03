"""Header-level inventory on synthetic fixtures (well-formed and deliberately malformed)."""

import hashlib

import synthetic_fixtures as fx

from research.danish_aau.evaluation.inventory import (
    count_data_rows,
    detect_delimiter,
    discover_csvs,
    format_inventory,
    inventory_raw,
    read_header,
)
from research.danish_aau.evaluation.registry import DEFAULT_REGISTRY


def test_matching_fixture_reports_all_registered_files_match(raw_dir, fixture_registry):
    rep = inventory_raw(raw_dir, fixture_registry, count_rows=True)
    assert rep["summary"]["all_registered_match"] is True
    assert rep["summary"]["n_match"] == 4 and rep["unregistered_csv"] == []
    assert all(c["status"] == "match" for f in rep["files"] for c in f["checks"])


def test_against_the_real_registry_the_tiny_fixture_is_reported_as_mismatch(raw_dir, fixture_registry):
    rep = inventory_raw(raw_dir, DEFAULT_REGISTRY, count_rows=True)  # sizes/rows can not match 46 MB / 90,902 rows
    assert rep["summary"]["n_mismatch"] == 4 and rep["summary"]["all_registered_match"] is False
    main = next(f for f in rep["files"] if f["key"] == "temperature_power_25")
    by_name = {c["name"]: c for c in main["checks"]}
    assert by_name["n_columns"]["status"] == "match"  # the synthetic header has 52 columns on purpose
    assert by_name["size_bytes"]["status"] == by_name["data_rows"]["status"] == "mismatch"


def test_missing_directory_and_missing_files(tmp_path, raw_dir, fixture_registry):
    rep = inventory_raw(tmp_path / "absent", fixture_registry)
    assert rep["raw_dir_exists"] is False and rep["summary"]["n_missing"] == 4
    (raw_dir / fixture_registry[0].filename).unlink()
    rep = inventory_raw(raw_dir, fixture_registry)
    assert rep["summary"]["n_missing"] == 1 and rep["summary"]["n_match"] == 3


def test_unregistered_csvs_are_listed_without_interpretation(raw_dir, fixture_registry):
    fx.write_csv(raw_dir / "sub" / "AAU_other_50_percent.csv", ["Time [Date/Time]", "a"], [["2024-01-01 00:00:00", 1]])
    rep = inventory_raw(raw_dir, fixture_registry)
    assert [u["relpath"] for u in rep["unregistered_csv"]] == ["sub/AAU_other_50_percent.csv"]
    assert "not audited" in rep["unregistered_csv"][0]["note"]


def test_duplicate_registered_filename_is_ambiguous_and_not_checked(raw_dir, fixture_registry):
    name = fixture_registry[1].filename
    (raw_dir / "copy").mkdir()
    (raw_dir / "copy" / name).write_bytes((raw_dir / name).read_bytes())
    rep = inventory_raw(raw_dir, fixture_registry)
    entry = next(f for f in rep["files"] if f["filename"] == name)
    assert entry["status"] == "ambiguous" and len(entry["candidates"]) == 2


def test_filename_match_is_case_insensitive_like_windows(raw_dir, fixture_registry):
    f = raw_dir / fixture_registry[2].filename
    f.rename(raw_dir / fixture_registry[2].filename.upper().replace(".CSV", ".csv"))
    rep = inventory_raw(raw_dir, fixture_registry)
    assert rep["summary"]["n_match"] == 4


def test_wrong_column_count_and_wrong_first_column_are_flagged(raw_dir, fixture_registry):
    name = fixture_registry[2].filename
    fx.write_csv(raw_dir / name, ["when", "Outdoor_temperature"], [["2024-09-17 09:40:00", 1.0]])
    rep = inventory_raw(raw_dir, fixture_registry)
    entry = next(f for f in rep["files"] if f["filename"] == name)
    bad = {c["name"] for c in entry["checks"] if c["status"] == "mismatch"}
    assert {"n_columns", "first_column", "size_bytes"} <= bad


def test_column_classification_summary_for_the_52_column_header(raw_dir, fixture_registry):
    rep = inventory_raw(raw_dir, fixture_registry)
    main = next(f for f in rep["files"] if f["key"] == "temperature_power_25")
    assert main["columns"]["by_kind"] == {"power": 3, "temperature": 48, "timestamp": 1}
    assert main["columns"]["unclassified_count"] == 0
    vent = next(f for f in rep["files"] if f["key"] == "ventilation")
    assert len(vent["columns"]["unit_unconfirmed_columns"]) == 6


def test_unknown_columns_surface_as_unclassified(raw_dir, fixture_registry):
    name = fixture_registry[1].filename
    fx.write_csv(raw_dir / name, ["Time [Date/Time]", "velocity 1", "mystery"], [["2024-09-17 09:40:00", 1, 2]])
    rep = inventory_raw(raw_dir, fixture_registry)
    entry = next(f for f in rep["files"] if f["filename"] == name)
    assert entry["columns"]["unclassified_columns"] == ["mystery"]


def test_hash_option_matches_hashlib(raw_dir, fixture_registry):
    rep = inventory_raw(raw_dir, fixture_registry, hash_files=True)
    for f in rep["files"]:
        assert f["sha256"] == hashlib.sha256((raw_dir / f["filename"]).read_bytes()).hexdigest()
    assert inventory_raw(raw_dir, fixture_registry)["files"][0]["sha256"] is None


def test_delimiter_detection():
    assert detect_delimiter("a,b,c")[0] == ","
    assert detect_delimiter("a;b;c")[0] == ";"
    assert detect_delimiter("a\tb\tc")[0] == "\t"
    assert detect_delimiter('"a,1",b')[0] == ","  # quoted comma is not a separator
    assert detect_delimiter("a,b;c")[0] is None  # tie -> ambiguous, not guessed
    assert detect_delimiter("justonecolumn")[0] is None


def test_header_reading_handles_bom_crlf_semicolons_and_bad_encoding(raw_dir):
    p = fx.write_csv(raw_dir / "bom.csv", ["time", "a", "b"], [[1, 2, 3]], bom=True, newline="\r\n", delimiter=";")
    h = read_header(p, raw_dir)
    assert (h["bom"], h["delimiter"], h["columns"]) == (True, ";", ["time", "a", "b"])
    bad = raw_dir / "latin.csv"
    bad.write_bytes(b"time,temp \xb0C\n1,2\n")
    h = read_header(bad, raw_dir)
    assert h["encoding_utf8"] is False and h["n_columns"] == 2


def test_row_counting_ignores_blank_lines_and_crlf(raw_dir):
    p = fx.write_csv(raw_dir / "r.csv", ["t", "v"], [[1, 1], [2, 2], [3, 3]], newline="\r\n", trailing_blank_lines=3)
    assert count_data_rows(p, raw_dir) == 3
    assert count_data_rows(fx.write_csv(raw_dir / "h.csv", ["t", "v"], []), raw_dir) == 0


def test_discovery_is_recursive_sorted_and_csv_only(raw_dir, fixture_registry):
    (raw_dir / "notes.txt").write_text("x", encoding="utf-8")
    fx.write_csv(raw_dir / "z" / "a.CSV", ["t"], [])
    names = [p.relative_to(raw_dir).as_posix() for p in discover_csvs(raw_dir)]
    assert names == sorted(names) and "z/a.CSV" in names and "notes.txt" not in names


def test_console_table_is_ascii_and_states_the_caveat(raw_dir, fixture_registry):
    text = format_inventory(inventory_raw(raw_dir, DEFAULT_REGISTRY))
    assert text.isascii() and "unverified" in text
