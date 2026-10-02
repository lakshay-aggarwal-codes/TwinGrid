"""legacy-0 must stay bit-identical to the pre-T7 behaviour.

The goldens in legacy_0_goldens.json were generated from the UNMODIFIED
pre-T7 snapshot (see its "meta" block). If one of these fails, legacy-0 changed:
either fix the regression, or -- only if replay of old results no longer matters
-- retire legacy-0 deliberately (roadmap decision 6), do not just regenerate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tests.golden import scenarios

GOLDEN = json.loads((Path(__file__).with_name("legacy_0_goldens.json")).read_text())
REL = 1e-9


def assert_close(actual, expected, path="$"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert actual.keys() == expected.keys(), f"{path}: keys differ: {set(actual) ^ set(expected)}"
        for k in expected:
            assert_close(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f"{path}: length {len(actual)} != {len(expected)}"
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_close(a, e, f"{path}[{i}]")
    elif isinstance(expected, float):
        assert math.isclose(actual, expected, rel_tol=REL, abs_tol=1e-12), f"{path}: {actual!r} != {expected!r}"
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def test_golden_metadata_records_provenance():
    meta = GOLDEN["meta"]
    assert meta["physics_version"] == "legacy-0"
    assert set(meta["sha256"]) >= {"src/digital_twin.py", "api/services/twin_service.py"}
    assert meta["commit"].startswith("unknown")


def test_grid_states():
    with scenarios.legacy_env():
        actual = scenarios.grid_states()
    assert len(actual) == 180
    assert_close(actual, GOLDEN["grid_states"], "grid_states")


def test_live_sequence_accumulators():
    with scenarios.legacy_env():
        actual = scenarios.live_sequence()
    assert_close(actual, GOLDEN["live_sequence"], "live_sequence")


def test_compute_whatif():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PHYSICS_VERSION", "legacy-0")
        actual = scenarios.whatif_cases()
    assert_close(actual, GOLDEN["whatif"], "whatif")


def test_optimizer_environment_rollout():
    with scenarios.legacy_env():
        actual = scenarios.env_rollout()
    assert_close(actual, GOLDEN["env_rollout"], "env_rollout")


def test_a_one_percent_change_to_a_water_constant_is_detected(monkeypatch):
    """Mutation demonstration: the goldens are sensitive enough to notice a 1% drift."""
    import src.digital_twin as dt

    monkeypatch.setattr(dt, "WATER_FLOW_SCALE_LPM_PER_KW", dt.WATER_FLOW_SCALE_LPM_PER_KW * 1.01)
    with scenarios.legacy_env():
        actual = scenarios.grid_states()
    with pytest.raises(AssertionError):
        assert_close(actual, GOLDEN["grid_states"], "grid_states")
