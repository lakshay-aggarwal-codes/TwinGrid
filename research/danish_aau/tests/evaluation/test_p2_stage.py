"""Phase 2: the ``prepare`` stage through the real runner, manifest/verify integration and raw-data protection."""

import ast
import builtins
import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import p2_fixtures as p2
import pytest
import synthetic_fixtures as fx

from research.danish_aau.evaluation import cli, stages  # noqa: F401  (registers 'preflight' and 'prepare')
from research.danish_aau.evaluation.config import load_config
from research.danish_aau.evaluation.data_layer import reader as reader_module
from research.danish_aau.evaluation.data_layer import validation
from research.danish_aau.evaluation.data_layer.validation import EXPECTED_AUDIT, cross_check, summarize_checks
from research.danish_aau.evaluation.manifest import MANIFEST_NAME, verify_manifest
from research.danish_aau.evaluation.paths import DANISH_AAU_DIR, REPO_ROOT
from research.danish_aau.evaluation.registry import DEFAULT_REGISTRY
from research.danish_aau.evaluation.runner import RunContext, available_stages, run_pipeline

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def _ctx(tmp_path, raw_dir, registry, config_path, run_id="r1", **kw):
    return RunContext(
        config=load_config(config_path),
        config_path="fixture.toml",
        repo_root=REPO_ROOT,
        raw_dir=raw_dir,
        raw_dir_source="cli",
        run_dir=tmp_path / "out" / run_id,
        run_id=run_id,
        registry=registry,
        **kw,
    )


def _report(ctx):
    return json.loads((ctx.run_dir / "stage_prepare.json").read_text(encoding="utf-8"))


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ happy path
def test_prepare_is_a_registered_stage():
    assert {"preflight", "prepare"} <= set(available_stages())


def test_prepare_runs_on_the_synthetic_dataset(tmp_path, raw_dir, fixture_registry, fixture_config):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    manifest, code = run_pipeline(ctx, ["prepare"], ["run"], now=NOW)
    rep = _report(ctx)
    assert code == 0 and rep["status"] == "ok" and manifest["run"]["status"] == "ok"
    assert set(rep["files"]) == {e.key for e in fixture_registry}
    for key, entry in rep["files"].items():
        assert (
            entry["status"] == "ok"
            and entry["time_index"]["n_rows"] == 6
            and entry["time_index"]["timestamp_state"] == "naive_unspecified"
        )
        assert (
            entry["stream_check"]["rows_streamed"] == 6
            and entry["stream_check"]["src_rows_contiguous_in_source_order"] is True
        )
        assert entry["cross_check"]["status"] == "not_checked" and (ctx.run_dir / f"time_index_{key}.csv").is_file()
        assert (ctx.run_dir / f"provenance_{key}.json").is_file()
    assert rep["layers"].keys() == {"L0", "L1", "L2", "L3"}
    assert rep["policies"]["duplicates"] == "keep_all_ordered" and rep["policies"]["interpolation"] == "none"
    assert rep["policies"]["approved_sensitivity"] == [] and rep["policies"]["approved_bucket_reducers"] == []
    assert (
        rep["timestamp_state"]["state"] == "naive_unspecified" and rep["timestamp_state"]["timezone_applied"] is False
    )


def test_the_phase1_undeclared_timezone_is_never_applied_even_when_declared(
    tmp_path, raw_dir, fixture_registry, declared_config
):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, declared_config)
    run_pipeline(ctx, ["prepare"], [], now=NOW)
    ts = _report(ctx)["timestamp_state"]
    assert (
        ts["phase1_declared_timezone"] == "Europe/Copenhagen"
        and ts["timezone_applied"] is False
        and ts["state"] == "naive_unspecified"
    )
    assert "no UTC conversion" in ts["note"]
    assert _report(ctx)["policies"]["note"] == "phase1 and data config agree"


def test_report_and_sidecars_contain_no_machine_specific_paths(tmp_path, raw_dir, fixture_registry, fixture_config):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    run_pipeline(ctx, ["prepare"], [], now=NOW)
    for f in ctx.run_dir.iterdir():
        text = f.read_text(encoding="utf-8")
        assert str(tmp_path) not in text and str(raw_dir) not in text and str(REPO_ROOT) not in text, f.name


