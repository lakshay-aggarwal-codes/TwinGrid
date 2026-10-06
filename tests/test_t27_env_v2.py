"""T27 -- environment v2: shield, action/observation semantics, schema hashes, artifact gate, SB3 buffer content.

The SB3 rollout-buffer test imports stable-baselines3 at module level ON PURPOSE: it is a required test, never
skipped. If SB3/torch are missing this module fails to import (a CI failure), it does not silently pass.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest import mock

import gymnasium as gym
import numpy as np
import pytest
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv

from src import versions
from src.optimizer import (
    ACTION_SCHEMA,
    CHILLED_WATER_ACTION_RANGE_C,
    DataCentreEnv,
    JointOptimizer,
    action_schema_hash,
    assert_env_contract,
    env_contract,
    observation_schema,
    observation_schema_hash,
)
from src.rl import env as env_mod
from src.rl import safety_filter as sf
from src.rl.safety_filter import DROUGHT_OVERRIDE_MODE, DROUGHT_THRESHOLD, shield
from src.versions import LEGACY_PHYSICS_VERSION, PHYSICS_V1, EnvContractError

ROOT = Path(__file__).resolve().parent.parent
FLAT = np.full(24, 475.0)


def make_env(**kw) -> DataCentreEnv:
    kw.setdefault("carbon_intensity_by_hour", FLAT)
    kw.setdefault("physics_version", PHYSICS_V1)
    kw.setdefault("seed", 0)
    return DataCentreEnv(**kw)


# --------------------------------------------------------------------------- shield: pure, versioned, deterministic
def test_shield_is_pure_and_does_not_mutate_its_inputs():
    state = {"water_stress_scenario": 0.9, "extra": object()}
    a = np.array([0.3, 0.0], dtype=np.float32)
    a_before, state_before = a.copy(), dict(state)
    out1, f1 = shield(state, a)
    out2, f2 = shield(state, a)
    assert np.array_equal(a, a_before) and state == state_before  # inputs untouched
    assert np.array_equal(out1, out2) and f1 == f2  # same inputs, same outputs
    out1[0] = 99.0
    assert shield(state, a)[0][0] == pytest.approx(0.3)  # result is a fresh array, no shared state


def test_shield_module_has_no_environment_or_twin_dependency_and_no_mutable_globals():
    tree = ast.parse((ROOT / "src" / "rl" / "safety_filter.py").read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and ("digital_twin" in m or m.endswith("env") or "optimizer" in m) for m in imported)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "shield")
    assert not any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(fn))


def test_shield_is_versioned():
    assert sf.SHIELD_VERSION == versions.SHIELD_VERSION == "1"
    assert versions.CURRENT_ENV_VERSIONS["shield_version"] == "1"


@pytest.mark.parametrize("scenario, expect_override", [(0.0, False), (0.7, False), (0.7000001, True), (1.0, True)])
def test_drought_rule_boundary_is_strictly_greater_than(scenario, expect_override):
    a_x, flags = shield({"water_stress_scenario": scenario}, [0.5, 1.0])  # agent asks for mode 3 (hybrid)
    assert flags.drought_triggered is expect_override and flags.mode_overridden is expect_override
    assert sf.COOLING_MODES[sf.mode_index_of(a_x[1])] == (DROUGHT_OVERRIDE_MODE if expect_override else "hybrid")
    assert a_x[0] == pytest.approx(0.5)  # setpoint never touched by the drought rule


def test_drought_rule_fails_closed_on_a_missing_or_non_finite_scenario():
    for bad in (float("nan"), float("inf"), None, "x"):
        _, flags = shield({"water_stress_scenario": bad}, [0.5, 1.0])
        assert flags.drought_triggered is True
    with pytest.raises(KeyError):  # the key is mandatory: no silent default
        shield({}, [0.5, 1.0])


def test_shield_sanitises_and_snaps():
    out, flags = shield({"water_stress_scenario": 0.0}, [1.7, -0.4])
    assert np.array_equal(out, np.array([1.0, 0.0], dtype=np.float32)) and flags.clipped and flags.active
    out, flags = shield({"water_stress_scenario": 0.0}, [float("nan"), float("inf")])
    assert flags.non_finite_replaced and np.all(np.isfinite(out)) and 0.0 <= out.min() and out.max() <= 1.0
    out, flags = shield({"water_stress_scenario": 0.0}, [0.4, 0.4])  # mode 0.4 -> index 1 -> snapped to 1/3
    assert out[1] == pytest.approx(1 / 3, abs=1e-6) and not flags.active
    for bad in ([0.5], [0.1, 0.2, 0.3], np.zeros((2, 2))):
        with pytest.raises(ValueError):
            shield({"water_stress_scenario": 0.0}, bad)


def test_shield_is_idempotent_and_never_leaves_the_box():
    rng = np.random.default_rng(0)
    for _ in range(300):
        a = rng.uniform(-2, 3, size=2)
        s = {"water_stress_scenario": float(rng.uniform(0, 1))}
        once, _ = shield(s, a)
        twice, f2 = shield(s, once)
        assert np.array_equal(once, twice) and not f2.clipped and not f2.non_finite_replaced
        assert 0.0 <= once.min() and once.max() <= 1.0 and once.dtype == np.float32


# --------------------------------------------------------------------------- environment applies the shield
def test_env_reports_executed_action_shield_and_applied_actuator_in_info():
    env = make_env(water_stress=0.9)
    env.reset(seed=1)
    a_e = np.array([0.8, 1.0], dtype=np.float32)
    obs, r, term, trunc, info = env.step(a_e)
    expect, flags = shield({"water_stress_scenario": 0.9}, a_e)
    assert np.array_equal(info["executed_action"], expect)  # executed action recoverable from info
    assert np.array_equal(info["env_action"], a_e)
    assert info["shield_active"] is True and info["shield_flags"] == flags.as_dict()
    lo, hi = CHILLED_WATER_ACTION_RANGE_C[PHYSICS_V1]
    assert info["requested_setpoint_C"] == pytest.approx(lo + 0.8 * (hi - lo), abs=1e-5)
    assert info["requested_mode"] == DROUGHT_OVERRIDE_MODE
    assert info["applied_mode"] == env._twin._state.cooling_mode.value
    assert info["applied_setpoint_C"] == pytest.approx(env._twin._applied_chilled_water_temp_C)
    assert info["env_version"] == versions.ENV_VERSION == "2"
    assert "state" in info


def test_executed_action_decodes_to_exactly_what_the_plant_was_asked():
    env = make_env(water_stress=0.0)
    env.reset(seed=2)
    for a in ([0.1, 0.0], [0.9, 0.34], [0.5, 1.0], [0.0, 0.67]):
        _, _, _, _, info = env.step(np.array(a, dtype=np.float32))
        c, m = env._action_to_control(info["executed_action"])
        assert c == pytest.approx(info["requested_setpoint_C"]) and m == info["requested_mode"]


def test_action_decoding_no_longer_contains_the_drought_rule():
    env = make_env(water_stress=0.95)
    env.reset()
    _, mode = env._action_to_control(np.array([0.5, 1.0], dtype=np.float32))
    assert mode == "hybrid"  # decoding is pure; the override happens in the shield, inside step()


def test_drought_rule_is_triggered_by_the_scenario_variable_only():
    tree = ast.parse((ROOT / "src" / "rl" / "env.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "shield"]
    assert len(calls) == 1
    src = ast.unparse(calls[0])
    assert "water_stress_scenario" in src and "self._water_stress" in src and "baseline" not in src.lower()


def test_env_builds_its_twin_with_an_explicit_physics_version():
    tree = ast.parse((ROOT / "src" / "rl" / "env.py").read_text())
    twins = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "DigitalTwin"]
    assert twins and all(any(k.arg == "physics_version" for k in c.keywords) for c in twins)
    for pv in (PHYSICS_V1, LEGACY_PHYSICS_VERSION):
        env = make_env(physics_version=pv)
        env.reset()
        assert env._twin.physics_version == pv == env.physics_version


def test_env_is_deterministic_from_equal_state_and_seed():
    def run():
        env = make_env(water_stress=0.3)
        obs, _ = env.reset(seed=7)
        rows = [obs]
        rng = np.random.default_rng(11)
        for _ in range(40):
            o, r, *_rest, info = env.step(rng.uniform(0, 1, 2).astype(np.float32))
            rows.append(np.concatenate([o, [r], info["executed_action"]]))
        return np.concatenate([np.ravel(x) for x in rows])

    assert np.array_equal(run(), run())


# --------------------------------------------------------------------------- observation semantics
def test_observation_schema_is_ordered_named_and_bounded():
    names = [n for n, _, _ in observation_schema(PHYSICS_V1)]
    assert names[:9] == [
        "hour",
        "utilisation",
        "outside_temp",
        "inlet_temp",
        "outlet_temp",
        "it_power",
        "wue",
        "pue",
        "water_stress_scenario",
    ]
    assert names[9:] == [
        "applied_chilled_water_C",
        "applied_mode_free_air",
        "applied_mode_closed_loop",
        "applied_mode_evaporative",
        "applied_mode_hybrid",
        "prev_executed_setpoint_norm",
        "prev_executed_mode_norm",
        "room_thermal_C",
    ]
    assert len(names) == len(set(names)) == 17
    assert [n for n, _, _ in observation_schema(LEGACY_PHYSICS_VERSION)] == names[:9]  # legacy-0: frozen 9
    assert all(lo < hi for _, lo, hi in observation_schema(PHYSICS_V1))


def test_observation_contains_actuator_state_and_previous_executed_action():
    env = make_env(water_stress=0.0)
    obs, info = env.reset(seed=3)
    names = env.observation_names
    ix = {n: i for i, n in enumerate(names)}
    lo, hi = env_mod.APPLIED_SETPOINT_OBS_RANGE_C
    seen_applied = set()
    for a in ([0.0, 0.0], [1.0, 1.0], [1.0, 1.0], [0.5, 0.67], [0.5, 0.67]):
        obs, _, _, _, info = env.step(np.array(a, dtype=np.float32))
        applied = env._twin._applied_chilled_water_temp_C
        seen_applied.add(round(applied, 6))
        assert obs[ix["applied_chilled_water_C"]] == pytest.approx((applied - lo) / (hi - lo), abs=1e-6)
        mode = env._twin._state.cooling_mode.value
        hot = {m: obs[ix[f"applied_mode_{m}"]] for m in sf.COOLING_MODES}
        assert hot[mode] == 1.0 and sum(hot.values()) == 1.0  # one-hot of the APPLIED mode
        assert obs[ix["prev_executed_setpoint_norm"]] == pytest.approx(info["executed_action"][0])
        assert obs[ix["prev_executed_mode_norm"]] == pytest.approx(info["executed_action"][1])
        assert obs[ix["room_thermal_C"]] == pytest.approx(
            np.clip((info["room_thermal_C"] - 5) / (35 - 5), 0, 1), abs=1e-6
        )
    assert len(seen_applied) > 2  # the applied setpoint is a real state (rate-limited), not a copy of the request


def test_applied_setpoint_lags_the_request_and_the_policy_can_see_it():
    env = make_env(water_stress=0.0)
    env.reset(seed=4)
    _, _, _, _, info = env.step(np.array([1.0, 0.34], dtype=np.float32))  # ask for the top of the range at once
    assert (
        info["applied_setpoint_C"] < info["requested_setpoint_C"] or info["requested_setpoint_C"] - 10.0 <= 2.0 + 1e-9
    )


def test_reset_info_and_first_observation_are_consistent():
    env = make_env()
    obs, info = env.reset(seed=5)
    assert obs.shape == (17,) and info["shield_active"] is False and info["env_action"] is None
    assert info["requested_mode"] == "closed_loop" and info["requested_setpoint_C"] == 10.0
    ix = {n: i for i, n in enumerate(env.observation_names)}
    assert obs[ix["applied_mode_closed_loop"]] == 1.0


def test_observations_stay_in_the_declared_box_for_wild_actions():
    env = make_env(water_stress=0.8)
    env.reset(seed=6)
    rng = np.random.default_rng(1)
    for _ in range(150):
        o, *_ = env.step(rng.uniform(-3, 4, 2).astype(np.float32))
        assert o.shape == env.observation_space.shape and np.all((o >= 0) & (o <= 1)) and np.all(np.isfinite(o))


# --------------------------------------------------------------------------- hashes and versions
def test_schema_hashes_are_stable_and_sensitive():
    assert observation_schema_hash(PHYSICS_V1) == observation_schema_hash(PHYSICS_V1)
    assert observation_schema_hash(PHYSICS_V1) != observation_schema_hash(LEGACY_PHYSICS_VERSION)
    assert action_schema_hash() == env_mod._schema_hash(ACTION_SCHEMA)
    changed = tuple((n, lo, hi + 1.0 if n == "pue" else hi) for n, lo, hi in env_mod._BASE_OBS_SCHEMA)
    assert env_mod._schema_hash(changed) != env_mod._schema_hash(env_mod._BASE_OBS_SCHEMA)  # ranges are hashed
    renamed = (("x",) + env_mod._BASE_OBS_SCHEMA[0][1:],) + env_mod._BASE_OBS_SCHEMA[1:]
    assert env_mod._schema_hash(renamed) != env_mod._schema_hash(env_mod._BASE_OBS_SCHEMA)  # names are hashed
    swapped = (env_mod._BASE_OBS_SCHEMA[1], env_mod._BASE_OBS_SCHEMA[0]) + env_mod._BASE_OBS_SCHEMA[2:]
    assert env_mod._schema_hash(swapped) != env_mod._schema_hash(env_mod._BASE_OBS_SCHEMA)  # order is hashed
    assert [n for n, _, _ in ACTION_SCHEMA] == ["chilled_water_setpoint_norm", "cooling_mode_norm"]


def test_versions_recorded():
    c = env_contract(PHYSICS_V1)
    assert (c["env_version"], c["action_semantics_version"], c["reward_version"], c["shield_version"]) == (
        "2",
        "2",
        "2",
        "1",
    )
    assert c["safety_envelope_version"] == versions.SAFETY_ENVELOPE_VERSION and c["physics_version"] == PHYSICS_V1
    assert (
        c["observation_schema_hash"] == observation_schema_hash(PHYSICS_V1)
        and c["action_schema_hash"] == action_schema_hash()
    )
    assert make_env().env_contract == c


def test_optimizer_import_shim_exposes_the_moved_names():
    import src.optimizer as shim

    assert shim.DataCentreEnv is env_mod.DataCentreEnv and shim.shield is sf.shield
    assert shim.COOLING_MODES is sf.COOLING_MODES and shim.DROUGHT_THRESHOLD == sf.DROUGHT_THRESHOLD == 0.7
    for name in (
        "OBS_RANGES",
        "_normalise",
        "_denormalise",
        "EPISODE_STEPS",
        "INTERVAL_MIN",
        "OUTLET_MAX",
        "MAX_IT_POWER_KW",
        "DROUGHT_OVERRIDE_MODE",
    ):
        assert hasattr(shim, name), name


# --------------------------------------------------------------------------- gate: every pre-v2 artifact is rejected
def _write_artifact(path: Path, **config):
    path.mkdir(parents=True, exist_ok=True)
    base = {"alpha": 0.5, "beta": 0.3, "gamma": 0.2, "safety_envelope_version": versions.SAFETY_ENVELOPE_VERSION}
    (path / "config.json").write_text(json.dumps({**base, **config}))
    (path / "ppo_model.zip").write_bytes(b"not a model")  # must be rejected BEFORE it is opened


def test_gate_rejects_an_artifact_with_no_env_contract(tmp_path):
    _write_artifact(tmp_path / "pre_v2")
    with pytest.raises(EnvContractError, match="predates environment v2"):
        JointOptimizer.load(tmp_path / "pre_v2")


def test_gate_rejects_the_checked_in_artifact_config():
    cfg = json.loads((ROOT / "models" / "optimizer" / "config.json").read_text())
    with pytest.raises(EnvContractError):
        assert_env_contract(cfg.get("env_contract"), cfg.get("physics_version"))


@pytest.mark.parametrize(
    "mutate",
    [
        {"env_version": "1"},
        {"action_semantics_version": "1"},
        {"reward_version": "1"},
        {"shield_version": "0"},
        {"safety_envelope_version": "1"},
        {"env_version": None},
        {"observation_schema_hash": "0" * 64},
        {"action_schema_hash": "f" * 64},
    ],
)
def test_gate_rejects_any_single_wrong_field(mutate):
    good = env_contract(PHYSICS_V1)
    assert assert_env_contract(good) == good
    with pytest.raises(EnvContractError):
        assert_env_contract({**good, **mutate})


def test_gate_rejects_missing_keys_and_wrong_types():
    good = env_contract(PHYSICS_V1)
    for k in good:
        if k == "physics_version":
            continue
        with pytest.raises(EnvContractError):
            assert_env_contract({kk: v for kk, v in good.items() if kk != k})
    for bad in (None, "2", ["2"], 2):
        with pytest.raises(EnvContractError):
            assert_env_contract(bad)


def test_gate_rejects_a_contract_for_the_other_physics_schema():
    legacy = env_contract(LEGACY_PHYSICS_VERSION)
    with pytest.raises(EnvContractError):
        assert_env_contract({**legacy, "physics_version": PHYSICS_V1})  # legacy hashes under v1 physics


def test_save_records_the_contract_and_load_accepts_only_that(tmp_path):
    class _M:
        def save(self, p):
            (tmp_path / "ppo_model.zip").write_bytes(b"x")

    opt = JointOptimizer(seed=0, carbon_intensity_by_hour=FLAT, physics_version=PHYSICS_V1)
    opt._model = _M()
    opt.save(tmp_path)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["env_contract"] == env_contract(PHYSICS_V1)
    assert_env_contract(cfg["env_contract"], cfg["physics_version"])
    cfg["env_contract"]["observation_schema_hash"] = "0" * 64
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    with pytest.raises(EnvContractError):
        JointOptimizer.load(tmp_path)


# --------------------------------------------------------------------------- SB3 rollout buffer (required, never skipped)
class _Recorder(gym.Wrapper):
    """Records what the environment received and reported at every step (outside the env, so no trust in it)."""

    def __init__(self, env):
        super().__init__(env)
        self.received: list[np.ndarray] = []
        self.infos: list[dict] = []

    def step(self, action):
        self.received.append(np.array(action, dtype=np.float32))
        out = self.env.step(action)
        self.infos.append(out[4])
        return out


def _out_of_range_samples(n: int) -> np.ndarray:
    rng = np.random.default_rng(123)
    a = rng.uniform(-1.0, 2.0, size=(n, 2)).astype(np.float32)
    a[0] = [1.7, -0.4]  # pin some definitely-outside samples
    a[1] = [-0.9, 2.5]
    a[2] = [0.5, 0.5]
    return a


@pytest.mark.parametrize("scenario", [0.0, 0.9])
def test_sb3_rollout_buffer_stores_the_sampled_action_not_the_clipped_or_executed_one(scenario):
    """64 steps with a stub policy that emits out-of-range SAMPLES a_s. Finding to be recorded in the evidence:
    SB3 passes clip(a_s, 0, 1) to the Box env (a_e) and stores the UNCLIPPED a_s in the rollout buffer."""
    n = 64
    samples = _out_of_range_samples(n)
    assert (samples < 0).any() and (samples > 1).any()

    recorder = _Recorder(make_env(water_stress=scenario, max_steps=10_000, seed=0))
    venv = DummyVecEnv([lambda: recorder])
    model = PPO("MlpPolicy", venv, n_steps=n, batch_size=n, n_epochs=1, seed=0, device="cpu")

    calls = {"i": 0}

    def stub_forward(obs, deterministic=False):  # replaces policy.forward: (actions, values, log_prob)
        a = torch.as_tensor(samples[calls["i"]]).reshape(1, 2)
        calls["i"] += 1
        return a, torch.zeros(1), torch.zeros(1)

    with mock.patch.object(model.policy, "forward", stub_forward):
        model.learn(total_timesteps=n)

    stored = model.rollout_buffer.actions.reshape(n, 2)
    received = np.stack(recorder.received)
    executed = np.stack([i["executed_action"] for i in recorder.infos])

    # 1. the buffer holds the raw sample a_s (log-prob refers to it), including out-of-range values
    assert np.array_equal(stored, samples)
    assert stored.min() < 0.0 and stored.max() > 1.0
    # 2. the env received a_e = clip(a_s, 0, 1)
    assert np.array_equal(received, np.clip(samples, 0.0, 1.0))
    assert not np.array_equal(stored, received)
    # 3. the shield ran inside the env: executed action recoverable from info, equals shield(state, a_e)
    expect = np.stack([shield({"water_stress_scenario": scenario}, a)[0] for a in received])
    assert np.array_equal(executed, expect)
    assert np.all((executed >= 0) & (executed <= 1))
    if scenario > DROUGHT_THRESHOLD:  # drought: every executed mode is the override, whatever the policy sampled
        assert {sf.COOLING_MODES[sf.mode_index_of(m)] for m in executed[:, 1]} == {DROUGHT_OVERRIDE_MODE}
        assert all(i["shield_active"] for i in recorder.infos)
    # 4. the buffer is NOT the executed action
    assert not np.array_equal(stored, executed)
    # 5. the observations the policy saw have the v2 width
    assert model.rollout_buffer.observations.shape == (n, 17)  # flattened (n_steps * n_envs, obs_dim) after the update
    # 6. log-prob/value were not altered by the shield (they are whatever the policy emitted)
    assert np.all(model.rollout_buffer.log_probs.reshape(-1)[:1] == 0.0)
