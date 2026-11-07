"""Task 15: dataset bundle tests. SYNTHETIC fixtures only (year-2000 timestamps, patterned values); no realData."""

from __future__ import annotations

import ast
import calendar
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from research.danish_aau.adapter.schema import spec_for_key
from research.danish_aau.cleaning import CleanConfig
from research.danish_aau.panel import build_panel
from src.dataset_bundle import (
    BundleError,
    BundleNotFound,
    dataset_version,
    derived_history,
    entities,
    format_ticks,
    history,
    open_readonly,
)
from src.dataset_bundle import __main__ as cli
from src.dataset_bundle.loader import REAL_REFERENCE, build_bundle
from src.dataset_bundle.verify import verify_bundle

FILE = "AAU_temperature_and_power_use.csv"
ALL_COLS = sorted(spec_for_key("temperature_power").measurement_columns)
T1 = "danish-aau-v5.temperature.mod1.ch1"
DERIVED = "derived.rack_power_total_1_6"


def _ts(sec: int) -> str:
    return f"2000-01-01 {sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def _row(sec: int, **over: str) -> str:
    cells = []
    for j, c in enumerate(ALL_COLS):
        v = (100.0 if c.startswith("Power") else 20.0) + (sec % 7) * 0.5 + j * 0.01
        cells.append(over.get(c, f"{v:.4f}"))
    return ",".join([_ts(sec), *cells])