def test_prepare_is_deterministic(tmp_path, raw_dir, fixture_registry, fixture_config):
    a, b = (_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, rid) for rid in ("a", "b"))
    ma, _ = run_pipeline(a, ["prepare"], ["x"], now=NOW)
    mb, _ = run_pipeline(b, ["prepare"], ["y"], now=NOW)
    assert ma["determinism"] == mb["determinism"]
    assert ma["stages"][0]["report_sha256"] == mb["stages"][0]["report_sha256"]
    for f in a.run_dir.iterdir():
        if f.name != MANIFEST_NAME:
            assert f.read_bytes() == (b.run_dir / f.name).read_bytes(), f.name


def test_duplicates_and_empty_rows_produce_sidecars(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    p2.write_source(raw, p2.MAIN_KEY, p2.MAIN_HEADER, p2.DUP_ROWS)
    p2.write_source(
        raw,
        p2.VENT_KEY,
        p2.VENT_HEADER,
        [["2024-09-16 16:45:00", *([""] * 6)], ["2024-09-16 16:47:00", "0.0", *([""] * 5)]],
    )
    cfg = fx.write_config(tmp_path / "c.toml", raw)
    ctx = _ctx(tmp_path, raw, DEFAULT_REGISTRY, cfg)
    manifest, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    rep = _report(ctx)
    assert (
        code == 0
        and rep["status"] == "warn"
        and set(rep["missing_files"]) == {"air_speed_25", "surrounding_temperatures"}
    )
    main = rep["files"][p2.MAIN_KEY]
    assert main["time_index"]["n_duplicate_groups"] == 2 and main["time_index"]["n_conflicting_duplicate_groups"] == 1
    assert main["l2_view"]["n_rows_in_view"] == 11 and main["l2_view"]["n_excluded"] == 0  # keep_all_ordered
    assert (ctx.run_dir / f"duplicate_groups_{p2.MAIN_KEY}.csv").read_text(encoding="utf-8").count(
        "\n"
    ) == 5  # header + 4 duplicate rows
    vent = rep["files"][p2.VENT_KEY]
    assert vent["time_index"]["completeness_counts"] == {"FULL": 0, "PARTIAL": 1, "EMPTY": 1}
    assert vent["l2_view"]["n_rows_in_view"] == 1  # the damper-only row survives, the EMPTY row is excluded
    ledger = (
        (ctx.run_dir / f"exclusion_ledger_{p2.VENT_KEY}_exclude_empty_rows.csv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(ledger) == 2 and ledger[1].startswith(f"{p2.VENT_KEY},1,empty_observation")
    assert "problems" in rep and manifest["run"]["status"] == "warn"


# ------------------------------------------------------------------------------------------------ failures
def test_missing_raw_directory_fails(tmp_path, fixture_registry, fixture_config):
    manifest, code = run_pipeline(
        _ctx(tmp_path, tmp_path / "absent", fixture_registry, fixture_config), ["prepare"], [], now=NOW
    )
    assert code == 2 and manifest["run"]["status"] == "failed"


def test_conflicting_duplicate_policy_between_phase1_and_data_config_fails(tmp_path, raw_dir, fixture_registry):
    cfg = tmp_path / "p1.toml"
    cfg.write_text(
        f"schema_version = 1\n[dataset]\nraw_dir = '{raw_dir.as_posix()}'\nis_synthetic_fixture = true\n[policies]\nduplicate_timestamps = 'exclude_ambiguous'\n",
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, cfg)
    _, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    assert code == 2 and "conflicting duplicate policy" in " ".join(_report(ctx)["problems"])


def test_an_invalid_data_config_is_reported_with_every_problem(tmp_path, raw_dir, fixture_registry, fixture_config):
    bad = tmp_path / "bad_data.toml"
    bad.write_text(
        '[policies]\nduplicates = "mean"\n[reader]\nchunksize = 0\n[timestamps]\nstate = "UTC"\n', encoding="utf-8"
    )
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config, data_config_path=str(bad))
    _, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    problems = _report(ctx)["problems"]
    assert code == 2 and len(problems) >= 3 and any("DIFFERENT" in p for p in problems)


def test_a_custom_data_config_is_used_and_hashed(tmp_path, raw_dir, fixture_registry, fixture_config):
    custom = tmp_path / "custom.toml"
    custom.write_text(
        '[reader]\nchunksize = 4\n[files.ventilation]\nmeasurement_columns = ["Room_damper_opening"]\n',
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config, data_config_path=str(custom))
    run_pipeline(ctx, ["prepare"], [], now=NOW)
    rep = _report(ctx)
    assert (
        rep["files"]["ventilation"]["stream_check"]["chunks"] == 2
        and rep["files"]["ventilation"]["n_measurement_columns"] == 1
    )
    assert rep["data_config_sha256"] != hashlib.sha256(b"").hexdigest() and rep["data_config"] == "custom.toml"


def test_a_non_numeric_value_fails_the_stream_check_with_a_typed_error(
    tmp_path, raw_dir, fixture_registry, fixture_config
):
    victim = raw_dir / fixture_registry[1].filename
    victim.write_text(victim.read_text(encoding="utf-8").replace("20.", "x.", 1), encoding="utf-8")
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    _, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    entry = _report(ctx)["files"][fixture_registry[1].key]
    assert (
        code == 2
        and entry["stream_check"]["status"] == "failed"
        and "NumericParseError" in entry["stream_check"]["error"]
    )


def test_a_malformed_file_fails_that_file_without_crashing_the_run(tmp_path, raw_dir, fixture_registry, fixture_config):
    victim = raw_dir / fixture_registry[2].filename
    victim.write_text(victim.read_text(encoding="utf-8") + "2024-09-17 10:00:00,1,2,3,4,5,6,7,8,9\n", encoding="utf-8")
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    _, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    rep = _report(ctx)
    assert (
        code == 2
        and rep["files"][fixture_registry[2].key]["status"] == "failed"
        and rep["files"][fixture_registry[0].key]["status"] == "ok"
    )


# ------------------------------------------------------------------------------------------------ cross-check
def test_real_dataset_expectations_differ_from_the_synthetic_fixture_and_are_reported_not_hidden(
    tmp_path, raw_dir, fixture_registry
):
    cfg = tmp_path / "nonfixture.toml"
    cfg.write_text(f"schema_version = 1\n[dataset]\nraw_dir = '{raw_dir.as_posix()}'\n", encoding="utf-8")
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, cfg)
    manifest, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    rep = _report(ctx)
    assert code == 0 and rep["status"] == "warn" and manifest["dataset"]["data_kind"] == "reported_real_dataset"
    cc = rep["files"][p2.MAIN_KEY]["cross_check"]
    assert cc["expectation_source"] == validation.EXPECTATION_SOURCE and cc["summary"]["mismatch"] > 0
    assert any(c["name"] == "n_rows" and c["expected"] == 90_902 and c["actual"] == 6 for c in cc["checks"])


def test_the_cross_check_mechanism_reports_matches_when_values_agree(tmp_path, monkeypatch):
    reader = p2.build_reader(
        tmp_path, p2.VENT_KEY, p2.VENT_HEADER, __import__("test_p2_policies_completeness").VENT_ROWS
    )[0]
    mini = {
        "n_rows": 9,
        "first_row_text": "2024-09-16 16:45:00",
        "last_row_text": "2024-09-17 10:45:00",
        "n_timestamp_parse_errors": 0,
        "n_timestamp_tz_suffix_rejected": 0,
        "n_ordering_violations": 0,
        "delta_seconds_counts": {"120.0": 3, "780.0": 1, "900.0": 3, "60960.0": 1},
        "n_duplicate_groups": 0,
        "completeness_counts": {"FULL": 3, "PARTIAL": 2, "EMPTY": 4},
        "population_patterns": [
            {"populated_columns": [], "n_rows": 4},
            {"populated_columns": ["Room_damper_opening"], "n_rows": 1},
            {"populated_columns": sorted(p2.VENT_COLUMNS), "n_rows": 3},
            {"populated_columns": ["AHU_temperature_supply"], "n_rows": 1},
        ],
        "in_window_rows": 4,
    }
    monkeypatch.setitem(EXPECTED_AUDIT, p2.VENT_KEY, mini)
    window = reader.window_ns(("2024-09-17 09:40:00", "2024-09-17 10:20:00"))
    checks = cross_check(reader.index, window)
    assert summarize_checks(checks) == {"match": len(mini), "mismatch": 0, "not_checked": 0}
    monkeypatch.setitem(EXPECTED_AUDIT, p2.VENT_KEY, {**mini, "n_rows": 10})
    assert summarize_checks(cross_check(reader.index, window))["mismatch"] == 1
    assert {c["status"] for c in cross_check(reader.index, None) if c["name"].startswith("in_window")} == {
        "not_checked"
    }
    assert (
        cross_check(reader.index, window)
        and cross_check(type(reader.index)(**{**reader.index.__dict__, "file_key": "unknown"}), None) == []
    )


def test_recorded_expectations_are_internally_consistent_with_the_registry():
    by_key = {e.key: e for e in DEFAULT_REGISTRY}
    assert set(EXPECTED_AUDIT) == set(by_key)
    for key, exp in EXPECTED_AUDIT.items():
        reg = by_key[key]
        assert exp["n_rows"] == reg.expected_rows
        assert (
            exp["first_row_text"] == reg.expected_first_timestamp
            and exp["last_row_text"] == reg.expected_last_timestamp
        )
        assert sum(exp["delta_seconds_counts"].values()) == exp["n_rows"] - 1  # one interval per consecutive pair
    main = EXPECTED_AUDIT["temperature_power_25"]
    assert (
        main["n_duplicate_groups"] == 46
        and main["n_duplicate_rows"] == 92
        and main["delta_seconds_counts"]["0.0"] == 46
    )
    vent = EXPECTED_AUDIT["ventilation"]
    # Corrected expectations (locally verified): three disjoint patterns; no FULL row, no EMPTY row.
    assert vent["completeness_counts"] == {"FULL": 0, "PARTIAL": 4_576, "EMPTY": 0}
    assert not {"partial_row_texts", "in_window_full_rows", "in_window_rows"} & set(
        vent
    )  # the old interpretations are gone
    patterns = vent["population_patterns"]
    assert sum(p["n_rows"] for p in patterns) == vent["n_rows"] == 4_576
    assert sorted(p["n_rows"] for p in patterns) == [1_525, 1_525, 1_526]
    assert {frozenset(p["populated_columns"]) for p in patterns} == {
        frozenset({"Room_damper_opening"}),
        frozenset({"AHU_fan_speed_supply", "AHU_fan_speed_extraction", "AHU_temperature_supply"}),
        frozenset({"AHU_pressure_supply_duct", "AHU_pressure_extraction_duct"}),
    }
    # The per-column missing counts are preserved and agree with the patterns: missing = rows whose pattern lacks the column.
    assert vent["missing_by_column"]["Room_damper_opening"] == 3_050
    for column, missing in vent["missing_by_column"].items():
        populated = sum(p["n_rows"] for p in patterns if column in p["populated_columns"])
        assert missing == vent["n_rows"] - populated, column
    assert EXPECTED_AUDIT["surrounding_temperatures"]["in_window_rows"] == 101


# ------------------------------------------------------------------------------------------------ manifest / verify
def test_stage_report_hashes_are_in_the_manifest_and_verify_detects_tampering(
    tmp_path, raw_dir, fixture_registry, fixture_config
):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    manifest, _ = run_pipeline(ctx, ["preflight", "prepare"], [], now=NOW)
    assert [s["name"] for s in manifest["stages"]] == ["preflight", "prepare"] and all(
        len(s["report_sha256"]) == 64 for s in manifest["stages"]
    )
    path = ctx.run_dir / MANIFEST_NAME
    results = verify_manifest(path, raw_dir)
    assert {r["status"] for r in results} == {"pass"} and "stage_reports_unchanged" in {r["check"] for r in results}
    report_file = ctx.run_dir / "stage_prepare.json"
    report_file.write_text(
        report_file.read_text(encoding="utf-8").replace("keep_all_ordered", "exclude_ambiguous"), encoding="utf-8"
    )
    bad = next(r for r in verify_manifest(path, raw_dir) if r["check"] == "stage_reports_unchanged")
    assert bad["status"] == "fail" and "stage_prepare.json" in bad["detail"]


def test_manifest_phase_and_version_reflect_phase_2(tmp_path, raw_dir, fixture_registry, fixture_config):
    manifest, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config), ["prepare"], [], now=NOW)
    assert manifest["phase"] == 2 and manifest["harness_version"].endswith("phase2")
    assert manifest["claims"]["calibrated"] is False and manifest["claims"]["validated_against_real_data"] is False


