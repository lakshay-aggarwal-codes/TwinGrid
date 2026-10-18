"""Task 3: the recommended degrees C are the degrees C the evaluation executed (physics-aware), not legacy-0's 5..15 C.

Hermetic: every config is a tmp copy of the shipped one, edited here. Nothing under configs/ or reports/ is touched.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src import baseline_recommendation as br
from src import optimizer_proposals as rules
from src.baselines import config as bc
from src.baselines import policies as bp
from src.optimizer import DataCentreEnv
from src.versions import LEGACY_PHYSICS_VERSION, PHYSICS_V1, active_physics_version

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configs(tmp_path):
    shutil.copytree(ROOT / "configs" / "baselines", tmp_path / "configs" / "baselines")
    return tmp_path


def _edit(root: Path, name: str, fn) -> None:
    path = root / "configs" / "baselines" / f"{name}.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    fn(cfg)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def _rec(root, **kw):
    args = {"outside_temp": 22.0, "water_stress": 0.0, "current_chilled_c": 20.0, "inlet_temp_c": None}
    return br.recommend(root, **{**args, **kw})


def _only(root: Path, keep: str) -> None:
    for name in ("pid", "rule"):
        if name != keep:
            _edit(root, name, lambda c: c.update(status="infeasible", infeasible_reason="x"))


def _env_executed_c(cfg: dict, physics: str, state: dict) -> float:
    env = DataCentreEnv(physics_version=physics, seed=0, max_steps=4)
    policy = bc.build_policy(cfg)
    return env._action_to_control(policy.act(None, state))[0]


# ----------------------------------------------------------------------------- the defect (failed before the fix)


@pytest.mark.skipif(active_physics_version() != PHYSICS_V1, reason="the shipped configs are tuned under physics 1")
@pytest.mark.parametrize("name", ["rule", "pid"])
def test_recommended_celsius_is_what_the_environment_executes_under_physics_1(configs, name):
    _only(configs, name)
    sel = _rec(configs)["selected"]
    cfg = bc.load_config(bc.config_path(name, configs), name)
    state = {"outside_temp": 22.0, "water_stress": 0.0, "inlet_temp": 22.0}  # PID: inlet == target -> nominal
    assert sel["name"] == name
    assert sel["chilled_water_temp_C"] == pytest.approx(_env_executed_c(cfg, PHYSICS_V1, state), abs=1e-3)
    lo, hi = bp.actuator_range_C(PHYSICS_V1)
    assert lo <= sel["chilled_water_temp_C"] <= hi
    assert sel["physics_version"] == PHYSICS_V1 and sel["actuator_range_C"] == [lo, hi]


@pytest.mark.skipif(active_physics_version() != PHYSICS_V1, reason="the shipped configs are tuned under physics 1")
def test_the_old_legacy_scale_conversion_disagreed_with_the_environment_by_over_ten_degrees(configs):
    """The pre-fix result for the shipped rule config (legacy formula) vs what the evaluation executed."""
    _only(configs, "rule")
    cfg = bc.load_config(bc.config_path("rule", configs), "rule")
    old_reported = bp.CHILLED_MIN_C + float(
        bc.build_policy(cfg).act(None, {"outside_temp": 22.0, "water_stress": 0.0})[0]
    ) * (bp.CHILLED_MAX_C - bp.CHILLED_MIN_C)
    executed = _env_executed_c(cfg, PHYSICS_V1, {"outside_temp": 22.0, "water_stress": 0.0})
    assert old_reported == pytest.approx(12.0, abs=1e-3) and executed == pytest.approx(22.3, abs=1e-3)
    assert _rec(configs)["selected"]["chilled_water_temp_C"] == pytest.approx(executed, abs=1e-3)


# ----------------------------------------------------------------------------- legacy-0 is unchanged


def test_legacy_0_recommendation_is_the_stored_celsius(configs, monkeypatch):
    monkeypatch.setenv("PHYSICS_VERSION", LEGACY_PHYSICS_VERSION)
    running = bc.running_lineage()
    for name in ("pid", "rule"):
        _edit(configs, name, lambda c: c["lineage"].update(running))
    _only(configs, "rule")
    sel = _rec(configs, current_chilled_c=10.0)["selected"]
    assert sel["chilled_water_temp_C"] == pytest.approx(12.0, abs=1e-3)  # identity: stored C == reported C
    assert sel["physics_version"] == LEGACY_PHYSICS_VERSION and sel["actuator_range_C"] == [5.0, 15.0]
    assert "converted" not in sel["basis"]


# ----------------------------------------------------------------------------- a physics-aware policy is the identity


def test_a_config_whose_policy_is_physics_1_reports_its_own_celsius(configs, monkeypatch):
    if active_physics_version() != PHYSICS_V1:
        pytest.skip("needs physics 1 as the running physics")
    _only(configs, "rule")
    monkeypatch.setattr(bc, "build_policy", lambda cfg: bp.RulePolicy(20.0, physics_version=PHYSICS_V1))
    sel = _rec(configs)["selected"]
    assert sel["chilled_water_temp_C"] == pytest.approx(20.0, abs=1e-3)
    assert "converted" not in sel["basis"]


def test_a_config_the_policy_cannot_hold_is_skipped_not_a_server_error(configs, monkeypatch):
    _only(configs, "rule")

    def refuse(cfg):
        raise ValueError("rule set-point 22.75 C is outside the actuator range 5..15 C")

    monkeypatch.setattr(bc, "build_policy", refuse)
    rec = _rec(configs)
    assert rec["selected"] is None
    assert "outside the actuator range" in next(c for c in rec["considered"] if c["name"] == "rule")["reason"]


# ----------------------------------------------------------------------------- PID: the current set-point is a real C


@pytest.mark.skipif(active_physics_version() != PHYSICS_V1, reason="the shipped configs are tuned under physics 1")
def test_pid_step_starts_from_the_current_celsius_on_the_executed_scale(configs):
    _only(configs, "pid")
    _edit(configs, "pid", lambda c: c["parameters"].update(selected_gains={"kp": 1.0, "ki": 0.0, "kd": 0.0}))
    # current 22 C = 0.667 of 16..25; the legacy-scale PID holds that as 11.667; error +1 -> 13.0 -> 0.8 -> 23.2 C
    sel = _rec(configs, current_chilled_c=22.0, inlet_temp_c=21.0)["selected"]
    assert sel["chilled_water_temp_C"] == pytest.approx(23.2, abs=1e-3)
    assert "one PID step" in sel["basis"] and "clipped" not in sel["basis"] and "converted" in sel["basis"]


@pytest.mark.skipif(active_physics_version() != PHYSICS_V1, reason="the shipped configs are tuned under physics 1")
def test_a_current_setpoint_outside_the_actuator_range_is_clipped_and_says_so(configs):
    _only(configs, "pid")
    sel = _rec(configs, current_chilled_c=7.0, inlet_temp_c=21.0)["selected"]  # 7 C: the API's own default
    lo, hi = bp.actuator_range_C(PHYSICS_V1)
    assert "clipped" in sel["basis"] and lo <= sel["chilled_water_temp_C"] <= hi


@pytest.mark.skipif(active_physics_version() != PHYSICS_V1, reason="the shipped configs are tuned under physics 1")
@pytest.mark.parametrize("name", ["rule", "pid"])
def test_the_recommendation_never_leaves_the_actuator_range(configs, name):
    _only(configs, name)
    lo, hi = bp.actuator_range_C(PHYSICS_V1)
    for current in (0.0, 5.0, 16.0, 20.0, 25.0, 40.0):
        for inlet in (None, 10.0, 22.0, 40.0):
            sel = _rec(configs, current_chilled_c=current, inlet_temp_c=inlet)["selected"]
            assert lo - 1e-6 <= sel["chilled_water_temp_C"] <= hi + 1e-6


# ----------------------------------------------------------------------------- proposal rules


def test_accepted_range_is_a_superset_of_the_registry_bounds_and_the_actuator_range():
    assert rules.accepted_chilled_range_C((5.0, 15.0), LEGACY_PHYSICS_VERSION) == (5.0, 15.0)  # nothing changes
    assert rules.accepted_chilled_range_C((5.0, 15.0), PHYSICS_V1) == (5.0, 25.0)
    assert (rules.CHILLED_MIN_C, rules.CHILLED_MAX_C) == (5.0, 15.0)  # legacy constants stay for compatibility


def test_setpoint_check_flags_values_outside_the_evaluated_range():
    chk = rules.setpoint_check(20.0, 7.0, PHYSICS_V1)
    assert chk == {
        "physics_version": PHYSICS_V1,
        "actuator_range_C": [16.0, 25.0],
        "proposed_within_actuator_range": True,
        "reference_within_actuator_range": False,
    }
    assert rules.setpoint_check(12.0, 12.0, LEGACY_PHYSICS_VERSION)["proposed_within_actuator_range"] is True
