"""Physics v2 (T21): dynamic lumped-capacitance model, frozen PhysicsParams.

Sections map to the roadmap tests: per-step energy closure, steady state equals v1, step-response monotonicity,
actuator rate limit, determinism, and the v1 invariants carried over. v2 is UNCALIBRATED; nothing here claims
agreement with any facility, only internal consistency and consistency with v1.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import math
import random
from datetime import datetime
from unittest import mock

import numpy as np
import pytest

import src.digital_twin as dt_mod
from src.digital_twin import (
    AIR_DENSITY_KG_M3,
    COOLING_CAPACITY_MARGIN,
    LATENT_WATER_BOUND_L_PER_KWH,
    SAFETY_ENVELOPE,
    SPECIFIC_HEAT_AIR_J_KG_K,
    CoolingMode,
    DigitalTwin,
    InvalidInputError,
    carbon_emissions_gco2,
)
from src.physics import v2
from src.physics.params import DEFAULT_PHYSICS_PARAMS, PhysicsParams, PhysicsParamsError
from src.versions import (
    KNOWN_PHYSICS_VERSIONS,
    PHYSICS_V1,
    PHYSICS_V2,
    PhysicsVersionError,
    active_physics_version,
    assert_same_physics_identity,
    physics_identity,
)

START = datetime(2025, 6, 1, 3, 0, 0)
FLAT = np.full(24, 475.0)
MODES = list(CoolingMode)
UTILS = (0.0, 0.1, 0.5, 0.9, 1.0)
TEMPS = (-20.0, -5.0, 10.0, 25.0, 40.0)
EXPECTED_DEFAULT_PARAMS_HASH = "d2d7b2c000ed54b623c6e18d7fd180cac47c0518a16de274ac5bcc7607de1b68"
CLOSURE_TOL_KJ = 1e-6  # roadmap: per-step energy closure <= 1e-6
STEADY_REL_TOL = 1e-6  # stated tolerance of the v2-vs-v1 steady-state comparison (relative, +1e-9 absolute)


@pytest.fixture(autouse=True)
def flat_carbon():
    with mock.patch("src.digital_twin.load_diurnal_carbon_intensity", return_value=(FLAT, False)):
        yield


def twin2(**kw) -> DigitalTwin:
    return DigitalTwin(physics_version=PHYSICS_V2, start_time=START, **kw)


def twin1(**kw) -> DigitalTwin:
    return DigitalTwin(physics_version=PHYSICS_V1, start_time=START, thermal_time_constant_min=0.01, **kw)


def act(u=0.5, t=25.0, mode=CoolingMode.CLOSED_LOOP, rh=50.0, cw=12.0) -> dict:
    return {"utilisation": u, "outside_temp_C": t, "cooling_mode": mode, "humidity_pct": rh, "chilled_water_temp_C": cw}


def inputs(u=0.5, t=25.0, mode="closed_loop", rh=50.0, cw=12.0) -> v2.StepInputs:
    return v2.StepInputs(utilisation=u, outside_temp_c=t, humidity_pct=rh, cooling_mode=mode, chw_requested_c=cw)


def run_v2(state, inp, n, dt=300.0, params=DEFAULT_PHYSICS_PARAMS):
    results = []
    for _ in range(n):
        r = v2.step(state, inp, dt, params)
        results.append(r)
        state = r.state
    return results


# =============================================================================== PhysicsParams
class TestPhysicsParams:
    def test_is_frozen_and_hashable(self):
        p = PhysicsParams()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.max_it_power_kw = 1.0  # type: ignore[misc]
        assert hash(p) == hash(PhysicsParams())
        assert {p: 1}[PhysicsParams()] == 1
        assert PhysicsParams() == PhysicsParams() and PhysicsParams(max_it_power_kw=600) != p

    def test_default_hash_is_pinned(self):
        """Changing ANY default changes the physics identity -- do it on purpose and update this constant."""
        assert PhysicsParams().params_hash() == EXPECTED_DEFAULT_PARAMS_HASH
        assert len(EXPECTED_DEFAULT_PARAMS_HASH) == 64

    def test_hash_does_not_depend_on_int_or_float_spelling(self):
        assert PhysicsParams(max_it_power_kw=500).params_hash() == PhysicsParams(max_it_power_kw=500.0).params_hash()

    @pytest.mark.parametrize("name", [f.name for f in dataclasses.fields(PhysicsParams)])
    def test_every_field_is_part_of_the_hash(self, name):
        base = PhysicsParams()
        value = getattr(base, name)
        new = (1.0 if value is None else value * 0.9) if name != "idle_power_fraction" else 0.35
        if name == "capacity_design_kw":
            new = 800.0
        elif value == 0.0:
            new = 0.05  # e.g. evap_fraction_free_air (0 * 0.9 would not change anything)
        changed = dataclasses.replace(base, **{name: new})
        assert changed.params_hash() != base.params_hash(), name

    @pytest.mark.parametrize(
        "kw",
        [
            {"max_it_power_kw": float("nan")},
            {"coil_ua_kw_per_k": float("inf")},
            {"thermal_capacitance_kj_per_k": 0.0},
            {"tau_air_min": -1.0},
            {"idle_power_fraction": 1.5},
            {"cop_min": 0.0},
            {"max_it_power_kw": "500"},
            {"max_it_power_kw": True},
            {"capacity_design_kw": -5.0},
            {"evap_fraction_hybrid": 1.5},
            {"air_flow_full_load_m3_s": 1.0},
            {"humidity_reference_pct": 120.0},
            {"chw_rate_limit_c_per_5min": -0.1},
        ],
    )
    def test_invalid_values_are_rejected(self, kw):
        with pytest.raises(PhysicsParamsError):
            PhysicsParams(**kw)

    def test_defaults_inherited_from_v1_match_the_v1_module_constants(self):
        """Steady-state equality with v1 depends on these; fail loudly if either side drifts."""
        p = DEFAULT_PHYSICS_PARAMS
        assert (p.cop_free_air, p.cop_closed_loop, p.cop_evaporative, p.cop_hybrid) == tuple(
            dt_mod._BASE_COP[m]
            for m in (CoolingMode.FREE_AIR, CoolingMode.CLOSED_LOOP, CoolingMode.EVAPORATIVE, CoolingMode.HYBRID)
        )
        for mode in MODES:
            assert p.evap_fraction(mode.value) == pytest.approx(dt_mod._EVAPORATIVE_HEAT_FRACTION[mode], rel=1e-15)
        assert p.cop_load_derate == dt_mod.COP_LOAD_DERATE
        assert p.cop_outside_derate_per_c == dt_mod.COP_OUTSIDE_TEMP_DERATE_PER_C
        assert p.cop_min == dt_mod.COP_MIN
        assert p.cop_chw_lift_per_c == dt_mod.COP_CHILLED_WATER_LIFT_DERATE_PER_C
        assert p.cop_chw_reference_c == dt_mod.DEFAULT_CHILLED_WATER_TEMP_C
        assert p.cop_humidity_reference_pct == dt_mod.EVAPORATIVE_HUMIDITY_REFERENCE_PCT
        assert p.cop_humidity_derate_per_pct == 0.5 * dt_mod.WATER_HUMIDITY_FACTOR_PER_PCT
        assert p.capacity_margin == COOLING_CAPACITY_MARGIN
        assert p.capacity_derate_start_c == dt_mod.CAPACITY_DERATE_START_OUTSIDE_C
        assert p.capacity_derate_per_c == dt_mod.CAPACITY_DERATE_PER_C
        assert p.capacity_min_fraction == dt_mod.CAPACITY_MIN_FRACTION
        assert p.latent_heat_j_per_kg == dt_mod.LATENT_HEAT_VAPORISATION_J_PER_KG
        assert p.water_warm_factor_per_c == dt_mod.WATER_TEMP_FACTOR_PER_C
        assert p.inlet_supply_floor_c == dt_mod.INLET_SUPPLY_FLOOR_C
        assert p.free_air_fan_heat_c == dt_mod.FREE_AIR_FAN_HEAT_C
        assert p.chw_approach_c == dt_mod.CHILLED_WATER_APPROACH_C
        assert p.free_air_ineffective_above_c == dt_mod.FREE_AIR_INEFFECTIVE_OUTSIDE_TEMP_C
        assert p.air_flow_full_load_m3_s == dt_mod.AIR_FLOW_FULL_LOAD_M3_S
        assert p.tau_air_min == dt_mod.DEFAULT_THERMAL_TIME_CONSTANT_MIN
        assert p.chw_rate_limit_c_per_5min == dt_mod.DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP
        assert v2.AIR_DENSITY_KG_M3 == AIR_DENSITY_KG_M3 and v2.SPECIFIC_HEAT_AIR_J_KG_K == SPECIFIC_HEAT_AIR_J_KG_K
        assert v2.JOULES_PER_KWH == dt_mod.JOULES_PER_KWH

    def test_json_encoding_is_canonical(self):
        text = PhysicsParams().canonical_json()
        assert json.loads(text)["params"]["max_it_power_kw"] == 500.0
        assert text == PhysicsParams().canonical_json() and " " not in text


# =============================================================================== version + identity
class TestVersionAndIdentity:
    def test_2_is_known_and_v1_stays_the_default(self, monkeypatch):
        assert PHYSICS_V2 in KNOWN_PHYSICS_VERSIONS
        monkeypatch.delenv("PHYSICS_VERSION", raising=False)
        assert active_physics_version() == PHYSICS_V1  # opt-in: nothing changes silently
        assert DigitalTwin(start_time=START).physics_version == PHYSICS_V1

    def test_environment_selects_v2_and_rollback_is_one_variable(self, monkeypatch):
        monkeypatch.setenv("PHYSICS_VERSION", "2")
        assert DigitalTwin(start_time=START).physics_version == "2"
        monkeypatch.setenv("PHYSICS_VERSION", "1")  # rollback
        assert DigitalTwin(start_time=START).physics_version == "1"

    def test_unknown_version_still_raises(self):
        with pytest.raises(PhysicsVersionError):
            DigitalTwin(physics_version="3")

    def test_identity_carries_the_params_hash_for_v2_only(self):
        t = twin2()
        assert t.physics_identity == {"physics_version": "2", "physics_params_hash": EXPECTED_DEFAULT_PARAMS_HASH}
        assert DigitalTwin(physics_version="1", start_time=START).physics_identity == {
            "physics_version": "1",
            "physics_params_hash": None,
        }

    def test_v2_identity_requires_params(self):
        with pytest.raises(PhysicsVersionError):
            physics_identity("2")
        with pytest.raises(PhysicsVersionError):
            physics_identity("1", DEFAULT_PHYSICS_PARAMS)

    def test_different_params_are_different_physics(self):
        a = twin2().physics_identity
        b = twin2(physics_params=PhysicsParams(coil_ua_kw_per_k=30.0)).physics_identity
        assert a["physics_params_hash"] != b["physics_params_hash"]
        assert assert_same_physics_identity(a, dict(a)) == a
        with pytest.raises(PhysicsVersionError, match="parameter"):
            assert_same_physics_identity(a, b)
        with pytest.raises(PhysicsVersionError):
            assert_same_physics_identity(a, {"physics_version": "1", "physics_params_hash": None})
        with pytest.raises(PhysicsVersionError):
            assert_same_physics_identity({"physics_version": "2", "physics_params_hash": None})
        with pytest.raises(PhysicsVersionError):
            assert_same_physics_identity(a, None)

    def test_physics_params_only_for_version_2(self):
        with pytest.raises(InvalidInputError):
            DigitalTwin(physics_version="1", physics_params=PhysicsParams(), start_time=START)
        with pytest.raises(InvalidInputError):
            DigitalTwin(physics_version="legacy-0", physics_params=PhysicsParams(), start_time=START)

    def test_legacy_arguments_map_onto_params_and_conflicts_are_refused(self):
        t = twin2(max_it_power_kw=800.0, idle_power_fraction=0.3, cooling_capacity_kw=900.0, air_flow_m3_s=10.0)
        p = t.physics_params
        assert (p.max_it_power_kw, p.idle_power_fraction, p.capacity_design_kw, p.air_flow_base_m3_s) == (
            800.0,
            0.3,
            900.0,
            10.0,
        )
        assert t.compute_it_power(1.0) == pytest.approx(800.0)
        with pytest.raises(InvalidInputError, match="conflicts"):
            twin2(physics_params=PhysicsParams(), max_it_power_kw=800.0)
        assert twin2(physics_params=PhysicsParams(max_it_power_kw=800.0)).compute_it_power(1.0) == pytest.approx(800.0)

    def test_v1_and_legacy_have_no_dynamic_state(self):
        assert DigitalTwin(physics_version="1", start_time=START).dynamic_state is None
        assert DigitalTwin(physics_version="legacy-0", start_time=START).dynamic_state is None
        assert DigitalTwin(physics_version="1", start_time=START).physics_params is None


# =============================================================================== 1. per-step energy closure
class TestEnergyClosure:
    @pytest.mark.parametrize(
        "mode,u,t", list(itertools.product(("free_air", "closed_loop", "evaporative", "hybrid"), UTILS, TEMPS))
    )
    def test_room_energy_balance_closes_every_step(self, mode, u, t):
        """C_th dT_room = (Q_it - Q_cool) dt, from a cold, a settled and an overloaded start."""
        for start_u in (0.0, 1.0):
            state = v2.initial_state(inputs(start_u, t, mode), DEFAULT_PHYSICS_PARAMS, 12.0)
            for r in run_v2(state, inputs(u, t, mode, cw=18.0), 12):
                assert abs(r.closure_residual_kj) <= CLOSURE_TOL_KJ
                assert r.q_cool_kw <= r.capacity_kw + 1e-9 and r.q_cool_kw >= 0.0
                assert r.q_stored_kw == pytest.approx(r.it_power_kw - r.q_cool_kw)

    @pytest.mark.parametrize("dt", [1.0, 30.0, 300.0, 900.0, 3600.0])
    def test_closure_for_any_allowed_step_length(self, dt):
        state = v2.initial_state(inputs(0.2, 25.0), DEFAULT_PHYSICS_PARAMS, 12.0)
        for r in run_v2(state, inputs(0.95, 25.0), 6, dt=dt):
            assert abs(r.closure_residual_kj) <= CLOSURE_TOL_KJ

    def test_closure_over_a_random_trajectory(self):
        rng = random.Random(1234)
        state = v2.initial_state(inputs(0.3, 20.0), DEFAULT_PHYSICS_PARAMS, 12.0)
        worst = 0.0
        for _ in range(500):
            inp = inputs(
                rng.random(),
                rng.uniform(-20, 45),
                rng.choice(["free_air", "closed_loop", "evaporative", "hybrid"]),
                rng.uniform(5, 95),
                rng.uniform(6, 24),
            )
            r = v2.step(state, inp, rng.choice([60.0, 300.0, 600.0]), DEFAULT_PHYSICS_PARAMS)
            worst = max(worst, abs(r.closure_residual_kj))
            state = r.state
        assert worst <= CLOSURE_TOL_KJ

    @pytest.mark.parametrize("mode,u,t", list(itertools.product(MODES, UTILS, TEMPS)))
    def test_facility_energy_total_is_it_plus_cooling(self, mode, u, t):
        tw = twin2()
        s = tw.step(act(u, t, mode))
        assert s.total_power_kw == pytest.approx(s.it_power_kw + s.cooling_power_kw, abs=1e-9)
        b = tw.last_balance
        assert b["heat_rejected_kw"] == pytest.approx(b["heat_removed_kw"] + b["cooling_electrical_kw"], abs=1e-9)
        assert b["heat_removed_kw"] + b["heat_unremoved_kw"] == pytest.approx(b["it_heat_kw"], abs=1e-9)
        assert abs(b["closure_residual_kj"]) <= CLOSURE_TOL_KJ

    def test_twin_reports_the_room_energy_change(self):
        tw = twin2()
        tw.step(act(0.2))
        t0 = tw.dynamic_state.t_room_c
        tw.step(act(0.9))
        b = tw.last_balance
        assert b["room_energy_change_kj"] == pytest.approx(
            tw.physics_params.thermal_capacitance_kj_per_k * (tw.dynamic_state.t_room_c - t0)
        )


# =============================================================================== 2. steady state equals v1
def settle_both(u, t, mode, cw, rh=50.0, cap=None):
    kw = {} if cap is None else {"cooling_capacity_kw": cap}
    a, b = twin1(**kw), twin2(**kw)
    for _ in range(12):
        s1 = a.step(act(u, t, mode, rh, cw))
    for _ in range(200):
        s2 = b.step(act(u, t, mode, rh, cw))
    return a, s1, b, s2


FIELDS = (
    "it_power_kw",
    "cooling_power_kw",
    "total_power_kw",
    "pue",
    "server_inlet_temp_C",
    "server_outlet_temp_C",
    "water_flow_lpm",
    "wue",
)


class TestSteadyStateMatchesV1:
    """Stated tolerance: relative 1e-6 (+1e-9 absolute) on every field, wherever BOTH versions can remove the load
    (v1 leaves no unremoved heat). Humidity is at the reference (50 %): see TestHumidity for other values."""

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("u", UTILS)
    @pytest.mark.parametrize("t", TEMPS)
    @pytest.mark.parametrize("cw", [8.0, 12.0, 16.0, 22.0])
    def test_every_economic_quantity_matches(self, mode, u, t, cw):
        a, s1, b, s2 = settle_both(u, t, mode, cw)
        assert a.last_balance["heat_unremoved_kw"] == 0.0  # grid is chosen inside both capacities
        assert s2.cooling_mode == s1.cooling_mode
        for f in FIELDS:
            assert getattr(s2, f) == pytest.approx(getattr(s1, f), rel=STEADY_REL_TOL, abs=1e-9), f
        assert b.dynamic_state.t_chw_applied_c == pytest.approx(cw)

    def test_the_comparison_is_not_vacuous(self):
        a, s1, b, s2 = settle_both(1.0, 25.0, CoolingMode.HYBRID, 12.0)
        assert s2.cooling_power_kw > 50.0 and s2.water_flow_lpm > 0.0 and s2.pue > 1.1

    def test_room_settles_where_the_coil_carries_the_load(self):
        _, _, b, s2 = settle_both(0.7, 25.0, CoolingMode.CLOSED_LOOP, 12.0)
        want = 12.0 + s2.it_power_kw / b.physics_params.coil_ua_kw_per_k
        assert b.dynamic_state.t_room_c == pytest.approx(want, rel=1e-9)

    def test_evaluating_at_other_capacities_still_matches_when_feasible(self):
        a, s1, b, s2 = settle_both(0.5, 25.0, CoolingMode.HYBRID, 12.0, cap=400.0)
        for f in FIELDS:
            assert getattr(s2, f) == pytest.approx(getattr(s1, f), rel=STEADY_REL_TOL, abs=1e-9), f

    def test_overload_is_the_documented_difference(self):
        """Above capacity v1 has a finite algebraic inlet offset; v2 integrates an ever-warming room."""
        a, s1, b, s2 = settle_both(1.0, 25.0, CoolingMode.HYBRID, 12.0, cap=300.0)
        assert a.last_balance["heat_unremoved_kw"] > 0.0
        assert b.last_balance["heat_removed_kw"] == pytest.approx(300.0)  # coil saturated at capacity
        t_before = b.dynamic_state.t_room_c
        b.step(act(1.0, 25.0, CoolingMode.HYBRID))
        assert b.dynamic_state.t_room_c > t_before  # no steady state
        assert s2.server_inlet_temp_C > SAFETY_ENVELOPE.inlet_max_C and not b.is_safe()


# =============================================================================== 3. step response
class TestStepResponse:
    def test_load_step_up_is_monotone_and_never_overshoots(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(0.2), p, 12.0)
        hi = inputs(0.9)
        final = v2.initial_state(hi, p, 12.0)
        rs = run_v2(s0, hi, 100)  # 0.75 ** 100 ~ 3e-13 of the initial gap
        rooms = [s0.t_room_c] + [r.state.t_room_c for r in rs]
        assert all(b >= a - 1e-12 for a, b in zip(rooms, rooms[1:]))
        assert max(rooms) <= final.t_room_c + 1e-9  # semi-implicit Euler: no overshoot
        assert rooms[-1] == pytest.approx(final.t_room_c, rel=1e-6)
        q = [r.q_cool_kw for r in rs]
        assert all(b >= a - 1e-12 for a, b in zip(q, q[1:]))
        assert q[0] < rs[0].it_power_kw  # the room stores heat first: removal lags the load
        cool = [r.cooling_electrical_kw for r in rs]
        assert cool[0] < cool[-1]

    def test_load_step_down_is_monotone(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(1.0), p, 12.0)
        rs = run_v2(s0, inputs(0.1), 40)
        rooms = [s0.t_room_c] + [r.state.t_room_c for r in rs]
        assert all(b <= a + 1e-12 for a, b in zip(rooms, rooms[1:]))
        assert min(rooms) >= v2.initial_state(inputs(0.1), p, 12.0).t_room_c - 1e-9
        assert rs[0].q_stored_kw < 0.0  # the room gives heat back

    def test_setpoint_step_is_monotone_in_room_and_actuator(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(0.6, cw=12.0), p, 12.0)
        rs = run_v2(s0, inputs(0.6, cw=22.0), 100)
        rooms = [s0.t_room_c] + [r.state.t_room_c for r in rs]
        chw = [s0.t_chw_applied_c] + [r.state.t_chw_applied_c for r in rs]
        assert all(b >= a - 1e-12 for a, b in zip(rooms, rooms[1:]))
        assert all(b >= a - 1e-12 for a, b in zip(chw, chw[1:])) and chw[-1] == pytest.approx(22.0)
        assert rooms[-1] == pytest.approx(22.0 + rs[-1].it_power_kw / p.coil_ua_kw_per_k, rel=1e-6)

    def test_air_path_lags_but_is_monotone(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(0.2, 25.0), p, 12.0)
        rs = run_v2(s0, inputs(1.0, 25.0), 30)
        outs = [s0.t_out_c] + [r.state.t_out_c for r in rs]
        assert all(b >= a - 1e-12 for a, b in zip(outs, outs[1:]))
        target = v2.initial_state(inputs(1.0, 25.0), p, 12.0).t_out_c
        assert outs[1] < target and outs[-1] == pytest.approx(target, rel=1e-6)

    def test_matches_the_exact_exponential_for_a_small_step(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(0.2), p, 12.0)
        hi = inputs(0.9)
        ss = v2.initial_state(hi, p, 12.0).t_room_c
        tau = p.room_time_constant_s
        horizon = 600.0
        exact = ss + (s0.t_room_c - ss) * math.exp(-horizon / tau)
        got = run_v2(s0, hi, 60, dt=10.0)[-1].state.t_room_c
        assert got == pytest.approx(exact, abs=0.02 * abs(exact - s0.t_room_c))

    def test_integrator_is_first_order(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(0.2), p, 12.0)
        hi = inputs(0.9)
        ss = v2.initial_state(hi, p, 12.0).t_room_c
        exact = ss + (s0.t_room_c - ss) * math.exp(-600.0 / p.room_time_constant_s)
        e_big = abs(run_v2(s0, hi, 10, dt=60.0)[-1].state.t_room_c - exact)
        e_small = abs(run_v2(s0, hi, 20, dt=30.0)[-1].state.t_room_c - exact)
        assert 1.7 < e_big / e_small < 2.3


# =============================================================================== 4. actuator rate limit
class TestActuator:
    @pytest.mark.parametrize("dt", [30.0, 300.0, 900.0])
    @pytest.mark.parametrize("target", [30.0, 0.0])
    def test_slew_rate_limit_is_never_exceeded(self, dt, target):
        p = DEFAULT_PHYSICS_PARAMS
        limit = p.chw_rate_limit_c_per_5min * dt / 300.0
        state = v2.initial_state(inputs(), p, 12.0)
        prev = state.t_chw_applied_c
        for r in run_v2(state, inputs(cw=target), int(6000 / dt), dt=dt):
            assert abs(r.state.t_chw_applied_c - prev) <= limit + 1e-12
            prev = r.state.t_chw_applied_c
        assert prev == pytest.approx(target, abs=1e-6)

    def test_limit_binds_for_a_big_jump_and_lag_binds_for_a_small_one(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(), p, 12.0)
        big = v2.step(s0, inputs(cw=30.0), 300.0, p).state.t_chw_applied_c
        assert big == pytest.approx(12.0 + 2.0)  # rate limit
        small = v2.step(s0, inputs(cw=12.5), 300.0, p).state.t_chw_applied_c
        alpha = 1.0 - math.exp(-300.0 / (p.tau_chw_min * 60.0))
        assert small == pytest.approx(12.0 + alpha * 0.5) and small < 12.5  # first-order lag

    def test_lag_is_first_order_without_overshoot(self):
        p = PhysicsParams(chw_rate_limit_c_per_5min=1000.0)  # lag only
        state = v2.initial_state(inputs(), p, 12.0)
        values = [r.state.t_chw_applied_c for r in run_v2(state, inputs(cw=20.0), 10, dt=60.0, params=p)]
        assert all(b >= a for a, b in zip(values, values[1:])) and max(values) <= 20.0
        assert values[0] == pytest.approx(12.0 + 8.0 * (1.0 - math.exp(-60.0 / 120.0)))

    def test_zero_rate_freezes_the_actuator(self):
        p = PhysicsParams(chw_rate_limit_c_per_5min=0.0)
        s = v2.initial_state(inputs(), p, 12.0)
        assert run_v2(s, inputs(cw=25.0), 5, params=p)[-1].state.t_chw_applied_c == 12.0

    def test_through_the_twin_the_applied_setpoint_is_the_state_that_physics_used(self):
        tw = twin2()
        tw.step(act(cw=30.0))
        assert tw.dynamic_state.t_chw_applied_c == pytest.approx(14.0)
        assert tw.dynamic_state.t_chw_applied_c <= 12.0 + 2.0 + 1e-12
        # inlet follows the APPLIED setpoint, not the request: supply = max(18, 14 + 2)
        assert tw.dynamic_state.t_in_c <= 18.0 + 1e-9


# =============================================================================== 5. determinism
class TestDeterminism:
    def test_equal_inputs_give_identical_results(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(0.4), p, 12.0)
        a = v2.step(s0, inputs(0.8, 31.0, "hybrid", 63.0, 15.0), 300.0, p)
        b = v2.step(s0, inputs(0.8, 31.0, "hybrid", 63.0, 15.0), 300.0, p)
        assert a == b

    def test_step_does_not_mutate_its_arguments(self):
        p = DEFAULT_PHYSICS_PARAMS
        s0 = v2.initial_state(inputs(0.4), p, 12.0)
        snapshot = dataclasses.astuple(s0)
        v2.step(s0, inputs(0.9), 300.0, p)
        assert dataclasses.astuple(s0) == snapshot

    def test_two_twins_with_the_same_inputs_stay_identical(self):
        a, b = twin2(), twin2()
        rng = random.Random(7)
        for _ in range(60):
            action = act(rng.random(), rng.uniform(-10, 40), rng.choice(MODES), rng.uniform(10, 90), rng.uniform(8, 20))
            assert a.step(action).to_dict() == b.step(action).to_dict()
            assert a.dynamic_state == b.dynamic_state

    def test_one_long_step_differs_from_many_short_steps_but_both_are_deterministic(self):
        a, b = twin2(), twin2()
        a.step(act(0.9), dt_seconds=600.0)
        for _ in range(2):
            b.step(act(0.9), dt_seconds=300.0)
        assert a.dynamic_state.t_room_c != b.dynamic_state.t_room_c  # first-order scheme: step size matters
        c = twin2()
        c.step(act(0.9), dt_seconds=600.0)
        assert c.dynamic_state == a.dynamic_state


# =============================================================================== humidity: an input, not a state
class TestHumidity:
    def test_there_is_no_humidity_state(self):
        names = {f.name for f in dataclasses.fields(v2.DynamicState)}
        assert names == {"t_room_c", "t_in_c", "t_out_c", "t_chw_applied_c", "mode_applied", "water_cum_l"}

    def test_wet_bulb_is_below_dry_bulb_and_physical(self):
        assert v2.wet_bulb_c(25.0, 50.0) == pytest.approx(17.99, abs=0.05)  # Stull: ~18.0
        assert v2.wet_bulb_c(30.0, 100.0) <= 30.0
        for t, rh in itertools.product((-20, 0, 15, 30, 45), (5, 30, 60, 99)):
            assert v2.wet_bulb_c(t, rh) <= t
        assert v2.wet_bulb_c(30.0, 20.0) < v2.wet_bulb_c(30.0, 80.0)

    def test_factor_is_one_at_the_reference_and_orders_by_dryness(self):
        p = DEFAULT_PHYSICS_PARAMS
        assert v2.wet_bulb_factor(30.0, p.humidity_reference_pct, p) == 1.0
        assert v2.wet_bulb_factor(30.0, 20.0, p) > 1.0 > v2.wet_bulb_factor(30.0, 85.0, p)
        assert p.wet_bulb_factor_min <= v2.wet_bulb_factor(30.0, 99.0, p) <= p.wet_bulb_factor_max

    def test_drier_air_evaporates_more_and_free_air_uses_none(self):
        def water(mode, rh):
            return twin2().step(act(0.8, 30.0, mode, rh)).water_flow_lpm

        # hybrid is below the latent-heat cap in this range, so the ordering is strict
        assert water(CoolingMode.HYBRID, 20.0) > water(CoolingMode.HYBRID, 50.0) > water(CoolingMode.HYBRID, 90.0)
        # evaporative saturates at the latent-heat bound for dry air (share capped at 1): non-increasing, then falls
        assert (
            water(CoolingMode.EVAPORATIVE, 20.0)
            >= water(CoolingMode.EVAPORATIVE, 30.0)
            > water(CoolingMode.EVAPORATIVE, 90.0)
        )
        assert (
            twin2().step(act(0.8, 5.0, CoolingMode.FREE_AIR, 20.0)).water_flow_lpm == 0.0
        )  # cold enough for real free air

    @pytest.mark.parametrize("rh", [5.0, 20.0, 50.0, 80.0, 100.0])
    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("t", [-5.0, 15.0, 30.0, 45.0])
    def test_water_never_exceeds_the_latent_heat_bound_at_any_humidity(self, mode, t, rh):
        tw = twin2()
        s = tw.step(act(1.0, t, mode, rh))
        b = tw.last_balance
        step_l = b["water_evaporated_L"]
        rejected_kwh = b["heat_rejected_kw"] * b["dt_s"] / 3600.0
        assert step_l <= LATENT_WATER_BOUND_L_PER_KWH * rejected_kwh * (1 + 1e-12)
        assert s.water_flow_lpm * (b["dt_s"] / 60.0) == pytest.approx(step_l)

    def test_non_water_quantities_do_not_depend_on_humidity_except_the_evaporative_cop(self):
        for mode in (CoolingMode.CLOSED_LOOP, CoolingMode.HYBRID, CoolingMode.FREE_AIR):
            a = twin2().step(act(0.7, 20.0, mode, 20.0))
            b = twin2().step(act(0.7, 20.0, mode, 90.0))
            assert a.cooling_power_kw == b.cooling_power_kw and a.server_inlet_temp_C == b.server_inlet_temp_C
        e1 = twin2().step(act(0.7, 20.0, CoolingMode.EVAPORATIVE, 30.0)).cooling_power_kw
        e2 = twin2().step(act(0.7, 20.0, CoolingMode.EVAPORATIVE, 90.0)).cooling_power_kw
        assert e2 > e1  # v1 behaviour, kept: humid air lowers the evaporative COP

    def test_humidity_moves_capacity_through_the_wet_bulb_only_when_derated(self):
        p = DEFAULT_PHYSICS_PARAMS
        ref = v2.capacity_kw("evaporative", 44.0, p.humidity_reference_pct, p)
        assert v2.capacity_kw("evaporative", 44.0, 15.0, p) > ref > v2.capacity_kw("evaporative", 44.0, 95.0, p)
        assert v2.capacity_kw("closed_loop", 44.0, 15.0, p) == pytest.approx(
            v2.capacity_kw("closed_loop", 44.0, 95.0, p), rel=0.01
        )
        assert v2.capacity_kw("evaporative", 25.0, 15.0, p) == p.design_capacity_kw  # below the derate knee
        assert v2.capacity_kw("hybrid", 44.0, p.humidity_reference_pct, p) == pytest.approx(
            p.design_capacity_kw * (1.0 - p.capacity_derate_per_c * (44.0 - 35.0))
        )


# =============================================================================== stability check
class TestStability:
    def test_default_step_and_ceiling_are_allowed(self):
        rep = v2.check_step_stability(DEFAULT_PHYSICS_PARAMS, 300.0)
        assert rep.tau_room_s == 900.0 and 0.0 < rep.room_amplification < 1.0
        assert v2.check_step_stability(DEFAULT_PHYSICS_PARAMS, 3600.0).max_dt_s == 3600.0

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), 3600.1, True, "300"])
    def test_disallowed_steps_raise(self, bad):
        with pytest.raises(v2.PhysicsStabilityError):
            v2.check_step_stability(DEFAULT_PHYSICS_PARAMS, bad)

    def test_the_bound_follows_the_room_time_constant(self):
        fast = PhysicsParams(thermal_capacitance_kj_per_k=2500.0)  # tau_room = 100 s -> max dt = 400 s
        assert v2.check_step_stability(fast, 400.0).max_dt_s == 400.0
        with pytest.raises(v2.PhysicsStabilityError, match="exceeds"):
            v2.check_step_stability(fast, 401.0)

    def test_amplification_factor_is_in_unit_interval_for_every_allowed_dt(self):
        for dt in (1.0, 10.0, 300.0, 1800.0, 3600.0):
            assert 0.0 < v2.check_step_stability(DEFAULT_PHYSICS_PARAMS, dt).room_amplification < 1.0

    def test_step_refuses_an_unchecked_dt(self):
        s = v2.initial_state(inputs(), DEFAULT_PHYSICS_PARAMS, 12.0)
        with pytest.raises(v2.PhysicsStabilityError):
            v2.step(s, inputs(), 7200.0, DEFAULT_PHYSICS_PARAMS)

    def test_twin_rejects_a_too_long_step_before_changing_anything(self):
        tw = twin2(physics_params=PhysicsParams(thermal_capacitance_kj_per_k=7500.0))  # tau 300 s, max dt 1200 s
        tw.step(act(0.5))
        before = (tw.dynamic_state, tw._time, tw.state)
        with pytest.raises(InvalidInputError) as exc:
            tw.step(act(0.9), dt_seconds=1800.0)
        assert exc.value.field == "dt_seconds"
        assert (tw.dynamic_state, tw._time, tw.state) == before

    def test_sim_step_seconds_env(self, monkeypatch):
        monkeypatch.delenv("SIM_STEP_SECONDS", raising=False)
        assert v2.sim_step_seconds() == 300.0
        monkeypatch.setenv("SIM_STEP_SECONDS", "60")
        tw = twin2()
        tw.step(act(0.5))
        assert tw.last_step_dt_seconds == 60.0  # the configured step is v2's default step
        tw.step(act(0.5), dt_seconds=120.0)
        assert tw.last_step_dt_seconds == 120.0

    @pytest.mark.parametrize("bad", ["abc", "0", "-5", "nan", "inf"])
    def test_invalid_sim_step_seconds_is_an_error(self, monkeypatch, bad):
        monkeypatch.setenv("SIM_STEP_SECONDS", bad)
        with pytest.raises((v2.PhysicsStabilityError, InvalidInputError)):
            twin2()

    def test_configured_step_outside_the_checked_range_fails_at_construction(self, monkeypatch):
        monkeypatch.setenv("SIM_STEP_SECONDS", "3000")
        with pytest.raises(InvalidInputError) as exc:
            twin2(physics_params=PhysicsParams(thermal_capacitance_kj_per_k=7500.0))
        assert exc.value.field == "SIM_STEP_SECONDS"


# =============================================================================== v1 invariants carried over
class TestInvariantsCarriedOver:
    def test_initial_state_is_settled_and_the_water_counter_starts_at_zero(self):
        tw = twin2()
        ds = tw.dynamic_state
        assert ds.water_cum_l == 0.0 and tw._water_consumed_cumulative_L == 0.0
        before = ds
        tw2 = twin2()
        tw2.step(act(tw2.state.server_utilisation, 25.0, CoolingMode.CLOSED_LOOP))
        assert tw2.dynamic_state.t_room_c == pytest.approx(before.t_room_c)  # nothing moves at steady state

    def test_cumulative_water_is_the_sum_of_steps(self):
        tw = twin2()
        total = 0.0
        for u in (0.3, 0.6, 0.9, 0.9):
            tw.step(act(u, 30.0, CoolingMode.EVAPORATIVE))
            total += tw.last_balance["water_evaporated_L"]
        assert tw.state.water_consumed_L == pytest.approx(total)
        assert tw.dynamic_state.water_cum_l == pytest.approx(total)

    def test_clock_and_carbon_use_the_real_step(self):
        tw = twin2()
        s = tw.step(act(0.5), dt_seconds=120.0)
        assert (s.timestamp - START).total_seconds() == 120.0
        assert s.carbon_gco2 == pytest.approx(carbon_emissions_gco2(s.total_power_kw, 475.0, 120.0 / 3600.0))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("utilisation", 1.5),
            ("utilisation", float("nan")),
            ("outside_temp_C", 99.0),
            ("humidity_pct", -1.0),
            ("water_pressure_bar", 50.0),
            ("water_stress", 2.0),
            ("chilled_water_temp_C", 80.0),
            ("outside_temp_C", "hot"),
        ],
    )
    def test_bad_input_raises_a_typed_error_and_changes_nothing(self, field, value):
        tw = twin2()
        tw.step(act(0.4))
        before = (tw.dynamic_state, tw.state, tw._time)
        with pytest.raises(InvalidInputError) as exc:
            tw.step({"utilisation": 0.9, field: value})
        assert exc.value.field == field
        assert (tw.dynamic_state, tw.state, tw._time) == before

    @pytest.mark.parametrize("bad", ["", "turbo", None, 3])
    def test_unknown_cooling_mode_is_rejected(self, bad):
        with pytest.raises(InvalidInputError):
            twin2().step({"utilisation": 0.5, "cooling_mode": bad})

    @pytest.mark.parametrize(
        "kw",
        [
            {"max_it_power_kw": 0.0},
            {"idle_power_fraction": 2.0},
            {"thermal_time_constant_min": -1.0},
            {"cooling_capacity_kw": -1.0},
            {"initial_chilled_water_temp_C": 99.0},
        ],
    )
    def test_bad_constructor_arguments_are_rejected(self, kw):
        with pytest.raises(InvalidInputError):
            twin2(**kw)

    def test_free_air_falls_back_to_hybrid_and_the_state_reports_it(self):
        tw = twin2()
        s = tw.step(act(0.5, 25.0, CoolingMode.FREE_AIR))
        assert s.cooling_mode == CoolingMode.HYBRID and tw.dynamic_state.mode_applied == "hybrid"
        s = tw.step(act(0.5, 5.0, CoolingMode.FREE_AIR))
        assert s.cooling_mode == CoolingMode.FREE_AIR and s.water_flow_lpm == 0.0

    def test_drought_override_selection_is_unchanged(self):
        tw = twin2()
        assert tw.select_cooling_mode(5.0, 0.9) == CoolingMode.CLOSED_LOOP
        assert tw.select_cooling_mode(5.0, 0.1) == CoolingMode.FREE_AIR
        assert tw.step({"utilisation": 0.5, "water_stress": 0.9}).drought_override_active is True

    def test_normal_operation_is_safe_and_a_bad_setpoint_is_not(self):
        tw = twin2()
        for _ in range(20):
            tw.step(act(0.7, 25.0, CoolingMode.CLOSED_LOOP, cw=12.0))
        assert (
            tw.is_safe() and SAFETY_ENVELOPE.inlet_min_C <= tw.state.server_inlet_temp_C <= SAFETY_ENVELOPE.inlet_max_C
        )
        for _ in range(30):
            tw.step(act(0.7, 25.0, CoolingMode.CLOSED_LOOP, cw=30.0))
        assert not tw.is_safe() and "inlet_above_max" in SAFETY_ENVELOPE.violations(
            tw.state.server_inlet_temp_C, tw.state.server_outlet_temp_C, tw.state.pue
        )

    def test_capacity_is_finite_and_derated_in_hot_weather(self):
        tw = twin2()
        assert tw.cooling_capacity_kw(CoolingMode.HYBRID, 25.0) == pytest.approx(COOLING_CAPACITY_MARGIN * 500.0)
        assert tw.cooling_capacity_kw(CoolingMode.CLOSED_LOOP, 55.0) < tw.cooling_capacity_kw(
            CoolingMode.CLOSED_LOOP, 25.0
        )

    def test_heat_removed_never_exceeds_capacity_even_when_overloaded(self):
        tw = twin2(cooling_capacity_kw=250.0)
        for _ in range(10):
            tw.step(act(1.0))
            b = tw.last_balance
            assert b["heat_removed_kw"] <= b["capacity_kw"] + 1e-9
        assert b["heat_removed_kw"] == pytest.approx(250.0) and b["heat_unremoved_kw"] == pytest.approx(250.0)

    def test_overloaded_room_warms_linearly_until_the_plant_catches_up(self):
        tw = twin2(cooling_capacity_kw=250.0)
        tw.step(act(1.0))
        t1 = tw.dynamic_state.t_room_c
        tw.step(act(1.0))
        t2 = tw.dynamic_state.t_room_c
        tw.step(act(1.0))
        t3 = tw.dynamic_state.t_room_c
        assert (t3 - t2) == pytest.approx(t2 - t1, rel=1e-9)  # constant Q_stored, no steady state

    def test_outlet_is_inlet_plus_the_air_stream_delta_t_at_steady_state(self):
        tw = twin2()
        for _ in range(60):
            s = tw.step(act(0.8, 25.0, CoolingMode.CLOSED_LOOP))
        m_cp = AIR_DENSITY_KG_M3 * tw.effective_air_flow_m3_s(s.it_power_kw) * SPECIFIC_HEAT_AIR_J_KG_K
        assert s.server_outlet_temp_C - s.server_inlet_temp_C == pytest.approx(s.it_power_kw * 1000.0 / m_cp, rel=1e-9)

    def test_legacy_and_v1_numerics_are_untouched_by_v2_being_importable(self):
        legacy = DigitalTwin(physics_version="legacy-0", start_time=START)
        s = legacy.step({"utilisation": 0.5, "outside_temp_C": 25.0})
        assert s.server_inlet_temp_C == pytest.approx(14.0)
        v1 = DigitalTwin(physics_version="1", start_time=START)
        assert v1.step({"utilisation": 0.5, "outside_temp_C": 25.0}).server_inlet_temp_C == pytest.approx(18.0)

    def test_direct_calls_use_v2_formulas_not_legacy_ones(self):
        tw = twin2()
        flow, litres = tw.compute_water_consumption(100.0, CoolingMode.EVAPORATIVE, 30.0)
        assert litres <= LATENT_WATER_BOUND_L_PER_KWH * (100.0 * 3.5 + 100.0) * (300.0 / 3600.0) + 1e-9
        assert tw.compute_cooling_power(300.0, CoolingMode.HYBRID, 25.0, 12.0) == pytest.approx(
            300.0 / v2.cop("hybrid", 300.0, 25.0, 50.0, 12.0, tw.physics_params)
        )

    def test_changed_parameters_change_the_trajectory(self):
        a = twin2()
        b = twin2(physics_params=PhysicsParams(thermal_capacitance_kj_per_k=45000.0))
        for tw in (a, b):
            tw.step(act(0.1))
            tw.step(act(1.0))
        assert a.dynamic_state.t_room_c > b.dynamic_state.t_room_c  # more thermal mass -> slower warm-up
