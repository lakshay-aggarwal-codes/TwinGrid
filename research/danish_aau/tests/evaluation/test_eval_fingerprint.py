"""Evaluation source fingerprint: content-sensitive, includes untracked files, excludes generated output."""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from research.danish_aau.evaluation import (  # noqa: F401  (stages registers 'preflight')
    _reuse,
    cli,
    fingerprint,
    stages,
)
from research.danish_aau.evaluation.config import load_config
from research.danish_aau.evaluation.manifest import MANIFEST_NAME, verify_manifest
from research.danish_aau.evaluation.paths import REPO_ROOT
from research.danish_aau.evaluation.runner import RunContext, run_pipeline

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
HAS_GIT = shutil.which("git") is not None
EDITABLE = "research/danish_aau/evaluation/inventory.py"


def _copy_tree(dest: Path) -> Path:
    for rel in fingerprint.list_source_files(REPO_ROOT):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)
    return dest


@pytest.fixture
def tree(tmp_path):
    return _copy_tree(tmp_path / "repo")


def _git(tree: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=tree, check=True, capture_output=True
    )


@pytest.fixture
def git_tree(tree):
    if not HAS_GIT:
        pytest.skip("git not available")
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-qm", "init")
    return tree


def fp(tree: Path) -> str:
    return fingerprint.compute(tree)["sha256"]


# ------------------------------------------------------------------------------------------ coverage
def test_covered_files_are_exactly_the_required_set():
    files = fingerprint.list_source_files(REPO_ROOT)
    for required in (
        "research/danish_aau/run_evaluation.py",
        "research/danish_aau/config/default.toml",
        "research/danish_aau/docs/EVALUATION_PLAN.md",
        "research/danish_aau/docs/EVALUATION_HARNESS.md",
        "research/danish_aau/evaluation/fingerprint.py",
        "research/danish_aau/evaluation/stages/preflight.py",
        "src/repro/canonical.py",
        "src/repro/env.py",
    ):
        assert required in files
    assert not any("/tests/" in f or f.startswith("realData") or "outputs" in f for f in files)
    assert files == sorted(files)


def test_a_missing_required_file_is_an_error_not_a_silent_omission(tree):
    (tree / "src/repro/env.py").unlink()
    with pytest.raises(fingerprint.FingerprintError):
        fp(tree)


# ------------------------------------------------------------------------------------ determinism
def test_identical_source_gives_identical_fingerprints_even_in_different_locations(tmp_path):
    a = _copy_tree(tmp_path / "one" / "deeper" / "repo")
    b = _copy_tree(tmp_path / "two" / "repo")
    assert fp(a) == fp(a) == fp(b) == fp(REPO_ROOT)
    assert len(fp(a)) == 64


def test_line_endings_and_bom_do_not_change_the_fingerprint(tree):
    before = fp(tree)
    target = tree / EDITABLE
    target.write_bytes(b"\xef\xbb\xbf" + target.read_bytes().replace(b"\n", b"\r\n"))
    assert fp(tree) == before


def test_file_path_is_part_of_the_fingerprint(tree):
    before = fp(tree)
    (tree / "research/danish_aau/evaluation/stages/extra.py").write_text("X = 1\n", encoding="utf-8")
    one = fp(tree)
    (tree / "research/danish_aau/evaluation/stages/extra.py").rename(tree / "research/danish_aau/evaluation/extra.py")
    assert before != one != fp(tree)


# --------------------------------------------------------------------------- sensitivity to edits
def test_modifying_a_tracked_source_file_changes_the_fingerprint(git_tree):
    before = fp(git_tree)
    target = git_tree / EDITABLE
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n# tracked edit\n", encoding="utf-8")
    assert fp(git_tree) != before
    target.write_text(original, encoding="utf-8")
    assert fp(git_tree) == before  # reverting restores it exactly


def test_modifying_an_untracked_source_file_changes_the_fingerprint(git_tree):
    new = git_tree / "research/danish_aau/evaluation/untracked_module.py"
    new.write_text("VALUE = 1\n", encoding="utf-8")
    assert (
        "?? research/danish_aau/evaluation/untracked_module.py"
        in subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=git_tree, capture_output=True, text=True
        ).stdout
    )  # genuinely untracked
    first = fp(git_tree)
    new.write_text("VALUE = 2\n", encoding="utf-8")
    assert fp(git_tree) != first


