"""Path anchoring and output-safety rules."""

import pytest

from research.danish_aau.evaluation import paths
from research.danish_aau.evaluation.paths import (
    REPO_ROOT,
    UnsafeOutputPath,
    ensure_output_dir_safe,
    resolve_against_root,
    resolve_raw_dir,
)


def test_repo_root_is_the_twingrid_repository():
    assert (REPO_ROOT / "src" / "digital_twin.py").is_file()
    assert paths.DANISH_AAU_DIR == REPO_ROOT / "research" / "danish_aau"


def test_default_raw_dir_is_independent_of_cwd(tmp_path, monkeypatch):
    # Reproduce the old failure: a process whose cwd is already inside research/danish_aau.
    nested = tmp_path / "research" / "danish_aau"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    got = resolve_raw_dir(None, "", repo_root=REPO_ROOT, environ={})
    assert got.source == "default"
    assert got.path == (REPO_ROOT / "realData" / "danish-server-room-v5" / "raw").resolve()
    assert "research" not in got.path.relative_to(REPO_ROOT.resolve()).parts


def test_raw_dir_precedence_cli_env_config_default(tmp_path):
    env = {paths.ENV_RAW_DIR: str(tmp_path / "from_env")}
    assert resolve_raw_dir(str(tmp_path / "cli"), "cfg", repo_root=REPO_ROOT, environ=env).source == "cli"
    assert resolve_raw_dir(None, "cfg", repo_root=REPO_ROOT, environ=env).source == "env"
    assert resolve_raw_dir(None, "cfg", repo_root=REPO_ROOT, environ={}).source == "config"
    assert resolve_raw_dir(None, "", repo_root=REPO_ROOT, environ={}).source == "default"


def test_relative_values_are_taken_relative_to_the_repo_root_not_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_against_root("a/b", REPO_ROOT) == (REPO_ROOT / "a" / "b").resolve()


def test_absolute_values_are_kept(tmp_path):
    assert resolve_against_root(str(tmp_path), REPO_ROOT) == tmp_path.resolve()


def test_output_outside_the_repo_is_allowed(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    assert ensure_output_dir_safe(tmp_path / "out", raw, REPO_ROOT) == (tmp_path / "out").resolve()


def test_default_output_location_is_allowed():
    raw = REPO_ROOT / "realData" / "danish-server-room-v5" / "raw"
    ensure_output_dir_safe(REPO_ROOT / "research" / "danish_aau" / "outputs" / "run1", raw, REPO_ROOT)


@pytest.mark.parametrize(
    "part", ["src", "api", "models", "data", "tests", "reports", "realData", "twin-stream-insight-main"]
)
def test_output_under_production_roots_is_refused(part, tmp_path):
    with pytest.raises(UnsafeOutputPath):
        ensure_output_dir_safe(REPO_ROOT / part / "x", tmp_path / "raw", REPO_ROOT)


def test_output_inside_raw_dir_is_refused(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    with pytest.raises(UnsafeOutputPath):
        ensure_output_dir_safe(raw / "derived", raw, REPO_ROOT)
    with pytest.raises(UnsafeOutputPath):
        ensure_output_dir_safe(raw, raw, REPO_ROOT)


def test_output_that_contains_the_raw_dir_is_refused(tmp_path):
    raw = tmp_path / "a" / "raw"
    raw.mkdir(parents=True)
    with pytest.raises(UnsafeOutputPath):
        ensure_output_dir_safe(tmp_path / "a", raw, REPO_ROOT)


def test_output_equal_to_repo_root_is_refused(tmp_path):
    with pytest.raises(UnsafeOutputPath):
        ensure_output_dir_safe(REPO_ROOT, tmp_path / "raw", REPO_ROOT)
