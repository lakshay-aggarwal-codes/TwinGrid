"""TG-A-13: the baselines must command the temperature they say, under EACH physics version.

Before this fix ``policies.py`` normalised every set-point with the legacy 5..15 C range, while the physics-1
environment maps actions onto 16..25 C, so a baseline labelled "12 C" really commanded 22.3 C.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.baselines import policies as bp
from src.optimizer import COOLING_MODES, DataCentreEnv, UnsupportedPhysicsVersionForRL
from src.rl.env import CHILLED_WATER_ACTION_RANGE_C

VERSIONS = ("legacy-0", "1")


def _legacy_formula(celsius: float) -> float:
    """The pre-fix normalisation, copied here so legacy-0 byte-compatibility is tested against it."""
    return float(np.clip((celsius - 5.0) / (15.0 - 5.0), 0.0, 1.0))


def _env(version: str) -> DataCentreEnv:
    return DataCentreEnv(physics_version=version, seed=0, max_steps=4)


def test_ranges_are_read_from_the_environment_not_copied():
    for v in VERSIONS:
        assert bp.actuator_range_C(v) == CHILLED_WATER_ACTION_RANGE_C[v]
    assert bp.actuator_range_C("legacy-0") == (bp.CHILLED_MIN_C, bp.CHILLED_MAX_C)
    assert bp.actuator_range_C("1") == (16.0, 25.0)  # documents the numbers the audit found
    with pytest.raises(UnsupportedPhysicsVersionForRL):
        bp.actuator_range_C("2")


@pytest.mark.parametrize("version", VERSIONS)
def test_make_action_round_trips_through_the_environment(version):
    env = _env(version)
    lo, hi = bp.actuator_range_C(version)
    for c in np.linspace(lo, hi, 9):
        for mode in COOLING_MODES:
            chilled, got_mode = env._action_to_control(bp.make_action(float(c), mode, version))
            assert chilled == pytest.approx(float(c), abs=1e-5) and got_mode == mode


def test_the_audit_defect_cannot_recur():
    """A 'legacy-range' action fed to the physics-1 env is NOT 12 C; a physics-1 action is."""
    env = _env("1")
    assert env._action_to_control(bp.make_action(12.0, "hybrid"))[0] != pytest.approx(12.0)  # the old bug, for contrast
    assert env._action_to_control(bp.make_action(22.0, "hybrid", "1"))[0] == pytest.approx(22.0, abs=1e-5)


def test_legacy_actions_are_identical_to_the_pre_fix_formula():
    for c in np.linspace(5.0, 15.0, 41):
        assert bp.norm_chilled(float(c)) == _legacy_formula(float(c))
        for mode in COOLING_MODES:
            a = bp.make_action(float(c), mode)
            assert a.dtype == np.float32 and a[0] == np.float32(_legacy_formula(float(c)))
    assert bp.RulePolicy().act(None, {"outside_temp": 20.0, "water_stress": 0.0})[0] == np.float32(
        _legacy_formula(12.0)
    )


@pytest.mark.parametrize("version", VERSIONS)
def test_out_of_range_set_points_are_refused_not_clipped(version):
    lo, hi = bp.actuator_range_C(version)
    for bad in (lo - 0.5, hi + 0.5):
        with pytest.raises(ValueError, match="actuator range"):
            bp.ConstantPolicy(bad, "hybrid", physics_version=version)
        with pytest.raises(ValueError, match="actuator range"):
            bp.RulePolicy(bad, physics_version=version)
    with pytest.raises(ValueError, match="outside the actuator limits"):
        bp.LookupPolicy(
            [0.5],
            [10.0],
            [[(bad, "hybrid"), (lo, "hybrid")], [(lo, "hybrid"), (lo, "hybrid")]],
            physics_version=version,
        )


def test_a_legacy_constant_is_refused_under_physics_1():
    """The legacy protocol's 5..15 C grid must not silently run on physics 1 (Task 2 gives physics 1 its own grid)."""
    with pytest.raises(ValueError, match="actuator range"):
        bp.ConstantPolicy(5.0, "free_air", physics_version="1")