def write_raw(raw: Path, lines: list[str]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    header = ",".join([spec_for_key("temperature_power").timestamp_column, *ALL_COLS])
    (raw / FILE).write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")


def synth_lines(skip: tuple[int, ...] = ()) -> list[str]:
    ln = [_row(s) for s in range(0, 6) if s not in skip]
    ln.append(_row(6, **{"Temperature mod 1 ch 1": "21.305", "Power Ch 1 (W)": "100.05"}))
    ln.append(_row(7, **{"Temperature mod 1 ch 2": ""}))  # blank single, Tier 1
    ln += [_row(8), _row(8, **{"Power Ch 2 (W)": "999.0"})]  # tie in a power channel: derived undefined
    ln += [_row(9), _row(9)]  # exact duplicate pair
    ln += [_row(10, **{"Temperature mod 2 ch 1": "20.00"}), _row(10, **{"Temperature mod 2 ch 1": "20.50"})]
    ln += [_row(11, **{"Temperature mod 3 ch 1": "5.00"}), _row(11, **{"Temperature mod 3 ch 1": "6.00"})]  # not Tier 1
    ln += [_row(s) for s in range(12, 20)]
    return ln


def _panel(tmp_path: Path, name: str = "p", lines=None, **kw) -> Path:
    raw = tmp_path / f"raw_{name}"
    write_raw(raw, lines or synth_lines())
    out = tmp_path / f"panel_{name}"
    build_panel(raw, out, manifest_path=None, **kw)
    return out


@pytest.fixture
def panel(tmp_path):
    return _panel(tmp_path)


@pytest.fixture
def built(panel, tmp_path):
    out = tmp_path / "bundle" / "danish-aau-v5.sqlite"
    return out, build_bundle(panel, out)


def _file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------ build and counts
def test_build_loads_the_panel_and_reconciles_every_count(built, panel):
    out, rep = built
    c = rep["counts"]
    assert c["stored_cells"] == 40 * 20 == c["inserted"] == rep["read_back"]["observation_rows"]
    assert (c["skipped"], c["invalid"], c["conflict"]) == (0, 0, 0)
    assert c["observed_cells"] + c["tier1_conflict_missing_cells"] + c["blank_cells"] == c["stored_cells"]
    assert (
        c["tier1_conflict_missing_cells"] == 2 and c["blank_cells"] == 1
    )  # one power tie, one rack-probe tie, one blank
    assert c["raw_rows"] == 24 and c["unique_seconds"] == 20
    assert c["derived_defined_seconds"] == 19 and c["derived_undefined_seconds"] == 1  # only the Power Ch 2 tie second
    assert c["ledger_by_disposition"] == {"conflict_cell_missing": 6, "exact_duplicate": 1, "retained": 17}
    assert rep["stream"] == "import:danish-aau-v5" and c["reference_check"] == {"status": "not_applicable"}
    conn = open_readonly(out)
    try:
        d = dataset_version(conn)
    finally:
        conn.close()
    assert d["access_status"] == "local_only" and d["time_basis"] == "source_text_undeclared_tz"
    assert d["licence_name"] == "CC BY 4.0" and "10.5281/zenodo.21262042" in d["attribution_text"]
    assert "rounded half-even" in d["modifications_statement"]
    assert d["panel_sha256"] == json.loads((panel / "panel_manifest.json").read_text())["panel_sha256"]
    assert verify_bundle(out, panel, deep=True)["problems"] == []


def test_rebuild_is_idempotent_and_never_duplicates(built, panel):
    out, rep1 = built
    sha1 = _file_sha(out)
    rep2 = build_bundle(panel, out)
    assert _file_sha(out) == sha1  # byte-identical bundle
    assert rep2["content_digest"] == rep1["content_digest"] and rep2["read_back"] == rep1["read_back"]
    assert not out.with_name(out.name + ".building").exists()


def test_real_reference_constants_are_internally_consistent():
    r = REAL_REFERENCE
    assert r["stored_cells"] == 40 * r["unique_seconds"] == 54_831_520
    assert r["observed_cells"] + r["tier1_conflict_missing_cells"] + r["blank_cells"] == r["stored_cells"]
    assert r["derived_defined_seconds"] + r["derived_undefined_seconds"] == r["unique_seconds"]


# ------------------------------------------------------------------------------------------------ what is stored
def test_missing_cells_are_missing_with_a_reason_never_imputed(built):
    out, _ = built
    conn = open_readonly(out)
    try:
        rows = {r["ts_source_text"]: r for r in history(conn, "danish-aau-v5.temperature.mod1.ch2", limit=1000)}
        blank = rows[_ts(7)]
        assert blank["state"] == "missing" and blank["value"] is None and blank["reason_code"] == "blank_cell"
        assert blank["quality"] is None
        tie = {r["ts_source_text"]: r for r in history(conn, "danish-aau-v5.power.ch2", limit=1000)}[_ts(8)]
        assert tie["state"] == "missing" and tie["value"] is None and tie["reason_code"] == "conflict_unresolved_tie"
        assert tie["disposition"] == "conflict_cell_missing" and tie["group_size"] == 2 and tie["row_ordinal"] == 9
        dup = history(conn, T1, from_t=calendar.timegm((2000, 1, 1, 0, 0, 9, 0, 0, 0)), limit=1)[0]
        assert dup["disposition"] == "retained" and dup["group_size"] == 2 and dup["state"] == "observed"
    finally:
        conn.close()


def test_values_are_exact_decimal_text_from_integer_ticks(built):
    out, _ = built
    conn = open_readonly(out)
    try:
        r = {x["ts_source_text"]: x for x in history(conn, T1, limit=1000)}[_ts(6)]
        assert (r["value_ticks"], r["value"], r["unit"]) == (2130, "21.30", "degC")  # 21.305 half-even
        p = {x["ts_source_text"]: x for x in history(conn, "danish-aau-v5.power.ch1", limit=1000)}[_ts(6)]
        assert (p["value_ticks"], p["value"], p["unit"]) == (1000, "100.0", "W")  # 100.05 half-even at 0.1 W
    finally:
        conn.close()
    assert format_ticks(5, 2) == "0.05" and format_ticks(-5, 2) == "-0.05" and format_ticks(-2130, 2) == "-21.30"
    assert format_ticks(7, 0) == "7" and format_ticks(None, 2) is None and format_ticks(1000, 1) == "100.0"


def test_an_absent_second_has_no_row_and_nothing_is_filled(tmp_path):
    panel = _panel(tmp_path, "gap", lines=synth_lines(skip=(3,)))
    out = tmp_path / "b.sqlite"
    rep = build_bundle(panel, out)
    assert rep["counts"]["unique_seconds"] == 19
    conn = open_readonly(out)
    try:
        texts = [r["ts_source_text"] for r in history(conn, T1, limit=1000)]
        assert _ts(3) not in texts and len(texts) == 19
        assert conn.execute("SELECT COUNT(*) FROM second WHERE ts_text = ?", (_ts(3),)).fetchone()[0] == 0
    finally:
        conn.close()


def test_time_key_is_naive_label_seconds_and_no_zone_is_applied(built):
    out, _ = built
    conn = open_readonly(out)
    try:
        for r in conn.execute("SELECT t_naive_s, ts_text FROM second"):
            y, mo, d = int(r[1][:4]), int(r[1][5:7]), int(r[1][8:10])
            hh, mm, ss = int(r[1][11:13]), int(r[1][14:16]), int(r[1][17:19])
            assert r[0] == calendar.timegm((y, mo, d, hh, mm, ss, 0, 0, 0))
        assert "utc" not in " ".join(c[1].lower() for c in conn.execute("PRAGMA table_info(second)"))
    finally:
        conn.close()


def test_registry_carries_attribution_and_never_splits_group_power(built):
    out, _ = built
    conn = open_readonly(out)
    try:
        ents = {e["external_id"]: e for e in entities(conn)}
        assert len([e for e in ents.values() if e["kind"] == "channel"]) == 79
        assert len([e for e in ents.values() if e["kind"] == "rack"]) == 6
        p1, p2, p3 = (ents[f"danish-aau-v5.power.ch{n}"] for n in (1, 2, 3))
        assert (p1["attribution_scope"], p1["member_source_rack_ids"]) == ("rack_group", ["1", "2", "3"])
        assert (p2["attribution_scope"], p2["member_source_rack_ids"]) == ("rack_group", ["4", "6"])
        assert (p3["attribution_scope"], p3["member_source_rack_ids"]) == ("rack", ["5"])
        assert all(e["split_allowed"] == 0 for e in ents.values() if e["kind"] == "channel")
        loaded = [e for e in ents.values() if e["kind"] == "channel" and e["provenance"] == "measured"]
        assert len(loaded) == 40 and {e["tier"] for e in loaded} == {"tier1"}
        deferred = [e for e in ents.values() if e["tier"] == "deferred"]
        assert len(deferred) == 12 and all(e["provenance"] is None for e in deferred)
        with pytest.raises(BundleError):  # registered but not loaded
            history(conn, "danish-aau-v5.temperature.mod3.ch1")
    finally:
        conn.close()


def test_schema_forbids_a_split_flag_and_a_non_derived_provenance(built, tmp_path):
    out, _ = built
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(out.read_bytes())
    w = sqlite3.connect(copy)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            w.execute("UPDATE entity SET split_allowed = 1 WHERE kind = 'channel'")
        with pytest.raises(sqlite3.IntegrityError):
            w.execute("UPDATE derived_series SET provenance = 'measured'")
        with pytest.raises(sqlite3.IntegrityError):
            w.execute("UPDATE derived_series SET split_per_rack = 1")
        with pytest.raises(sqlite3.IntegrityError):  # an observed cell must carry a value and a quality
            w.execute("UPDATE observation SET value_ticks = NULL WHERE state = 0")
    finally:
        w.close()


# ------------------------------------------------------------------------------------------------ measured vs derived
def test_derived_values_live_in_their_own_tables_and_routes(built):
    out, _ = built
    conn = open_readonly(out)
    try:
        assert not conn.execute(
            "SELECT 1 FROM entity WHERE external_id LIKE 'derived.%' OR entity_id LIKE 'derived.%'"
        ).fetchall()
        with pytest.raises(BundleError):
            history(conn, DERIVED)  # a measured route never serves a derived series
        with pytest.raises(BundleError):
            derived_history(conn, T1)  # and the derived route never serves a measured channel
        rows = {r["ts_source_text"]: r for r in derived_history(conn, DERIVED, limit=1000)}
        assert rows[_ts(0)]["value_ticks"] == 3000 and rows[_ts(0)]["value"] == "300.0"
        assert rows[_ts(0)]["provenance"] == "derived" and rows[_ts(0)]["output_scope"] == "rack_group"
        assert rows[_ts(0)]["output_member_source_rack_ids"] == ["1", "2", "3", "4", "5", "6"]
        gone = rows[_ts(8)]  # Power Ch 2 tie -> no partial sum
        assert gone["state"] == "missing" and gone["value"] is None and gone["reason_code"] == "inputs_not_all_observed"
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert names == {
            "dataset_version", "reason_code", "disposition", "entity", "second", "observation", "derived_series",
            "derived_observation",
        }  # fmt: skip
        assert not any("telemetry_sample" in n for n in names)
    finally:
        conn.close()


def test_history_paging_is_half_open_keyset_and_capped(built):
    out, _ = built
    conn = open_readonly(out)
    try:
        allr = history(conn, T1, limit=1000)
        t = [r["t_naive_s"] for r in allr]
        assert t == sorted(set(t)) and len(t) == 20
        page = history(conn, T1, limit=7)
        nxt = history(conn, T1, after_t=page[-1]["t_naive_s"], limit=7)
        assert [r["t_naive_s"] for r in page + nxt] == t[:14]
        rng = history(conn, T1, from_t=t[2], to_t=t[5], limit=1000)
        assert [r["t_naive_s"] for r in rng] == t[2:5]  # [from, to)
        assert len(history(conn, T1, limit=10**6)) == 20 and len(history(conn, T1, limit=0)) == 1
        assert [r["t_naive_s"] for r in derived_history(conn, DERIVED, from_t=t[2], to_t=t[4])] == t[2:4]
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------ read-only and absence
def test_bundle_is_read_only_and_absence_is_a_distinct_error(built, tmp_path):
    out, _ = built
    conn = open_readonly(out)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM observation")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE x (a)")
    finally:
        conn.close()
    with pytest.raises(BundleNotFound):
        open_readonly(tmp_path / "missing.sqlite")
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a database" * 100)
    with pytest.raises(BundleError):
        open_readonly(junk)


