"""T24: reproducibility run framework (contract section 11).

Covers: canonical JSON, explicit RNG streams, the run directory and manifest, byte-identical
results.json for identical config/seed (level L1), ``verify`` failing by field name when any input
or generated file changes, report generation from results.json only, dirty-tree promotion rules,
failure/determinism handling and the toy round trip. Nothing here needs TensorFlow, SB3 or a database.
"""

import ast
import contextlib
import importlib.util
import inspect
import io
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src import versions
from src.repro import canonical, env, experiments, report, rng, toy
from src.repro.promotion import NotPromotable, promotion_eligibility, require_promotable
from src.repro.run import REQUIRED_MANIFEST_FIELDS, RunError, RunRequest, execute_experiment, read_json, run
from src.repro.verify import verify_run

ROOT = Path(__file__).resolve().parent.parent
SHA = "c" * 40
CONFIG = "src/repro/toy_config.json"
ARTIFACT_FILE = "models/toyart/model.keras"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A scratch project root with a config, lock file, dataset manifest, pre-registration and a registered artifact."""
    monkeypatch.setenv("GIT_SHA", SHA)
    monkeypatch.delenv("GIT_DIRTY", raising=False)
    (tmp_path / "src/repro").mkdir(parents=True)
    shutil.copy(ROOT / CONFIG, tmp_path / CONFIG)
    (tmp_path / "requirements.lock").write_text("numpy==2.4.4\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/MANIFEST.json").write_text('{"files": {"a.csv": "00"}}\n', encoding="utf-8")
    (tmp_path / "prereg.json").write_text('{"alpha": 0.5}\n', encoding="utf-8")
    (tmp_path / "models/toyart").mkdir(parents=True)
    (tmp_path / ARTIFACT_FILE).write_bytes(b"model-bytes" * 20)
    registry = {
        "registry_version": 2,
        "artifacts": [
            {
                "model_id": "toyart-1",
                "status": "candidate",
                "files": {
                    ARTIFACT_FILE: {
                        "sha256": canonical.sha256_raw_file(tmp_path / ARTIFACT_FILE),
                        "size": 220,
                        "format": "keras",
                    }
                },
            }
        ],
    }
    (tmp_path / "models/registry.json").write_text(json.dumps(registry), encoding="utf-8")
    return tmp_path


def make_run(root, run_id="r1", **kw):
    request = RunRequest(experiment="toy", config_paths=[CONFIG], run_id=run_id, **kw)
    return run(request, root)


def full_run(root, run_id="r1", **kw):
    outcome = make_run(
        root, run_id, dataset_manifest="data/MANIFEST.json", prereg="prereg.json", artifacts=["toyart-1"], **kw
    )
    assert outcome.state == "completed", outcome.error
    return outcome


def names(rep):
    return [f.field for f in rep.failures]


def flip(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    path.write_bytes(bytes(data))


# ----------------------------------------------------------------------------- canonical JSON and hashing


def test_canonical_json_is_sorted_fixed_format_and_ends_with_a_newline():
    text = canonical.canonical_dumps({"b": 1, "a": [1.5, 2, True, None, "x"], "c": {"z": 0, "y": 1}})
    assert (
        text
        == '{\n  "a": [\n    1.5,\n    2,\n    true,\n    null,\n    "x"\n  ],\n  "b": 1,\n  "c": {\n    "y": 1,\n    "z": 0\n  }\n}\n'
    )
    assert canonical.canonical_dumps({"b": 1, "a": 2}) == canonical.canonical_dumps({"a": 2, "b": 1})


def test_canonical_json_normalises_numpy_tuples_and_negative_zero_and_refuses_nan():
    obj = {"a": np.float64(0.25), "b": np.arange(3), "c": (1, 2), "d": -0.0, "e": np.int64(7)}
    assert json.loads(canonical.canonical_dumps(obj)) == {"a": 0.25, "b": [0, 1, 2], "c": [1, 2], "d": 0.0, "e": 7}
    assert "-0.0" not in canonical.canonical_dumps(obj)
    for bad in (float("nan"), float("inf"), {1: 2}, object(), {"a": {"b": float("-inf")}}):
        with pytest.raises(canonical.CanonicalError):
            canonical.canonical_dumps(bad)


def test_round_sig_makes_last_bit_noise_disappear():
    a, b = 0.1 + 0.2, 0.3
    assert a != b and canonical.round_sig([a]) == canonical.round_sig([b])
    assert canonical.round_sig({"x": 1.23456789012345678}, 6) == {"x": 1.23457}
    with pytest.raises(ValueError):
        canonical.round_sig(1.0, 0)


def test_input_hash_ignores_line_endings_and_utf16_but_not_content(tmp_path):
    lf, crlf, u16, other = tmp_path / "a.txt", tmp_path / "b.txt", tmp_path / "c.txt", tmp_path / "d.txt"
    lf.write_bytes(b"x==1\ny==2\n")
    crlf.write_bytes(b"x==1\r\ny==2\r\n")
    u16.write_bytes("x==1\r\ny==2\r\n".encode("utf-16"))
    other.write_bytes(b"x==1\ny==3\n")
    assert canonical.sha256_input_file(lf) == canonical.sha256_input_file(crlf) == canonical.sha256_input_file(u16)
    assert canonical.sha256_input_file(lf) != canonical.sha256_input_file(other)
    binary = tmp_path / "w.keras"
    binary.write_bytes(b"a\r\nb")
    assert canonical.sha256_input_file(binary) == canonical.sha256_raw_file(binary)  # binary: byte for byte


# ----------------------------------------------------------------------------- RNG


def test_streams_are_reproducible_independent_and_order_free():
    a = rng.make_rng(7, "scenario", 3).random(5)
    assert np.array_equal(a, rng.make_rng(7, "scenario", 3).random(5))
    assert not np.array_equal(a, rng.make_rng(7, "scenario", 4).random(5))
    assert not np.array_equal(a, rng.make_rng(8, "scenario", 3).random(5))
    assert not np.array_equal(a, rng.make_rng(7, "noise", 3).random(5))
    first = rng.make_rng(1, "x")
    _ = rng.make_rng(1, "y").random(100)  # drawing from another stream first changes nothing
    assert np.array_equal(first.random(3), rng.make_rng(1, "x").random(3))
    assert isinstance(rng.make_rng(1), np.random.Generator)


@pytest.mark.parametrize("seed", [-1, 1.5, "3", True, None])
def test_bad_seeds_are_refused(seed):
    with pytest.raises(ValueError):
        rng.make_rng(seed)


def test_global_generator_use_is_detected_but_explicit_generators_are_fine():
    with rng.forbid_global_rng():
        rng.make_rng(1, "a").random(10)
    with pytest.raises(rng.GlobalRngTouched):
        with rng.forbid_global_rng():
            np.random.random()
    with pytest.raises(rng.GlobalRngTouched):
        with rng.forbid_global_rng():
            import random

            random.random()


# ----------------------------------------------------------------------------- run directory and manifest


def test_run_directory_layout_manifest_fields_and_status(world):
    outcome = full_run(world, "layout")
    d = outcome.run_dir
    assert d == world / "reports/runs/layout"
    for rel in (
        "manifest.json",
        "status.json",
        "results.json",
        "REPORT.md",
        "tables/per_seed.csv",
        "figures/pue_by_seed.svg",
    ):
        assert (d / rel).is_file(), rel
    m = read_json(d / "manifest.json")
    for key in REQUIRED_MANIFEST_FIELDS:
        assert key in m, key
    # every field named in contract 11.1
    spec = ("run_id started_at_utc code_revision dirty lock_sha256 platform command config_files dataset_manifest_sha256 "
            "physics_version environment_version reward_version safety_envelope_version action_semantics_version "
            "scenario_set_id split_id seeds artifacts prereg_sha256 result_sha256").split()  # fmt: skip
    assert all(k in m for k in spec)
    assert set(m["platform"]) >= {"os", "arch", "python", "numpy", "torch", "tensorflow"}
    assert m["code_revision"] == SHA and m["dirty"] is False and m["code_revision_source"] == "GIT_SHA"
    assert m["config_files"] == {CONFIG: canonical.sha256_input_file(world / CONFIG)}
    assert m["dataset_manifest_sha256"] == canonical.sha256_input_file(world / "data/MANIFEST.json")
    assert m["prereg_sha256"] == canonical.sha256_input_file(world / "prereg.json")
    assert m["lock_sha256"] == canonical.sha256_input_file(world / "requirements.lock")
    assert m["artifacts"] == [
        {
            "model_id": "toyart-1",
            "status": "candidate",
            "files": {ARTIFACT_FILE: canonical.sha256_raw_file(world / ARTIFACT_FILE)},
        }
    ]
    assert m["seeds"] == [11, 22, 33] and m["result_sha256"] == canonical.sha256_bytes(
        (d / "results.json").read_bytes()
    )
    assert (
        m["physics_version"] == versions.active_physics_version() and m["environment_version"] == versions.ENV_VERSION
    )
    status = read_json(d / "status.json")
    assert (
        status["state"] == "completed"
        and status["started_at_utc"]
        and status["finished_at_utc"]
        and status["error"] is None
    )


def test_manifest_contains_no_absolute_path(world):
    outcome = make_run(
        world,
        "paths",
        argv=["scripts/run_experiment.py", "--config", str(world / CONFIG), "--runs-dir", "/elsewhere/x"],
    )
    text = (outcome.run_dir / "manifest.json").read_text()
    assert str(world) not in text and "/elsewhere" not in text
    assert read_json(outcome.run_dir / "manifest.json")["command"][2] == CONFIG


def test_timestamps_come_from_the_injected_clock_and_stay_out_of_results(world):
    times = iter(f"2026-01-01T00:00:0{i}Z" for i in range(9))
    outcome = run(RunRequest(experiment="toy", config_paths=[CONFIG], run_id="clock"), world, clock=lambda: next(times))
    assert read_json(outcome.run_dir / "manifest.json")["started_at_utc"] == "2026-01-01T00:00:00Z"
    assert "2026" not in (outcome.run_dir / "results.json").read_text()


def test_run_ids_are_validated_and_never_reused(world):
    for bad in ("../x", "a/b", "", ".hidden", "x" * 200, "a b"):
        with pytest.raises(RunError):
            make_run(world, bad)
    assert make_run(world, "once").state == "completed"
    with pytest.raises(RunError, match="already exists"):
        make_run(world, "once")
    default = run(RunRequest(experiment="toy", config_paths=[CONFIG]), world)
    assert default.run_id.startswith("toy-") and default.state == "completed"


def test_bad_inputs_are_refused_before_anything_is_written(world):
    for kw in (
        {"config_paths": ["nope.json"]},
        {"config_paths": [CONFIG], "seeds": [1, 1]},
        {"config_paths": [CONFIG], "seeds": [-3]},
        {"config_paths": [CONFIG], "dataset_manifest": "missing.json"},
        {"config_paths": [CONFIG], "artifacts": ["no-such-model"]},
        {"config_paths": []},
    ):
        with pytest.raises(RunError):
            run(RunRequest(experiment="toy", run_id="bad", **kw), world)
    with pytest.raises(experiments.UnknownExperiment):
        run(RunRequest(experiment="nope", config_paths=[CONFIG]), world)
    assert not (world / "reports/runs").exists()


def test_inputs_outside_the_project_root_are_refused(world, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "cfg.json"
    outside.write_text("{}")
    with pytest.raises(RunError, match="outside the project root"):
        run(RunRequest(experiment="toy", config_paths=[str(outside)]), world)


def test_artifact_whose_file_differs_from_the_registry_is_refused(world):
    flip(world / ARTIFACT_FILE)
    with pytest.raises(RunError, match="differs from the registry"):
        make_run(world, "art", artifacts=["toyart-1"])


def test_seeds_can_be_overridden_on_the_request(world):
    outcome = make_run(world, "seeded", seeds=[5, 6])
    assert read_json(outcome.run_dir / "manifest.json")["seeds"] == [5, 6]
    assert read_json(outcome.run_dir / "results.json")["seeds"] == [5, 6]


# ----------------------------------------------------------------------------- determinism (level L1)


def test_identical_config_and_seed_give_byte_identical_results_json(world):
    a, b = make_run(world, "twin-a"), make_run(world, "twin-b")
    ra, rb = (a.run_dir / "results.json").read_bytes(), (b.run_dir / "results.json").read_bytes()
    assert ra == rb and len(ra) > 500
    assert (a.run_dir / "REPORT.md").read_bytes() == (b.run_dir / "REPORT.md").read_bytes()
    for rel in ("tables/per_seed.csv", "figures/mean_pue_by_policy.svg"):
        assert (a.run_dir / rel).read_bytes() == (b.run_dir / rel).read_bytes()
    assert (
        read_json(a.run_dir / "manifest.json")["result_sha256"]
        == read_json(b.run_dir / "manifest.json")["result_sha256"]
    )


def test_a_different_seed_or_config_changes_the_results(world):
    base = (make_run(world, "base").run_dir / "results.json").read_bytes()
    assert (make_run(world, "seed", seeds=[11, 22, 34]).run_dir / "results.json").read_bytes() != base
    cfg = json.loads((world / CONFIG).read_text())
    cfg["constant_setpoint_C"] = 9.0
    (world / "other.json").write_text(json.dumps(cfg))
    changed = run(RunRequest(experiment="toy", config_paths=["other.json"], run_id="cfg"), world)
    assert (changed.run_dir / "results.json").read_bytes() != base


def test_in_process_double_execution_agrees():
    cfg = json.loads((ROOT / CONFIG).read_text())
    a = execute_experiment("toy", cfg, cfg["seeds"], check_determinism=True)
    assert canonical.canonical_bytes(a) == canonical.canonical_bytes(execute_experiment("toy", cfg, cfg["seeds"]))


def test_a_nondeterministic_experiment_fails_the_run_and_is_recorded(world):
    counter = {"n": 0}

    def flaky(config, seeds, rng_factory):
        counter["n"] += 1
        out = toy.run(config, seeds, rng_factory)
        out["experiment"] = "flaky"
        out["summary"]["mean_pue_rule"] += counter["n"] * 1e-3
        return out

    experiments.register("flaky", flaky)
    try:
        outcome = run(
            RunRequest(experiment="flaky", config_paths=[CONFIG], run_id="flaky", check_determinism=True), world
        )
    finally:
        experiments._REGISTRY.pop("flaky")
    assert outcome.state == "failed" and "not deterministic" in outcome.error
    status = read_json(outcome.run_dir / "status.json")
    assert status["state"] == "failed" and "not deterministic" in status["error"]
    assert not (outcome.run_dir / "results.json").exists()


def test_an_experiment_using_the_global_rng_fails(world):
    def sloppy(config, seeds, rng_factory):
        np.random.rand(3)
        return toy.run(config, seeds, rng_factory)

    experiments.register("sloppy", sloppy)
    try:
        outcome = run(RunRequest(experiment="sloppy", config_paths=[CONFIG], run_id="sloppy"), world)
    finally:
        experiments._REGISTRY.pop("sloppy")
    assert outcome.state == "failed" and "GlobalRngTouched" in outcome.error


def test_results_that_ignore_the_schema_fail_the_run(world):
    experiments.register("bad", lambda c, s, r: {"schema": "nope"})
    try:
        outcome = run(RunRequest(experiment="bad", config_paths=[CONFIG], run_id="badres"), world)
    finally:
        experiments._REGISTRY.pop("bad")
    assert outcome.state == "failed" and "schema" in outcome.error


def test_failed_runs_scrub_absolute_paths_and_cannot_be_verified_or_promoted(world):
    def boom(config, seeds, rng_factory):
        raise OSError(f"cannot open {world}/data/secret.csv")

    experiments.register("boom", boom)
    try:
        outcome = run(RunRequest(experiment="boom", config_paths=[CONFIG], run_id="boom"), world)
    finally:
        experiments._REGISTRY.pop("boom")
    assert outcome.state == "failed" and str(world) not in outcome.error and "<path>" in outcome.error
    assert str(world) not in (outcome.run_dir / "error.txt").read_text()
    rep = verify_run(world, "boom")
    assert "status.state" in names(rep) and "results.json" in names(rep)
    assert promotion_eligibility(world, "boom")[0] is False


# ----------------------------------------------------------------------------- verify: passes and names the field that changed


def test_verify_passes_on_an_untouched_run(world):
    full_run(world)
    rep = verify_run(world, "r1")
    assert rep.failures == [] and rep.warnings == [] and rep.ok(strict=True)


def test_verify_with_rerun_reproduces_results_exactly(world):
    full_run(world)
    assert verify_run(world, "r1", rerun=True).ok(strict=True)


def test_verify_rerun_detects_that_the_code_no_longer_reproduces_the_results(world):
    full_run(world)
    original = experiments._REGISTRY["toy"]

    def drifted(config, seeds, rng_factory):
        out = original(config, seeds, rng_factory)
        out["summary"]["mean_pue_rule"] += 0.5
        return out

    experiments._REGISTRY["toy"] = drifted
    try:
        rep = verify_run(world, "r1", rerun=True)
    finally:
        experiments._REGISTRY["toy"] = original
    assert names(rep) == ["results.json"] and "different results" in rep.failures[0].message


def test_altering_the_config_fails_verify_naming_the_field(world):
    full_run(world)
    cfg = json.loads((world / CONFIG).read_text())
    cfg["episodes_per_seed"] = 7
    (world / CONFIG).write_text(json.dumps(cfg))
    rep = verify_run(world, "r1")
    assert names(rep) == [f"config_files[{CONFIG}]"]
    assert "sha256" in rep.failures[0].message


@pytest.mark.parametrize(
    "mutate,field",
    [
        (lambda w: (w / "data/MANIFEST.json").write_text('{"files": {"a.csv": "11"}}\n'), "dataset_manifest_sha256"),
        (lambda w: (w / "prereg.json").write_text('{"alpha": 0.6}\n'), "prereg_sha256"),
        (lambda w: (w / "requirements.lock").write_text("numpy==9.9.9\n"), "lock_sha256"),
        (lambda w: flip(w / ARTIFACT_FILE), f"artifacts[toyart-1].files[{ARTIFACT_FILE}]"),
        (lambda w: (w / "data/MANIFEST.json").unlink(), "dataset_manifest_sha256"),
        (lambda w: (w / ARTIFACT_FILE).unlink(), f"artifacts[toyart-1].files[{ARTIFACT_FILE}]"),
    ],
)
def test_altering_any_other_recorded_input_fails_verify_naming_the_field(world, mutate, field):
    full_run(world)
    mutate(world)
    assert names(verify_run(world, "r1")) == [field]


def test_line_ending_changes_to_text_inputs_do_not_break_verify(world):
    full_run(world)
    lock = world / "requirements.lock"
    lock.write_bytes(lock.read_text().replace("\n", "\r\n").encode("utf-16"))  # e.g. a Windows checkout
    assert verify_run(world, "r1").failures == []


def test_a_crlf_checkout_of_the_run_directory_still_verifies(world):
    full_run(world)
    for f in (world / "reports/runs/r1").rglob("*"):
        if f.is_file() and f.suffix in (".json", ".md", ".csv", ".svg"):
            f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert verify_run(world, "r1").failures == []
    assert promotion_eligibility(world, "r1") == (True, [])


def _edit_results(world, fn):
    path = world / "reports/runs/r1/results.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda w: _edit_results(w, lambda d: d["summary"].update(mean_pue_rule=0.5)), {"result_sha256"}),
        (lambda w: (w / "reports/runs/r1/results.json").write_text("{}"), {"result_sha256", "results.json"}),
        (lambda w: (w / "reports/runs/r1/results.json").unlink(), {"results.json"}),
        (lambda w: (w / "reports/runs/r1/REPORT.md").write_text("# hand edited 0.123\n"), {"REPORT.md"}),
        (lambda w: (w / "reports/runs/r1/REPORT.md").unlink(), {"REPORT.md"}),
        (lambda w: flip(w / "reports/runs/r1/tables/per_seed.csv"), {"tables/per_seed.csv"}),
        (lambda w: (w / "reports/runs/r1/figures/pue_by_seed.svg").write_text("<svg/>"), {"figures/pue_by_seed.svg"}),
        (lambda w: (w / "reports/runs/r1/figures/pue_by_seed.svg").unlink(), {"figures/pue_by_seed.svg"}),
        (lambda w: (w / "reports/runs/r1/tables/extra.csv").write_text("a\n1\n"), {"tables/extra.csv"}),
    ],
)
def test_tampering_with_results_or_generated_files_is_caught_by_name(world, mutate, expected):
    full_run(world)
    mutate(world)
    assert expected <= set(names(verify_run(world, "r1")))


def test_a_report_number_edit_is_named_as_absent_from_results_json(world):
    full_run(world)
    path = world / "reports/runs/r1/REPORT.md"
    path.write_text(path.read_text().replace("| episodes_total | 18 |", "| episodes_total | 1800 |"))
    rep = verify_run(world, "r1")
    assert any(f.field == "REPORT.md" and "1800" in f.message for f in rep.failures)


def test_manifest_problems_are_reported(world):
    full_run(world)
    mpath = world / "reports/runs/r1/manifest.json"
    m = json.loads(mpath.read_text())
    del m["lock_sha256"]
    mpath.write_text(json.dumps(m))
    rep = verify_run(world, "r1")
    assert names(rep) == ["manifest.json"] and "lock_sha256" in rep.failures[0].message
    mpath.write_text("not json")
    assert names(verify_run(world, "r1")) == ["manifest.json"]
    assert names(verify_run(world, "missing-run")) == ["run_id"]
    assert names(verify_run(world, "../x")) == ["run_id"]


def test_manifest_seed_edit_is_caught(world):
    full_run(world)
    mpath = world / "reports/runs/r1/manifest.json"
    m = json.loads(mpath.read_text())
    m["seeds"] = [1, 2, 3]
    mpath.write_text(json.dumps(m))
    assert "seeds" in names(verify_run(world, "r1"))


def test_a_run_still_marked_running_fails_verify(world):
    full_run(world)
    spath = world / "reports/runs/r1/status.json"
    s = json.loads(spath.read_text())
    s["state"] = "running"
    spath.write_text(json.dumps(s))
    assert names(verify_run(world, "r1")) == ["status.state"]


def test_a_recorded_path_that_escapes_the_root_fails_instead_of_reading_it(world):
    full_run(world)
    mpath = world / "reports/runs/r1/manifest.json"
    m = json.loads(mpath.read_text())
    m["config_files"] = {"../../etc/passwd": "0" * 64}
    mpath.write_text(json.dumps(m))
    assert any(
        "not a project-relative path" in f.message or "escapes" in f.message for f in verify_run(world, "r1").failures
    )


# ----------------------------------------------------------------------------- code revision, versions, platform


def test_a_changed_code_revision_fails_verify(world, monkeypatch):
    full_run(world)
    monkeypatch.setenv("GIT_SHA", "d" * 40)
    rep = verify_run(world, "r1")
    assert names(rep) == ["code_revision"] and SHA in rep.failures[0].message


def test_unknown_code_revision_is_a_warning_that_strict_turns_into_a_failure(world, monkeypatch):
    monkeypatch.delenv("GIT_SHA")
    full_run(world)
    assert read_json(world / "reports/runs/r1/manifest.json")["code_revision"] == "unknown"
    rep = verify_run(world, "r1")
    assert rep.failures == [] and [w.field for w in rep.warnings] == ["code_revision"]
    assert rep.ok() and not rep.ok(strict=True)


def test_a_changed_version_constant_fails_verify_naming_it(world, monkeypatch):
    full_run(world)
    monkeypatch.setattr(versions, "REWARD_VERSION", "2")
    assert names(verify_run(world, "r1")) == ["reward_version"]


def test_a_different_platform_is_a_warning_not_a_failure(world, monkeypatch):
    full_run(world)
    real = env.platform_info()
    monkeypatch.setattr(env, "platform_info", lambda: {**real, "numpy": "0.0.1", "arch": "riscv"})
    rep = verify_run(world, "r1")
    assert rep.failures == [] and {w.field for w in rep.warnings} == {"platform.numpy", "platform.arch"}


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": __import__("os").environ["PATH"],
            "HOME": str(cwd),
        },
    )


@pytest.fixture
def gitworld(world, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    monkeypatch.delenv("GIT_SHA")
    _git(world, "init", "-q")
    _git(world, "add", "-A")
    _git(world, "commit", "-q", "-m", "init")
    return world


def test_clean_git_tree_is_recorded_clean_and_a_run_does_not_dirty_it(gitworld):
    state = env.code_state(gitworld)
    assert state["code_revision_source"] == "git" and state["dirty"] is False and len(state["code_revision"]) == 40
    full_run(gitworld)
    assert env.code_state(gitworld)["dirty"] is False  # reports/runs is excluded from the dirty check
    assert verify_run(gitworld, "r1").ok(strict=True)
    assert promotion_eligibility(gitworld, "r1") == (True, [])


def test_a_dirty_git_tree_sets_dirty_true_forbids_promotion_and_pins_the_exact_diff(gitworld):
    (gitworld / "prereg.json").write_text('{"alpha": 0.9}\n')
    (gitworld / "untracked.py").write_text("x = 1\n")
    full_run(gitworld, "dirty")
    m = read_json(gitworld / "reports/runs/dirty/manifest.json")
    assert m["dirty"] is True and m["dirty_diff_sha256"] and m["code_revision_source"] == "git"
    ok, reasons = promotion_eligibility(gitworld, "dirty")
    assert ok is False and any("dirty" in r for r in reasons)
    with pytest.raises(NotPromotable):
        require_promotable(gitworld, "dirty")
    assert verify_run(gitworld, "dirty").failures == []
    (gitworld / "untracked.py").write_text("x = 2\n")  # code changed since the dirty run: not the same code any more
    (gitworld / "other.py").write_text("y = 1\n")
    assert "dirty_diff_sha256" in names(verify_run(gitworld, "dirty"))


def test_a_run_recorded_clean_fails_verify_once_the_tree_is_modified(gitworld):
    full_run(gitworld)
    (gitworld / "requirements.lock").write_text("numpy==2.4.4\n# edited\n")
    assert "dirty" in names(verify_run(gitworld, "r1")) or "lock_sha256" in names(verify_run(gitworld, "r1"))


def test_require_clean_refuses_a_dirty_tree_before_creating_the_run(gitworld):
    (gitworld / "x.txt").write_text("dirty")
    with pytest.raises(RunError, match="dirty"):
        make_run(gitworld, "rc", require_clean=True)
    assert not (gitworld / "reports/runs/rc").exists()


# ----------------------------------------------------------------------------- promotion eligibility without git


def test_promotion_requires_a_complete_non_dirty_run_with_a_revision(world, monkeypatch):
    full_run(world, "clean")
    assert promotion_eligibility(world, "clean") == (True, [])
    require_promotable(world, "clean")
    monkeypatch.setenv("GIT_DIRTY", "1")
    full_run(world, "flagged")
    assert promotion_eligibility(world, "flagged")[0] is False
    monkeypatch.delenv("GIT_DIRTY")
    monkeypatch.delenv("GIT_SHA")
    full_run(world, "unknown")
    ok, reasons = promotion_eligibility(world, "unknown")
    assert not ok and any("dirty" in r or "unverifiable" in r for r in reasons) and any("40-hex" in r for r in reasons)
    assert promotion_eligibility(world, "never-ran")[0] is False


def test_promotion_is_refused_when_results_no_longer_match_the_manifest(world):
    full_run(world, "tamper")
    (world / "reports/runs/tamper/results.json").write_text("{}")
    ok, reasons = promotion_eligibility(world, "tamper")
    assert not ok and any("result_sha256" in r for r in reasons)


# ----------------------------------------------------------------------------- report generation uses results.json only


def _results():
    cfg = json.loads((ROOT / CONFIG).read_text())
    return execute_experiment("toy", cfg, cfg["seeds"])


def test_every_number_in_report_md_is_present_in_results_json(world):
    outcome = full_run(world)
    results = read_json(outcome.run_dir / "results.json")
    text = (outcome.run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert report.check_report_numbers(text, results) == []
    assert len(report._NUMBER_TOKEN.findall(text)) > 30  # the check is not vacuous


def test_a_number_absent_from_results_json_is_detected():
    results = _results()
    text = report.render_report(results)
    assert report.check_report_numbers(text, results) == []
    assert report.check_report_numbers(text + "\nThe policy saves 12.5 percent.\n", results) == ["12.5"]
    assert report.check_report_numbers(text.replace("| episodes_total | 18 |", "| episodes_total | 19 |"), results) == [
        "19"
    ]


def test_report_functions_take_results_and_nothing_else(monkeypatch):
    for fn in (report.render_report, report.render_tables, report.render_figures, report.render_all):
        assert list(inspect.signature(fn).parameters) == ["results"]
    results = _results()
    expected = report.render_all(results)
    monkeypatch.setenv("GIT_SHA", "e" * 40)  # environment, clock and cwd cannot matter
    monkeypatch.chdir("/")
    assert report.render_all(json.loads(canonical.canonical_dumps(results))) == expected
    source = (ROOT / "src/repro/report.py").read_text()
    assert not any(
        word in source for word in ("open(", "read_text", "os.environ", "datetime", "time.time", "import random")
    )


def test_the_report_changes_only_when_results_change():
    a = _results()
    b = json.loads(json.dumps(a))
    b["summary"]["mean_pue_rule"] = 1.5
    assert report.render_report(a) != report.render_report(b)
    assert report.render_tables(a) == report.render_tables(json.loads(json.dumps(a)))


def test_regenerated_files_are_the_files_on_disk(world):
    outcome = full_run(world)
    results = read_json(outcome.run_dir / "results.json")
    for rel, text in report.render_all(results).items():
        assert (outcome.run_dir / rel).read_bytes() == text.encode("utf-8"), rel


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(schema="x"),
        lambda r: r.update(seeds=[1.5]),
        lambda r: r["tables"]["per_seed"]["rows"].append([1]),
        lambda r: r["tables"].update({"bad/name": r["tables"]["per_seed"]}),
        lambda r: r["figures"]["pue_by_seed"].update(type="pie"),
        lambda r: r["figures"]["pue_by_seed"]["series"].update(x=[1.0]),
        lambda r: r.update(notes="no"),
        lambda r: r["summary"].update(bad=[1]),
    ],
)
def test_invalid_results_are_rejected(mutate):
    results = json.loads(json.dumps(_results()))
    mutate(results)
    with pytest.raises(report.ResultsError):
        report.validate_results(results)


def test_figures_are_deterministic_well_formed_svg():
    import xml.dom.minidom

    results = _results()
    for rel, svg in report.render_figures(results).items():
        xml.dom.minidom.parseString(svg)
        assert svg == report.render_figures(json.loads(json.dumps(results)))[rel]


# ----------------------------------------------------------------------------- command-line scripts


def _script(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call(fn, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(argv)
    return code, out.getvalue(), err.getvalue()


def test_cli_round_trip_run_verify_promotable_list(world):
    run_experiment, repro = _script("run_experiment"), _script("repro")
    base = ["--root", str(world)]
    code, out, err = _call(
        run_experiment.main,
        [*base, "--experiment", "toy", "--config", CONFIG, "--run-id", "cli", "--check-determinism"],
    )
    assert code == 0 and out.strip() == "cli" and err == ""
    code, out, _ = _call(repro.main, [*base, "verify", "cli", "--rerun", "--strict"])
    assert code == 0 and out.strip().startswith("PASS cli: 0 failure(s), 0 warning(s)")
    assert _call(repro.main, [*base, "promotable", "cli"])[0] == 0
    code, out, _ = _call(repro.main, [*base, "list"])
    assert code == 0 and "cli\tcompleted\tdirty=False" in out
    (world / CONFIG).write_text(
        (world / CONFIG).read_text().replace('"episodes_per_seed": 6', '"episodes_per_seed": 5')
    )
    code, out, _ = _call(repro.main, [*base, "verify", "cli"])
    assert code == 1 and f"FAIL config_files[{CONFIG}]" in out and "FAIL cli" in out


def test_cli_exit_codes_for_bad_inputs_and_failed_runs(world):
    run_experiment, repro = _script("run_experiment"), _script("repro")
    base = ["--root", str(world)]
    assert _call(run_experiment.main, [*base, "--experiment", "toy", "--config", "missing.json"])[0] == 2
    assert _call(run_experiment.main, [*base, "--experiment", "nope", "--config", CONFIG])[0] == 2
    assert _call(repro.main, [*base, "verify", "no-such-run"])[0] == 2
    assert _call(repro.main, [*base, "verify", "../bad"])[0] == 2
    assert _call(repro.main, [*base, "promotable", "no-such-run"])[0] == 1
    assert _call(repro.main, [*base, "list"])[1].strip() == "no runs"
    experiments.register("boom2", lambda c, s, r: 1 / 0)
    try:
        code, _, err = _call(
            run_experiment.main, [*base, "--experiment", "boom2", "--config", CONFIG, "--run-id", "b2"]
        )
    finally:
        experiments._REGISTRY.pop("boom2")
    assert code == 1 and "FAILED b2" in err and "ZeroDivisionError" in err


def test_cli_notes_that_a_dirty_run_cannot_be_promoted(world, monkeypatch):
    monkeypatch.setenv("GIT_DIRTY", "1")
    code, out, err = _call(
        _script("run_experiment").main,
        ["--root", str(world), "--experiment", "toy", "--config", CONFIG, "--run-id", "d"],
    )
    assert code == 0 and "never support a promotion" in err


# ----------------------------------------------------------------------------- the shipped toy run, and static rules


def test_the_shipped_toy_reference_run_round_trips():
    run_dir = ROOT / "reports/runs/toy-reference"
    assert run_dir.is_dir(), "run: python scripts/run_experiment.py --experiment toy --config src/repro/toy_config.json --run-id toy-reference --check-determinism"
    rep = verify_run(ROOT, "toy-reference", rerun=True)
    assert rep.failures == [], [str(f) for f in rep.failures]
    results = read_json(run_dir / "results.json")
    assert report.check_report_numbers((run_dir / "REPORT.md").read_text(encoding="utf-8"), results) == []
    assert read_json(run_dir / "status.json")["state"] == "completed"


def test_the_shipped_toy_results_are_what_the_toy_experiment_produces_now():
    shipped = (ROOT / "reports/runs/toy-reference/results.json").read_bytes()
    assert canonical.canonical_bytes(_results()) == shipped  # same machine/environment (level L1)


_SCANNED = [*sorted((ROOT / "src/repro").glob("*.py")), ROOT / "scripts/run_experiment.py", ROOT / "scripts/repro.py"]
_GLOBAL_NUMPY = {
    "seed",
    "RandomState",
    "rand",
    "randn",
    "randint",
    "random",
    "random_sample",
    "shuffle",
    "choice",
    "normal",
    "uniform",
    "permutation",
    "set_state",
    "bytes",
}


def test_no_global_random_state_is_used_or_seeded_anywhere_in_the_framework():
    offenders = []
    for path in _SCANNED:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain, cur = [node.attr], node.value
                while isinstance(cur, ast.Attribute):
                    chain.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    chain.append(cur.id)
                dotted = ".".join(reversed(chain))
                if (
                    dotted.split(".")[0] in ("np", "numpy")
                    and ".random." in dotted + "."
                    and dotted.split(".")[-1] in _GLOBAL_NUMPY
                    and ".random." in dotted
                ):
                    offenders.append((path.name, dotted))
                if dotted in ("random.seed", "random.random", "random.shuffle", "random.randint", "random.choice"):
                    offenders.append((path.name, dotted))
    assert offenders == []


def test_experiments_reach_randomness_only_through_the_factory():
    source = (ROOT / "src/repro/toy.py").read_text()
    assert "default_rng" not in source and "np.random." not in source.replace("np.random.Generator", "")
    assert "rng_factory(" in source


def test_framework_files_do_not_read_the_clock_inside_results_or_reports():
    for name in ("toy.py", "report.py", "canonical.py"):
        source = (ROOT / "src/repro" / name).read_text()
        assert not any(w in source for w in ("datetime", "time.time", "perf_counter", "os.environ", "getpid"))