def test_rule_default_setpoint_is_physics_specific():
    assert bp.default_rule_setpoint_C("legacy-0") == 12.0
    assert bp.default_rule_setpoint_C("1") == pytest.approx(20.5)  # middle of 16..25
    lo, hi = bp.actuator_range_C("1")
    assert lo <= bp.default_rule_setpoint_C("1") <= hi
    env = _env("1")
    chilled = env._action_to_control(
        bp.RulePolicy(physics_version="1").act(None, {"outside_temp": 20.0, "water_stress": 0.0})
    )[0]
    assert chilled == pytest.approx(20.5, abs=1e-5)


@pytest.mark.parametrize("version", VERSIONS)
def test_pid_output_stays_in_the_physics_range_and_obeys_the_rate_limit(version):
    pid = bp.PIDPolicy.for_physics(version, target_inlet_C=22.0, kp=2.0, ki=0.1, kd=0.2)
    lo, hi = bp.actuator_range_C(version)
    assert (pid.min_setpoint_C, pid.max_setpoint_C) == (lo, hi)
    prev = pid.output
    for inlet in [10.0, 40.0, 40.0, 5.0, 35.0, 22.0, 60.0] * 6:
        out = pid.setpoint(inlet)
        assert lo <= out <= hi
        assert abs(out - prev) <= pid.max_rate_C_per_step + 1e-12
        prev = out


def test_pid_defaults_are_legacy_and_refuse_a_wrong_physics_range():
    legacy = bp.PIDPolicy(target_inlet_C=22.0, kp=1.0, ki=0.0, kd=0.0)
    assert (legacy.min_setpoint_C, legacy.max_setpoint_C, legacy.physics_version) == (5.0, 15.0, "legacy-0")
    with pytest.raises(ValueError, match="actuator range"):
        bp.PIDPolicy(target_inlet_C=22.0, kp=1.0, ki=0.0, kd=0.0, physics_version="1")  # legacy limits on physics 1


@pytest.mark.parametrize("version", VERSIONS)
def test_every_policy_emits_valid_actions_inside_the_environment(version):
    """End to end: run each policy for a few steps in the matching env; the executed set-point equals the intended one."""
    lo, hi = bp.actuator_range_C(version)
    mid = (lo + hi) / 2
    policies = [
        bp.ConstantPolicy(mid, "hybrid", physics_version=version),
        bp.RulePolicy(physics_version=version),
        bp.LookupPolicy(
            [0.5],
            [15.0],
            [[(lo, "hybrid"), (mid, "hybrid")], [(mid, "hybrid"), (hi, "hybrid")]],
            physics_version=version,
        ),
        bp.PIDPolicy.for_physics(version, 22.0, 1.0, 0.05, 0.1),
    ]
    for pol in policies:
        env = _env(version)
        obs, info = env.reset(seed=3)
        pol.reset()
        state = info.get("state", {}) if isinstance(info, dict) else {}
        for _ in range(3):
            action = pol.act(obs, state)
            assert action.shape == (2,) and 0.0 <= float(action[0]) <= 1.0
            chilled, _mode = env._action_to_control(action)
            assert lo - 1e-6 <= chilled <= hi + 1e-6
            obs, _r, term, trunc, info = env.step(action)
            state = info["state"]
            if term or trunc:
                break


# ------------------------------------------------------------------------------------------------ Task 2
def test_constant_grid_is_physics_specific_and_the_legacy_grid_is_unchanged():
    from src import policy_evaluation as pe

    assert pe.constant_grid_c("legacy-0") == (5.0, 7.5, 10.0, 12.5, 15.0)  # the frozen protocol's grid, exactly
    assert pe.constant_grid_c("1") == (16.0, 18.25, 20.5, 22.75, 25.0)
    for v in VERSIONS:
        lo, hi = bp.actuator_range_C(v)
        grid = pe.constant_grid_c(v)
        assert grid[0] == lo and grid[-1] == hi and list(grid) == sorted(grid)