def test_runtime_reader_imports_only_the_standard_library_and_the_package():
    import src.dataset_bundle.reader as reader_mod

    tree = ast.parse(Path(reader_mod.__file__).read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            mods.add((n.module or "").split(".")[0])
    assert mods <= {"__future__", "json", "sqlite3", "pathlib", "typing"}


def test_package_never_touches_shared_tables_or_the_writer():
    src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in Path(__import__("src.dataset_bundle").dataset_bundle.__file__).parent.glob("*.py")
    )
    for banned in (
        "ingest_samples",
        "INSERT INTO telemetry_sample",
        "from database",
        "import database",
        "alembic",
        "timezone.utc",
        "tzinfo",
    ):
        assert banned not in src, banned


# ------------------------------------------------------------------------------------------------ refusals and integrity
def test_a_tampered_panel_is_refused_and_the_previous_bundle_stays(built, panel):
    out, _ = built
    before = _file_sha(out)
    f = panel / "l1" / "observations" / "power_ch_1_w.tsv"
    f.write_bytes(f.read_bytes().replace(b"\t1000\t", b"\t1001\t", 1))
    with pytest.raises(BundleError, match="does not verify"):
        build_bundle(panel, out)
    assert _file_sha(out) == before and not out.with_name(out.name + ".building").exists()