def test_untracked_config_and_doc_edits_are_covered_too(git_tree):
    (git_tree / "research/danish_aau/config/variant.toml").write_text("a = 1\n", encoding="utf-8")
    (git_tree / "research/danish_aau/docs/EVALUATION_NOTES.md").write_text("n1\n", encoding="utf-8")
    first = fp(git_tree)
    (git_tree / "research/danish_aau/config/variant.toml").write_text("a = 2\n", encoding="utf-8")
    second = fp(git_tree)
    (git_tree / "research/danish_aau/docs/EVALUATION_NOTES.md").write_text("n2\n", encoding="utf-8")
    assert len({first, second, fp(git_tree)}) == 3


def test_reused_twingrid_helper_edits_are_covered(tree):
    before = fp(tree)
    (tree / "src/repro/canonical.py").write_text(
        (tree / "src/repro/canonical.py").read_text(encoding="utf-8") + "\n#x\n", encoding="utf-8"
    )
    assert fp(tree) != before


def test_the_gap_this_closes_env_code_state_ignores_untracked_content(git_tree):
    """Documents WHY the fingerprint exists: the reused env.code_state digest does not see untracked file content."""
    env = _reuse.repro_env()
    new = git_tree / "research/danish_aau/evaluation/untracked_module.py"
    new.write_text("VALUE = 1\n", encoding="utf-8")
    code_a, fp_a = env.code_state(git_tree), fp(git_tree)
    new.write_text("VALUE = 2\n", encoding="utf-8")
    code_b, fp_b = env.code_state(git_tree), fp(git_tree)
    assert code_a["dirty_diff_sha256"] == code_b["dirty_diff_sha256"]  # blind to the edit
    assert fp_a != fp_b  # the fingerprint is not


# ------------------------------------------------------------------------------- exclusions
def test_generated_outputs_caches_and_raw_data_do_not_change_it(tree):
    before = fp(tree)
    junk = [
        "research/danish_aau/outputs/run1/manifest.json",
        "research/danish_aau/outputs/run1/stage_preflight.json",
        "research/danish_aau/evaluation/__pycache__/cli.cpython-312.pyc",
        "research/danish_aau/evaluation/stages/__pycache__/preflight.cpython-312.pyc",
        "research/danish_aau/.pytest_cache/v/cache/lastfailed",
        "research/danish_aau/evaluation/stray.pyc",
        # .py / .toml / EVALUATION_*.md names that the globs DO match, but that live in excluded directories:
        "research/danish_aau/evaluation/__pycache__/leftover.py",
        "research/danish_aau/evaluation/outputs/generated.py",
        "research/danish_aau/evaluation/stages/.pytest_cache/cached.py",
        "research/danish_aau/evaluation/realData/copy.py",
        "research/danish_aau/config/outputs/run.toml",
        "research/danish_aau/tests/evaluation/test_eval_paths.py",
        "realData/danish-server-room-v5/raw/AAU_air_speed_25_percent_load_period.csv",
        "research/danish_aau/reports/audit_report.json",
    ]
    for rel in junk:
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"generated content 1")
    after_create = fp(tree)
    for rel in junk:
        (tree / rel).write_bytes(b"generated content 2, different and longer")
    assert before == after_create == fp(tree)
    assert not any(f["path"] in junk for f in fingerprint.compute(tree)["files"])


# -------------------------------------------------------------------- no machine-specific paths
def test_entries_are_relative_posix_paths_only(tree):
    result = fingerprint.compute(tree)
    for entry in result["files"]:
        path = entry["path"]
        assert not path.startswith(("/", "\\")) and ":" not in path and "\\" not in path and ".." not in path.split("/")
        assert str(tree) not in path
    assert str(tree) not in json.dumps(result)


# -------------------------------------------------------------------- manifest + verify integration
def _run(tree, tmp_path, raw_dir, registry, config_path, run_id):
    ctx = RunContext(
        config=load_config(config_path),
        config_path="fixture.toml",
        repo_root=tree,
        raw_dir=raw_dir,
        raw_dir_source="cli",
        run_dir=tmp_path / "out" / run_id,
        run_id=run_id,
        registry=registry,
    )
    manifest, code = run_pipeline(ctx, ["preflight"], ["run"], now=NOW)
    assert code == 0
    return manifest, ctx.run_dir / MANIFEST_NAME


def test_fingerprint_is_in_the_manifest_core_and_moves_the_core_hash(
    tmp_path, tree, raw_dir, fixture_registry, fixture_config
):
    a, _ = _run(tree, tmp_path, raw_dir, fixture_registry, fixture_config, "a")
    assert a["evaluation_source_fingerprint"] == fp(tree) and a["source_fingerprint_scheme"] == fingerprint.SCHEME
    (tree / "research/danish_aau/evaluation/untracked_module.py").write_text("V = 1\n", encoding="utf-8")
    b, _ = _run(tree, tmp_path, raw_dir, fixture_registry, fixture_config, "b")
    assert a["determinism"]["manifest_core_sha256"] != b["determinism"]["manifest_core_sha256"]
    (tree / "research/danish_aau/evaluation/untracked_module.py").write_text("V = 2\n", encoding="utf-8")
    c, _ = _run(tree, tmp_path, raw_dir, fixture_registry, fixture_config, "c")
    assert b["determinism"]["manifest_core_sha256"] != c["determinism"]["manifest_core_sha256"]


