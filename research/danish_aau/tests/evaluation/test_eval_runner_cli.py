"""Pipeline, manifest, verification and CLI behaviour (synthetic fixtures; no real dataset)."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from research.danish_aau.evaluation import cli, stages  # noqa: F401  (registers 'preflight')
from research.danish_aau.evaluation.config import load_config
from research.danish_aau.evaluation.manifest import MANIFEST_NAME, verify_manifest
from research.danish_aau.evaluation.paths import DANISH_AAU_DIR, REPO_ROOT
from research.danish_aau.evaluation.runner import (
    RunContext,
    register_stage,
    run_pipeline,
    unregister_stage,
)

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


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


def _load(run_dir):
    return json.loads((run_dir / MANIFEST_NAME).read_text(encoding="utf-8"))


def test_clean_run_is_ok_and_writes_stage_report_and_manifest(tmp_path, raw_dir, fixture_registry, fixture_config):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    manifest, code = run_pipeline(ctx, ["preflight"], ["run"], now=NOW)
    assert code == 0 and manifest["run"]["status"] == "ok"
    assert (ctx.run_dir / "stage_preflight.json").is_file() and (ctx.run_dir / MANIFEST_NAME).is_file()
    assert manifest["dataset"]["data_kind"] == "synthetic_fixture"
    assert [i["key"] for i in manifest["inputs"]] == sorted(e.key for e in fixture_registry)


def test_manifest_never_claims_calibration_or_validation(tmp_path, raw_dir, fixture_registry, fixture_config):
    manifest, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config), ["preflight"], [], now=NOW)
    assert manifest["claims"]["calibrated"] is False and manifest["claims"]["validated_against_real_data"] is False
    assert manifest["readiness"]["ready_for_comparisons"] is False


def test_manifest_contains_no_machine_specific_absolute_paths(tmp_path, raw_dir, fixture_registry, fixture_config):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    run_pipeline(ctx, ["preflight"], ["run", "--raw-dir", str(raw_dir)], now=NOW)
    text = (ctx.run_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(tmp_path) not in text and str(raw_dir) not in text
    assert (ctx.run_dir / "stage_preflight.json").read_text(encoding="utf-8").count(str(tmp_path)) == 0


def test_core_hash_is_deterministic_across_runs_and_times(tmp_path, raw_dir, fixture_registry, fixture_config):
    a, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, "a"), ["preflight"], ["x"], now=NOW)
    later = datetime(2027, 1, 1, tzinfo=timezone.utc)
    b, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, "b"), ["preflight"], ["y"], now=later)
    assert a["run"]["created_utc"] != b["run"]["created_utc"]
    assert a["determinism"] == b["determinism"]


def test_core_hash_changes_with_config_and_with_inputs(
    tmp_path, raw_dir, fixture_registry, fixture_config, declared_config
):
    a, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, "a"), ["preflight"], [], now=NOW)
    b, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, declared_config, "b"), ["preflight"], [], now=NOW)
    assert a["determinism"] != b["determinism"]
    victim = raw_dir / fixture_registry[0].filename
    victim.write_bytes(victim.read_bytes() + b"1,2\n")
    c, _ = run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, "c"), ["preflight"], [], now=NOW)
    assert c["determinism"] != a["determinism"]


def test_input_hashes_are_recorded_when_requested(tmp_path, raw_dir, fixture_registry, fixture_config):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    import dataclasses

    ctx.config = dataclasses.replace(ctx.config, integrity=dataclasses.replace(ctx.config.integrity, hash_inputs=True))
    manifest, _ = run_pipeline(ctx, ["preflight"], [], now=NOW)
    assert all(len(i["sha256"]) == 64 for i in manifest["inputs"])


def test_warning_when_files_differ_from_reported_expectations_and_strict_fails_it(
    tmp_path, raw_dir, fixture_registry, fixture_config
):
    from research.danish_aau.evaluation.registry import DEFAULT_REGISTRY

    _, code = run_pipeline(_ctx(tmp_path, raw_dir, DEFAULT_REGISTRY, fixture_config, "w"), ["preflight"], [], now=NOW)
    assert code == 0  # warn: the (tiny synthetic) files do not match the reported real-file expectations
    manifest, code = run_pipeline(
        _ctx(tmp_path, raw_dir, DEFAULT_REGISTRY, fixture_config, "s", strict=True), ["preflight"], [], now=NOW
    )
    assert code == 2 and manifest["run"]["status"] == "failed"


def test_missing_raw_dir_fails_preflight_but_still_writes_a_manifest(tmp_path, fixture_registry, fixture_config):
    ctx = _ctx(tmp_path, tmp_path / "absent", fixture_registry, fixture_config)
    manifest, code = run_pipeline(ctx, ["preflight"], [], now=NOW)
    assert code == 2 and manifest["run"]["status"] == "failed" and (ctx.run_dir / MANIFEST_NAME).is_file()


def test_a_stage_that_writes_into_the_raw_dir_is_caught(tmp_path, raw_dir, fixture_registry, fixture_config):
    class Vandal:
        name = "vandal"

        def run(self, ctx):
            (ctx.raw_dir / "oops.csv").write_text("a\n", encoding="utf-8")
            return {"status": "ok"}

    register_stage(Vandal())
    try:
        manifest, code = run_pipeline(
            _ctx(tmp_path, raw_dir, fixture_registry, fixture_config), ["vandal"], [], now=NOW
        )
    finally:
        unregister_stage("vandal")
    assert code == 2 and manifest["run"]["status"] == "failed_raw_data_modified"


def test_a_crashing_stage_is_recorded_and_stops_the_pipeline(tmp_path, raw_dir, fixture_registry, fixture_config):
    class Boom:
        name = "boom"

        def run(self, ctx):
            raise RuntimeError("kaput")

    register_stage(Boom())
    try:
        manifest, code = run_pipeline(
            _ctx(tmp_path, raw_dir, fixture_registry, fixture_config), ["boom", "preflight"], [], now=NOW
        )
    finally:
        unregister_stage("boom")
    assert code == 2 and [s["name"] for s in manifest["stages"]] == ["boom"]
    assert "kaput" in json.loads((tmp_path / "out" / "r1" / "stage_boom.json").read_text(encoding="utf-8"))["error"]


def test_unknown_stage_and_bad_run_id_and_reused_run_dir_are_refused(
    tmp_path, raw_dir, fixture_registry, fixture_config
):
    with pytest.raises(KeyError):
        run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config), ["nope"], [], now=NOW)
    with pytest.raises(ValueError):
        run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, "../evil"), ["preflight"], [], now=NOW)
    run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, "same"), ["preflight"], [], now=NOW)
    with pytest.raises(FileExistsError):
        run_pipeline(_ctx(tmp_path, raw_dir, fixture_registry, fixture_config, "same"), ["preflight"], [], now=NOW)


# ----------------------------------------------------------------------------------------------- verify
def test_verify_passes_on_a_fresh_manifest_and_detects_tampering(tmp_path, raw_dir, fixture_registry, fixture_config):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    run_pipeline(ctx, ["preflight"], [], now=NOW)
    path = ctx.run_dir / MANIFEST_NAME
    assert {r["status"] for r in verify_manifest(path, raw_dir)} == {"pass"}

    original = path.read_text(encoding="utf-8")
    tampered = json.loads(original)
    tampered["claims"]["calibrated"] = True
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert any(r["check"] == "claims_not_overstated" and r["status"] == "fail" for r in verify_manifest(path, raw_dir))

    tampered = json.loads(original)
    tampered["inputs"][0]["size_bytes"] += 1
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert any(r["check"] == "core_hash" and r["status"] == "fail" for r in verify_manifest(path, raw_dir))

    tampered = json.loads(original)
    tampered["config"]["run"]["seed"] = 99
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert any(r["check"] == "config_hash" and r["status"] == "fail" for r in verify_manifest(path, raw_dir))


def test_verify_detects_raw_input_changes_and_skips_without_the_dataset(
    tmp_path, raw_dir, fixture_registry, fixture_config
):
    ctx = _ctx(tmp_path, raw_dir, fixture_registry, fixture_config)
    run_pipeline(ctx, ["preflight"], [], now=NOW)
    path = ctx.run_dir / MANIFEST_NAME
    assert next(r for r in verify_manifest(path, None) if r["check"] == "inputs_unchanged")["status"] == "skipped"
    victim = raw_dir / fixture_registry[0].filename
    victim.write_bytes(victim.read_bytes() + b"x")
    assert next(r for r in verify_manifest(path, raw_dir) if r["check"] == "inputs_unchanged")["status"] == "fail"


def test_verify_of_unreadable_manifest_fails(tmp_path):
    assert verify_manifest(tmp_path / "missing.json")[0]["status"] == "fail"


# ----------------------------------------------------------------------------------------------- CLI
def test_cli_run_and_verify_roundtrip(tmp_path, raw_dir, fixture_registry, fixture_config, capsys):
    out = tmp_path / "cli_out"
    code = cli.main(["run", "--config", str(fixture_config), "--out-dir", str(out), "--run-id", "t1"])
    text = capsys.readouterr().out
    assert code == 0 and "manifest core sha256" in text and "not calibrated, not validated" in text
    assert text.isascii()
    assert cli.main(["verify", str(out / "t1"), "--config", str(fixture_config)]) == 0


def test_cli_require_ready_returns_3_until_declarations_are_made(
    tmp_path, raw_dir, fixture_registry, fixture_config, declared_config, capsys
):
    base = ["run", "--out-dir", str(tmp_path / "o"), "--require-ready"]
    assert cli.main([*base, "--config", str(fixture_config), "--run-id", "u"]) == 3
    assert cli.main([*base, "--config", str(declared_config), "--run-id", "d"]) == 0


def test_cli_missing_dataset_exits_2(tmp_path, fixture_config, capsys):
    code = cli.main(
        [
            "run",
            "--config",
            str(fixture_config),
            "--raw-dir",
            str(tmp_path / "absent"),
            "--out-dir",
            str(tmp_path / "o"),
        ]
    )
    assert code == 2
    assert "does not exist" in capsys.readouterr().out


def test_cli_refuses_an_unsafe_output_dir_and_creates_nothing(tmp_path, fixture_config, capsys):
    target = REPO_ROOT / "src" / "_aau_eval_must_not_exist"
    code = cli.main(["run", "--config", str(fixture_config), "--out-dir", str(target), "--run-id", "x"])
    assert code == 2 and not target.exists()


def test_cli_bad_config_lists_every_problem(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text('[policies]\nduplicate_timestamps = "mean"\n[run]\nsede = 1\n', encoding="utf-8")
    assert cli.main(["show-config", "--config", str(bad)]) == 2
    out = capsys.readouterr().out
    assert "mean" in out and "run.sede" in out


def test_cli_show_config_and_inventory_json(raw_dir, fixture_registry, fixture_config, capsys):
    assert cli.main(["show-config", "--config", str(fixture_config)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["config_sha256"] and shown["readiness"]["ready_for_comparisons"] is False
    assert cli.main(["inventory", "--config", str(fixture_config), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["raw_dir_exists"] is True


def test_cli_inventory_strict_fails_on_mismatch_and_missing_dir(fixture_registry, fixture_config, tmp_path, capsys):
    assert (
        cli.main(["inventory", "--config", str(fixture_config), "--strict"]) == 2
    )  # tiny fixture vs real expectations
    assert cli.main(["inventory", "--config", str(fixture_config), "--raw-dir", str(tmp_path / "absent")]) == 2


def test_cli_doctor_output_is_ascii_and_reports_missing_dataset(fixture_config, tmp_path, capsys):
    code = cli.main(["doctor", "--config", str(fixture_config)])
    out = capsys.readouterr().out
    assert code == 0 and out.isascii() and "PASS  config valid" in out
    code = cli.main(
        ["doctor", "--config", str(fixture_config), "--raw-dir", str(tmp_path / "absent"), "--require-dataset"]
    )
    assert code == 2 and "FAIL" in capsys.readouterr().out


def test_wrapper_script_works_from_any_working_directory(tmp_path, raw_dir, fixture_registry, fixture_config):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [
            sys.executable,
            str(DANISH_AAU_DIR / "run_evaluation.py"),
            "inventory",
            "--config",
            str(fixture_config),
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert (
        report["summary"]["n_registered"] == 4 and report["summary"]["n_mismatch"] == 4
    )  # fixture vs real expectations


def test_python_dash_m_entry_point(tmp_path, raw_dir, fixture_registry, fixture_config):
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.run(
        [sys.executable, "-m", "research.danish_aau.evaluation", "show-config", "--config", str(fixture_config)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