def test_the_data_layer_sources_are_part_of_the_source_fingerprint(tmp_path, raw_dir, fixture_registry, fixture_config):
    manifest, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config), ["prepare"], [], now=NOW)
    paths = {f["path"] for f in manifest["source_files"]}
    assert {
        "research/danish_aau/config/data.toml",
        "research/danish_aau/evaluation/data_layer/reader.py",
        "research/danish_aau/evaluation/data_layer/alignment.py",
        "research/danish_aau/evaluation/stages/prepare.py",
    } <= paths


# ------------------------------------------------------------------------------------------------ CLI
def test_cli_runs_both_stages_and_prints_ascii(tmp_path, raw_dir, fixture_registry, fixture_config, capsys):
    out = tmp_path / "cli"
    code = cli.main(
        [
            "run",
            "--config",
            str(fixture_config),
            "--stage",
            "preflight",
            "--stage",
            "prepare",
            "--out-dir",
            str(out),
            "--run-id",
            "c1",
        ]
    )
    text = capsys.readouterr().out
    assert code in (0,) and "stage prepare: ok" in text and text.isascii()
    assert (out / "c1" / "stage_prepare.json").is_file()
    assert cli.main(["verify", str(out / "c1"), "--config", str(fixture_config)]) == 0


def test_cli_custom_data_config_and_failure_exit_code(tmp_path, raw_dir, fixture_registry, fixture_config, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text('[policies]\nduplicates = "keep_first"\n', encoding="utf-8")
    code = cli.main(
        [
            "run",
            "--config",
            str(fixture_config),
            "--stage",
            "prepare",
            "--data-config",
            str(bad),
            "--out-dir",
            str(tmp_path / "o"),
            "--run-id",
            "x",
        ]
    )
    assert code == 2 and "[prepare]" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ raw-data protection
@pytest.fixture
def raw_io_spy(monkeypatch):
    """Record every open() of a file under the raw directory; FAIL the test on any write-capable open or write-style call."""
    seen = []

    def make(real, raw):
        def wrapper(file, mode="r", *a, **kw):
            try:
                inside = Path(os.fspath(file)).resolve().is_relative_to(raw)
            except (TypeError, ValueError, OSError):
                inside = False
            if inside:
                seen.append((Path(os.fspath(file)).name, mode))
                assert not any(
                    c in str(mode) for c in "wax+"
                ), f"write-capable open of a raw file: {file!r} mode={mode!r}"
            return real(file, mode, *a, **kw)

        return wrapper

    def install(raw):
        raw = Path(raw).resolve()
        monkeypatch.setattr(builtins, "open", make(builtins.open, raw))
        monkeypatch.setattr(io, "open", make(io.open, raw))
        real_os_open = os.open

        def os_open(path, flags, *a, **kw):
            try:
                inside = Path(os.fspath(path)).resolve().is_relative_to(raw)
            except (TypeError, ValueError, OSError):
                inside = False
            assert not (
                inside and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
            ), f"write-capable os.open under raw: {path!r}"
            return real_os_open(path, flags, *a, **kw)

        monkeypatch.setattr(os, "open", os_open)
        return seen

    return install


def test_the_full_prepare_run_never_opens_a_raw_file_for_writing_and_leaves_it_unchanged(
    tmp_path, raw_dir, fixture_registry, fixture_config, raw_io_spy
):
    before = _tree_hash(raw_dir)
    seen = raw_io_spy(raw_dir)
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    manifest, code = run_pipeline(ctx, ["preflight", "prepare"], [], now=NOW)
    assert code == 0 and manifest["run"]["status"] == "ok"
    assert seen and all(
        mode == "rb" or mode == "r" or mode.startswith("r") for _, mode in seen
    )  # the spy did observe raw reads
    assert {name for name, _ in seen} == {e.filename for e in fixture_registry}
    assert _tree_hash(raw_dir) == before


def test_the_spy_itself_would_catch_a_write(tmp_path, raw_dir, fixture_registry, raw_io_spy):
    raw_io_spy(raw_dir)
    with pytest.raises(AssertionError):
        (raw_dir / "x.csv").write_text("a", encoding="utf-8")
    with pytest.raises(AssertionError):
        open(raw_dir / fixture_registry[0].filename, "ab")  # noqa: SIM115


def test_an_output_directory_inside_the_raw_dataset_is_refused_and_not_created(
    tmp_path, raw_dir, fixture_registry, fixture_config, capsys
):
    target = raw_dir / "derived"
    code = cli.main(
        ["run", "--config", str(fixture_config), "--stage", "prepare", "--out-dir", str(target), "--run-id", "x"]
    )
    assert code == 2 and not target.exists() and "inside the raw dataset directory" in capsys.readouterr().out


def test_unregistered_files_are_never_loaded(tmp_path, raw_dir, fixture_registry, fixture_config, monkeypatch):
    (raw_dir / "AAU_temperature_and_power_use_50_percent_load_period.csv").write_text(
        "not,a,valid\nfile at all\n\x00\x01", encoding="utf-8"
    )
    created = []
    real_init = reader_module.AauCsvReader.__init__

    def spy(self, source, *a, **kw):
        created.append(source.filename)
        real_init(self, source, *a, **kw)

    monkeypatch.setattr(reader_module.AauCsvReader, "__init__", spy)
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    _, code = run_pipeline(ctx, ["prepare"], [], now=NOW)
    assert code == 0 and sorted(created) == sorted(e.filename for e in fixture_registry)
    assert "50_percent" not in (ctx.run_dir / "stage_prepare.json").read_text(encoding="utf-8")


def _write_capable_open_modes(call):
    """Mode-like string constants ('w', 'ab', 'r+', ...) among the arguments of an open() call that can write."""
    consts = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    consts += [
        k.value.value for k in call.keywords if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)
    ]
    return [c for c in consts if c and set(c) <= set("rwabxt+") and set(c) & set("wax+")]