def test_same_source_gives_the_same_core_hash_in_two_locations(tmp_path, raw_dir, fixture_registry, fixture_config):
    t1, t2 = _copy_tree(tmp_path / "x" / "repo"), _copy_tree(tmp_path / "y" / "repo")
    a, _ = _run(t1, tmp_path, raw_dir, fixture_registry, fixture_config, "a")
    b, _ = _run(t2, tmp_path, raw_dir, fixture_registry, fixture_config, "b")
    assert a["determinism"] == b["determinism"]


def test_manifest_contains_no_absolute_source_or_repo_paths(tmp_path, tree, raw_dir, fixture_registry, fixture_config):
    _, path = _run(tree, tmp_path, raw_dir, fixture_registry, fixture_config, "a")
    text = path.read_text(encoding="utf-8")
    for forbidden in (str(tree), str(tmp_path), str(REPO_ROOT)):
        assert forbidden not in text


def test_verify_passes_then_detects_source_changes(tmp_path, tree, raw_dir, fixture_registry, fixture_config):
    _, path = _run(tree, tmp_path, raw_dir, fixture_registry, fixture_config, "a")
    results = verify_manifest(path, raw_dir, tree)
    assert {r["status"] for r in results} == {"pass"}
    assert {"source_fingerprint_consistent", "source_unchanged"} <= {r["check"] for r in results}

    untracked = tree / "research/danish_aau/evaluation/untracked_module.py"
    untracked.write_text("V = 1\n", encoding="utf-8")
    bad = next(r for r in verify_manifest(path, raw_dir, tree) if r["check"] == "source_unchanged")
    assert bad["status"] == "fail" and "untracked_module.py" in bad["detail"] and "added" in bad["detail"]
    untracked.unlink()

    target = tree / EDITABLE
    target.write_text(target.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
    bad = next(r for r in verify_manifest(path, raw_dir, tree) if r["check"] == "source_unchanged")
    assert bad["status"] == "fail" and EDITABLE in bad["detail"] and "modified" in bad["detail"]


def test_verify_detects_a_tampered_fingerprint_or_file_list(tmp_path, tree, raw_dir, fixture_registry, fixture_config):
    _, path = _run(tree, tmp_path, raw_dir, fixture_registry, fixture_config, "a")
    original = path.read_text(encoding="utf-8")

    doc = json.loads(original)
    doc["evaluation_source_fingerprint"] = "0" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")
    checks = {r["check"]: r["status"] for r in verify_manifest(path, raw_dir, tree)}
    assert checks["core_hash"] == "fail" and checks["source_fingerprint_consistent"] == "fail"

    doc = json.loads(original)
    doc["source_files"][0]["sha256"] = "f" * 64
    path.write_text(json.dumps(doc), encoding="utf-8")
    checks = {r["check"]: r["status"] for r in verify_manifest(path, raw_dir, tree)}
    assert checks["source_fingerprint_consistent"] == "fail"

    doc = json.loads(original)
    del doc["source_files"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert (
        next(r for r in verify_manifest(path, raw_dir, tree) if r["check"] == "source_fingerprint_consistent")["status"]
        == "fail"
    )


def test_old_schema_manifests_are_rejected_clearly(tmp_path, tree, raw_dir, fixture_registry, fixture_config):
    _, path = _run(tree, tmp_path, raw_dir, fixture_registry, fixture_config, "a")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["schema"] = "twingrid.aau_eval.manifest/1"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert next(r for r in verify_manifest(path, raw_dir, tree) if r["check"] == "schema")["status"] == "fail"


def test_cli_verify_uses_the_repo_root_and_reports_source_change(
    tmp_path, tree, raw_dir, fixture_registry, fixture_config, capsys
):
    out = tmp_path / "cli_out"
    base = ["--config", str(fixture_config), "--repo-root", str(tree)]
    assert cli.main(["run", *base, "--out-dir", str(out), "--run-id", "t"]) == 0
    assert cli.main(["verify", str(out / "t"), *base]) == 0
    (tree / "research/danish_aau/run_evaluation.py").write_text("# changed\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["verify", str(out / "t"), *base]) == 2
    assert "source_unchanged" in capsys.readouterr().out