def test_a_non_default_cleaning_configuration_is_refused(tmp_path):
    p = _panel(tmp_path, "cfg", config=CleanConfig(flatline_min_run=50))
    with pytest.raises(BundleError, match="non-default cleaning"):
        build_bundle(p, tmp_path / "b.sqlite")
    assert not (tmp_path / "b.sqlite").exists()


def test_location_rules(panel, tmp_path):
    with pytest.raises(BundleError, match="separate"):
        build_bundle(panel, panel / "inside.sqlite")
    from src.dataset_bundle.loader import REPO_ROOT

    with pytest.raises(BundleError, match="realData"):
        build_bundle(panel, REPO_ROOT / "reports" / "x" / "b.sqlite")
    assert not (REPO_ROOT / "reports" / "x").exists()


def test_verify_detects_a_changed_value_and_a_wrong_panel(built, panel, tmp_path):
    out, _ = built
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(out.read_bytes())
    w = sqlite3.connect(bad)
    w.execute(
        "UPDATE observation SET value_ticks = value_ticks + 1 WHERE entity_pk = 1 AND t_naive_s = (SELECT MIN(t_naive_s) FROM second)"
    )
    w.commit()
    w.close()
    res = verify_bundle(bad, panel)
    assert any("content digest" in p for p in res["problems"])
    assert any("bundle values differ" in p for p in verify_bundle(bad, panel, deep=True)["problems"])
    other = _panel(tmp_path, "other", lines=synth_lines(skip=(2,)))
    assert any("panel_sha256" in p for p in verify_bundle(out, other)["problems"])


