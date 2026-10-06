"""T20 -- one SafetyEnvelope, one carbon function, a reachable operating band, configurable step.

Complements tests/test_physics_v1_invariants.py (the 14 specified invariants) with: full-band reachability by a
constant policy, the per-version action range, the envelope version gate, SIM_STEP_SECONDS in env and live loop.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest import mock

import numpy as np
import pytest

from src import versions
from src.digital_twin import (
    CHILLED_WATER_APPROACH_C,
    SAFETY_ENVELOPE,
    CoolingMode,
    DigitalTwin,
    carbon_emissions_gco2,
)
from src.optimizer import (
    CHILLED_WATER_ACTION_RANGE_C,
    DEFAULT_SIM_STEP_SECONDS,
    DataCentreEnv,
    JointOptimizer,
)
from src.versions import LEGACY_PHYSICS_VERSION, PHYSICS_V1

FLAT = np.full(24, 475.0)
START = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture(autouse=True)
def flat_carbon():
    with mock.patch("src.digital_twin.load_diurnal_carbon_intensity", return_value=(FLAT, False)):
        yield


def _steady(cw: float, u: float = 0.5, t: float = 25.0):
    twin = DigitalTwin(
        physics_version=PHYSICS_V1, start_time=START, thermal_time_constant_min=0.01, initial_chilled_water_temp_C=cw
    )
    s = twin.step(
        {"utilisation": u, "outside_temp_C": t, "cooling_mode": CoolingMode.CLOSED_LOOP, "chilled_water_temp_C": cw}
    )
    return twin, s


# --------------------------------------------------------------------------- reachability (physics v1, constant policy)
def test_full_inlet_band_is_attainable_by_a_constant_policy():
    """Every inlet value in [inlet_min, inlet_max] is produced by some constant setpoint inside the v1 action range."""
    lo, hi = CHILLED_WATER_ACTION_RANGE_C[PHYSICS_V1]
    inlets = []
    for cw in np.linspace(lo, hi, 91):
        _, s = _steady(float(cw))
        inlets.append(s.server_inlet_temp_C)
    assert min(inlets) == pytest.approx(SAFETY_ENVELOPE.inlet_min_C, abs=1e-6)
    assert max(inlets) == pytest.approx(SAFETY_ENVELOPE.inlet_max_C, abs=1e-6)
    assert all(b >= a - 1e-9 for a, b in zip(inlets, inlets[1:]))  # monotone: the band is swept without gaps
    assert max(np.diff(inlets)) < 0.2  # step between neighbouring setpoints stays small (no jump over the band)
    for target in np.linspace(SAFETY_ENVELOPE.inlet_min_C, SAFETY_ENVELOPE.inlet_max_C, 10):
        assert min(abs(i - target) for i in inlets) < 0.1, target


def test_legacy_range_cannot_reach_the_upper_half_of_the_band_under_v1():
    """Documents why the v1 range is not 5-15: the old range tops out at the floor of the band."""
    lo, hi = CHILLED_WATER_ACTION_RANGE_C[LEGACY_PHYSICS_VERSION]
    top = max(_steady(float(cw))[1].server_inlet_temp_C for cw in np.linspace(lo, hi, 21))
    assert top < SAFETY_ENVELOPE.inlet_min_C + 1e-6


def test_v1_action_range_is_derived_from_the_envelope_not_a_free_constant():
    assert CHILLED_WATER_ACTION_RANGE_C[PHYSICS_V1] == (
        SAFETY_ENVELOPE.inlet_min_C - CHILLED_WATER_APPROACH_C,
        SAFETY_ENVELOPE.inlet_max_C - CHILLED_WATER_APPROACH_C,
    )
    assert CHILLED_WATER_ACTION_RANGE_C[LEGACY_PHYSICS_VERSION] == (5.0, 15.0)


def test_env_action_extremes_hit_the_band_edges_under_v1():
    env = DataCentreEnv(seed=0, carbon_intensity_by_hour=FLAT, physics_version=PHYSICS_V1)
    assert env._action_to_control(np.array([0.0, 0.0]))[0] == pytest.approx(16.0)
    assert env._action_to_control(np.array([1.0, 0.0]))[0] == pytest.approx(25.0)


# --------------------------------------------------------------------------- one envelope
def test_violations_of_uses_the_envelope_and_legacy_is_outlet_only():
    ok = {"inlet_temp": 22.0, "outlet_temp": 40.0, "pue": 1.4}
    assert DataCentreEnv.safety_violations_of(ok) == ()
    bad = {"inlet_temp": 15.0, "outlet_temp": 50.0, "pue": 2.5}
    assert DataCentreEnv.safety_violations_of(bad) == SAFETY_ENVELOPE.violations(15.0, 50.0, 2.5)
    assert DataCentreEnv.safety_violations_of(bad, legacy=True) == ("outlet_above_max",)
    assert DataCentreEnv.safety_violations_of({**ok, "outlet_temp": float("nan")}, legacy=True) == ("outlet_above_max",)
    assert DataCentreEnv.safety_violations_of({**ok, "pue": float("nan")}) == ("pue_above_max",)


def test_count_violations_matches_the_envelope_row_by_row_including_nan():
    import pandas as pd

    rng = np.random.default_rng(1)
    df = pd.DataFrame(
        {
            "inlet_temp": rng.uniform(10, 35, 300),
            "outlet_temp": rng.uniform(30, 55, 300),
            "pue": rng.uniform(1.0, 2.6, 300),
        }
    )
    df.loc[3, "inlet_temp"] = float("nan")
    df.loc[4, "outlet_temp"] = float("nan")
    df.loc[5, "pue"] = float("nan")
    expected = sum(not SAFETY_ENVELOPE.is_safe(r.inlet_temp, r.outlet_temp, r.pue) for r in df.itertuples())
    assert JointOptimizer._count_safety_violations(df, legacy=False) == expected
    assert JointOptimizer._count_safety_violations(df, legacy=True) == int((~(df["outlet_temp"] <= 45.0)).sum())


def test_penalty_is_flat_minus_two_and_only_for_envelope_breaches_v1():
    """Reward gap == 2.0 exactly (J is unchanged by the penalty); the same state under legacy-0 pays nothing."""

    def reward(version, **state):
        env = DataCentreEnv(seed=0, carbon_intensity_by_hour=FLAT, physics_version=version)
        env.reset(seed=0)
        base = {
            "hour": 12.0, "utilisation": 0.5, "outside_temp": 25.0, "inlet_temp": 22.0, "outlet_temp": 35.0,
            "it_power": 350.0, "cooling_power": 100.0, "water_consumed": 0.0, "pue": 1.3, "wue": 0.0,
            "carbon_intensity_gco2_per_kwh": 475.0, "carbon_gco2": 0.0, "water_stress": 0.0,
            "drought_override_active": False,
        }  # fmt: skip
        base.update(state)
        env._step_physics = lambda c, m: dict(base)
        return env.step(np.array([0.5, 0.5], dtype=np.float32))[1]

    assert reward(PHYSICS_V1, inlet_temp=30.0) == pytest.approx(reward(PHYSICS_V1) - 2.0)
    assert reward(PHYSICS_V1, pue=2.4) == pytest.approx(reward(PHYSICS_V1, pue=1.3) - 2.0 - 0.3 * (1.1 / 1.5))
    assert reward(LEGACY_PHYSICS_VERSION, inlet_temp=30.0) == pytest.approx(reward(LEGACY_PHYSICS_VERSION))


# --------------------------------------------------------------------------- one carbon function
def test_env_carbon_is_the_api_function_on_total_power_for_any_step():
    for step_s in (60.0, 300.0, 900.0):
        env = DataCentreEnv(seed=1, carbon_intensity_by_hour=FLAT, physics_version=PHYSICS_V1, sim_step_seconds=step_s)
        env.reset(seed=1)
        st = env.step(np.array([0.5, 0.5], dtype=np.float32))[4]["state"]
        assert st["carbon_gco2"] == pytest.approx(
            carbon_emissions_gco2(
                st["it_power"] + st["cooling_power"], st["carbon_intensity_gco2_per_kwh"], step_s / 3600.0
            ),
            rel=1e-12,
        )


def test_carbon_normaliser_is_a_ceiling_on_the_envelope_for_every_hour():
    curve = np.linspace(100.0, 700.0, 24)
    env = DataCentreEnv(seed=3, carbon_intensity_by_hour=curve, physics_version=PHYSICS_V1)
    assert env._carbon_norm_max == pytest.approx(500.0 * SAFETY_ENVELOPE.pue_max * 700.0 * 300.0 / 3600.0)
    env.reset(seed=3)
    for _ in range(60):
        st = env.step(np.array([0.9, 1.0], dtype=np.float32))[4]["state"]
        assert st["carbon_gco2"] <= env._carbon_norm_max


# --------------------------------------------------------------------------- configurable step
def test_default_step_is_300_seconds_and_legacy_refuses_any_other():
    assert DEFAULT_SIM_STEP_SECONDS == 300
    DataCentreEnv(seed=0, carbon_intensity_by_hour=FLAT, physics_version=LEGACY_PHYSICS_VERSION, sim_step_seconds=300)
    with pytest.raises(ValueError):
        DataCentreEnv(
            seed=0, carbon_intensity_by_hour=FLAT, physics_version=LEGACY_PHYSICS_VERSION, sim_step_seconds=60
        )


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_env_rejects_a_bad_step(bad):
    with pytest.raises(ValueError):
        DataCentreEnv(seed=0, carbon_intensity_by_hour=FLAT, physics_version=PHYSICS_V1, sim_step_seconds=bad)


def test_env_step_length_drives_the_twin_clock_and_energy():
    def run(step_s):
        env = DataCentreEnv(seed=5, carbon_intensity_by_hour=FLAT, physics_version=PHYSICS_V1, sim_step_seconds=step_s)
        env.reset(seed=5)
        t0 = env._twin._time
        env.step(np.array([0.5, 0.5], dtype=np.float32))
        return (env._twin._time - t0).total_seconds()

    assert run(150.0) == 150.0 and run(600.0) == 600.0


def test_live_broadcast_uses_sim_step_seconds(monkeypatch):
    import asyncio

    import api.services.live_broadcast_service as lbs
    from tests.characterization import golden_support as gs

    seen = {}
    twin = DigitalTwin(physics_version=PHYSICS_V1, start_time=START)
    real_step = twin.step

    def spy(action, **kw):
        seen.update(kw)
        return real_step(action, **kw)

    monkeypatch.setattr(twin, "step", spy)
    monkeypatch.setattr(lbs, "get_twin", lambda: twin)
    monkeypatch.setenv("SIM_STEP_SECONDS", "120")

    async def go():
        with gs.live_tick_environment():
            return await lbs._tick()

    payload = asyncio.run(go())
    assert seen.get("dt_seconds") == 120.0
    assert payload["sim_time_scale"] == pytest.approx(120.0 / lbs.BROADCAST_INTERVAL_SECONDS)


# --------------------------------------------------------------------------- envelope version gate
def test_current_envelope_version_is_bumped_past_the_unversioned_original():
    assert versions.SAFETY_ENVELOPE_VERSION == "2"


@pytest.mark.parametrize("recorded", [None, "", "1", 1, "0", "3"])
def test_older_missing_or_foreign_envelope_versions_are_rejected(recorded):
    with pytest.raises(versions.SafetyEnvelopeVersionError):
        versions.assert_current_safety_envelope_version(recorded)
    assert issubclass(versions.SafetyEnvelopeVersionError, ValueError)


def test_current_version_is_accepted():
    assert versions.assert_current_safety_envelope_version(versions.SAFETY_ENVELOPE_VERSION) == "2"


def _write_artifact(path, **config):
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps({"alpha": 0.5, "beta": 0.3, "gamma": 0.2, **config}))
    (path / "ppo_model.zip").write_bytes(b"not a real model")


@pytest.mark.parametrize("config", [{}, {"safety_envelope_version": "1"}])
def test_joint_optimizer_load_rejects_an_artifact_without_the_current_envelope_version(tmp_path, config):
    _write_artifact(tmp_path / "old", **config)
    with pytest.raises(versions.SafetyEnvelopeVersionError):
        JointOptimizer.load(tmp_path / "old")  # rejected BEFORE the model file is even opened


def test_joint_optimizer_save_records_physics_step_and_envelope_version(tmp_path):
    class _Model:
        def save(self, p):
            (tmp_path / "ppo_model.zip").write_bytes(b"x")

    opt = JointOptimizer(seed=0, carbon_intensity_by_hour=FLAT, physics_version=PHYSICS_V1, sim_step_seconds=150)
    opt._model = _Model()
    opt.save(tmp_path)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["safety_envelope_version"] == versions.SAFETY_ENVELOPE_VERSION
    assert cfg["physics_version"] == PHYSICS_V1 and cfg["sim_step_seconds"] == 150
    versions.assert_current_safety_envelope_version(cfg["safety_envelope_version"])


# --------------------------------------------------------------------------- legacy-0 is untouched
def test_legacy_env_keeps_its_frozen_semantics():
    env = DataCentreEnv(seed=0, carbon_intensity_by_hour=FLAT, physics_version=LEGACY_PHYSICS_VERSION)
    env.reset(seed=0)
    st = env.step(np.array([0.5, 0.5], dtype=np.float32))[4]["state"]
    assert env._carbon_norm_max == pytest.approx(150.0 * 475.0 * 5 / 60)
    assert st["carbon_gco2"] == pytest.approx(st["cooling_power"] * 475.0 * 5 / 60)  # cooling-only, as frozen