def test_the_frozen_legacy_protocol_hash_is_unchanged():
    """Task 2 touched EvalConfig defaults; the committed registration must still hash to what it recorded."""
    from pathlib import Path

    from src import policy_evaluation as pe

    root = Path(__file__).resolve().parents[1] / "reports" / "policy_evaluation"
    registered = json.loads((root / "PREREGISTRATION.json").read_text())
    cfg = pe.load_preregistered_config(root)
    assert pe.config_sha256(cfg) == registered["preregistration_sha256"]
    assert cfg.physics_version == "legacy-0 (implicit)" and cfg.resolved_physics_version == "legacy-0"
    assert cfg.constant_chilled_C == (5.0, 7.5, 10.0, 12.5, 15.0) and cfg.rule_chilled_C == 12.0


def test_default_protocol_is_physics_1_with_in_range_setpoints():
    from src import policy_evaluation as pe

    cfg = pe.EvalConfig()
    assert cfg.resolved_physics_version == "1"
    lo, hi = bp.actuator_range_C("1")
    assert all(lo <= c <= hi for c in (*cfg.constant_chilled_C, cfg.rule_chilled_C))


def test_a_protocol_with_set_points_outside_its_physics_range_is_refused_at_construction():
    from dataclasses import replace

    from src import policy_evaluation as pe

    with pytest.raises(ValueError, match="registered per physics"):
        replace(pe.EvalConfig(), constant_chilled_C=(5.0, 15.0))  # legacy grid on physics 1
    with pytest.raises(ValueError, match="registered per physics"):
        replace(pe.EvalConfig(), physics_version="legacy-0")  # physics-1 grid on legacy-0


def test_tuning_runs_in_the_physics_range_and_records_it():
    from dataclasses import replace

    from src import policy_evaluation as pe
    from src.baselines import tuning

    cfg = replace(pe.EvalConfig(), n_validation_per_family=1, n_test_per_family=1, episode_steps=12)
    space = tuning.default_space(cfg)
    assert space.rule_chilled_C == 20.5 and space.pid_nominal_setpoint_C == 20.5
    assert all(16.0 <= c <= 25.0 for c in space.constant_chilled_C + space.lookup_chilled_C)
    assert space.lookup_transient_steps_excluded == 8  # ceil(max(|10-16|, |25-10|) / 2 C per step)
    legacy = replace(cfg, physics_version="legacy-0", constant_chilled_C=(5.0, 15.0), rule_chilled_C=12.0)
    assert tuning.default_space(legacy).lookup_transient_steps_excluded == 3  # unchanged for legacy-0
    assert tuning.default_space(legacy).pid_nominal_setpoint_C == 12.0
    assert tuning.TUNER_VERSION == "baselines-tuner/2"


def test_a_config_without_the_recorded_actuator_range_is_stale():
    """Configs tuned before this fix (tuner /1) used the legacy normalisation under every physics."""
    from src.baselines import config as bcfg

    lineage = bcfg.running_lineage()
    cfg = {"lineage": dict(lineage), "tuning": {}}
    with pytest.raises(bcfg.BaselineConfigStale) as exc:
        bcfg.check_lineage(cfg)
    assert exc.value.field == "tuning.actuator_range_C"
    cfg["tuning"]["actuator_range_C"] = list(bp.actuator_range_C(lineage["physics_version"]))
    bcfg.check_lineage(cfg)  # now current


def test_a_built_policy_uses_the_physics_of_its_config():
    from src.baselines import config as bcfg

    cfg = {
        "name": "constant",
        "parameters": {"selected": {"chilled_C": 22.75, "mode": "hybrid"}},
        "lineage": {"physics_version": "1"},
    }
    pol = bcfg.build_policy(cfg)
    assert pol.physics_version == "1"
    chilled, _ = _env("1")._action_to_control(pol.act(None, {}))
    assert chilled == pytest.approx(22.75, abs=1e-5)
    cfg["lineage"]["physics_version"] = "legacy-0"
    with pytest.raises(ValueError, match="actuator range"):
        bcfg.build_policy(cfg)  # 22.75 C does not exist under legacy-0
