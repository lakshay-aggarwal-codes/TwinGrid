"""Test bootstrap for the evaluation harness.

The repository root is derived from THIS FILE's location (never from the current directory), so the tests behave
the same whether pytest is started from the repo root, from research/, or from this folder -- the failure mode of the
earlier audit tests (paths resolving to research/research/...).

Run from the repository root:   python -m pytest research/danish_aau/tests/evaluation -p no:cacheprovider
These tests use SYNTHETIC fixtures only; they do not need, read or modify the real realData folder.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import synthetic_fixtures as fx  # noqa: E402


@pytest.fixture
def raw_dir(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    return d


@pytest.fixture
def fixture_registry(raw_dir):
    """Four small synthetic files with the registered names; the returned registry matches them exactly."""
    return fx.make_dataset(raw_dir)


@pytest.fixture
def fixture_config(tmp_path, raw_dir, fixture_registry):
    return fx.write_config(tmp_path / "fixture.toml", raw_dir)


@pytest.fixture
def declared_config(tmp_path, raw_dir, fixture_registry):
    return fx.write_config(tmp_path / "declared.toml", raw_dir, declared=True)