def test_only_the_provenance_and_prepare_modules_write_files():
    forbidden = {
        "write_text",
        "write_bytes",
        "to_csv",
        "to_json",
        "to_parquet",
        "unlink",
        "rmdir",
        "touch",
        "mkdir",
        "rename",
        "writelines",
        "write",
    }
    allowed = {"provenance.py", "prepare.py"}
    offenders = {}
    for path in (DANISH_AAU_DIR / "evaluation" / "data_layer").glob("*.py"):
        if path.name in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        names = {c.func.attr for c in calls if isinstance(c.func, ast.Attribute)} | {
            c.func.id for c in calls if isinstance(c.func, ast.Name)
        }
        bad = sorted(names & forbidden)
        for c in calls:
            if (isinstance(c.func, ast.Name) and c.func.id == "open") or (
                isinstance(c.func, ast.Attribute) and c.func.attr == "open"
            ):
                bad += [f"open(mode={m!r})" for m in _write_capable_open_modes(c)]
        if bad:
            offenders[path.name] = bad
    assert (
        offenders == {}
    )  # read-only opens (the TOML config, raw CSVs via open_raw_bytes) are fine; write-capable ones are not


def test_the_write_audit_would_catch_a_write_capable_open():
    tree = ast.parse("open(p, 'wb')\nPath(p).open(mode='a')\nopen(p, 'rb')\nf.open('rb')\nopen(p, encoding='ascii')")
    flagged = [
        bool(_write_capable_open_modes(c))
        for c in ast.walk(tree)
        if isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", "")) == "open"
    ]
    assert sorted(flagged) == [False, False, False, True, True]


def test_prepare_does_not_import_src_or_touch_logging(tmp_path, raw_dir, fixture_registry, fixture_config):
    code = (
        "import json, logging, sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "before = list(logging.getLogger().handlers)\n"
        "from research.danish_aau.evaluation import cli\n"
        f"rc = cli.main(['run', '--config', {str(fixture_config)!r}, '--stage', 'prepare', '--out-dir', {str(tmp_path / 'sub')!r}, '--run-id', 's'])\n"
        "print(json.dumps({'rc': rc, 'src': [m for m in sys.modules if m == 'src' or m.startswith('src.')], 'handlers_changed': before != list(logging.getLogger().handlers)}))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, timeout=300)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"rc": 0, "src": [], "handlers_changed": False}
    assert not (tmp_path / "logs").exists()