def test_verify_detects_a_wrong_derived_value(built, tmp_path):
    out, _ = built
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(out.read_bytes())
    w = sqlite3.connect(bad)
    w.execute(
        "UPDATE derived_observation SET value_ticks = value_ticks + 1 WHERE state = 0 AND t_naive_s = (SELECT MIN(t_naive_s) FROM second)"
    )
    w.commit()
    w.close()
    assert any("derived values differ" in p for p in verify_bundle(bad)["problems"])


# ------------------------------------------------------------------------------------------------ command line
def test_cli_build_verify_info_and_refusal(panel, tmp_path, capsys):
    out = tmp_path / "cli.sqlite"
    assert cli.main(["build", "--panel", str(panel), "--out", str(out), "--report", str(tmp_path / "r.json")]) == 0
    assert json.loads((tmp_path / "r.json").read_text())["counts"]["inserted"] == 800
    assert cli.main(["verify", "--bundle", str(out), "--panel", str(panel)]) == 0
    assert cli.main(["info", "--bundle", str(out)]) == 0
    assert '"access_status": "local_only"' in capsys.readouterr().out
    assert cli.main(["build", "--panel", str(tmp_path / "nope"), "--out", str(tmp_path / "x.sqlite")]) == 2
    assert cli.main(["verify", "--bundle", str(tmp_path / "missing.sqlite")]) == 2


# ------------------------------------------------------------------------------------------------ isolation, retention, memory
def _package_files():
    import src.dataset_bundle as pkg

    return sorted(Path(pkg.__file__).parent.glob("*.py"))


def test_no_module_of_the_package_imports_the_research_harness():
    """Isolation contract (research/danish_aau/tests/evaluation/test_eval_isolation.py): production never imports research."""
    for path in _package_files():
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            roots = {a.name.split(".")[0] for a in n.names} if isinstance(n, ast.Import) else set()
            if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                roots.add(n.module.split(".")[0])
            assert "research" not in roots, path.name


def test_locked_protocol_constant_equals_the_contract_constant():
    from research.danish_aau.contract.telemetry_contract import PROTOCOL_SHA256_V5
    from src.dataset_bundle.loader import LOCKED_PROTOCOL_SHA256

    assert LOCKED_PROTOCOL_SHA256 == PROTOCOL_SHA256_V5


def test_loader_hash_helper_matches_the_mapping_loader_convention():
    from research.danish_aau.mapping.derivations import REGISTRY_PATH
    from research.danish_aau.mapping.loader import MAPPING_PATH as RES_MAPPING
    from research.danish_aau.mapping.loader import mapping_file_sha256
    from src.dataset_bundle import loader

    assert loader.MAPPING_PATH == RES_MAPPING and loader.DERIVATIONS_PATH == REGISTRY_PATH
    assert loader._lf_sha256(loader.MAPPING_PATH) == mapping_file_sha256()


def test_retention_can_only_delete_telemetry_sample_rows_and_never_sees_the_bundle():
    """Retention works on database rows by id; the bundle is a separate file the purge has no path to."""
    retention = (Path(__file__).resolve().parents[1] / "src" / "telemetry" / "retention.py").read_text(encoding="utf-8")
    assert "dataset_bundle" not in retention and "sqlite3" not in retention
    for banned in ("unlink", "rmtree", "os.remove", "shutil"):
        assert banned not in retention, banned
    assert "delete(TelemetrySample)" in retention


def test_peak_memory_is_reported_as_a_number_or_not_measured():
    from src.dataset_bundle.loader import _peak_rss_mb

    v = _peak_rss_mb()
    assert v is None or v > 0
