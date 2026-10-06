"""Physics v1 invariants (T7). Each section is one invariant from the roadmap.

legacy-0 is covered separately and bit-for-bit by tests/golden; a few tests here
run the SAME probe on legacy-0 to document the defect v1 fixes.
"""

from __future__ import annotations

import itertools
import math
from datetime import datetime, timedelta
from unittest import mock

import numpy as np
import pytest

import src.digital_twin as dt_mod
from src.digital_twin import (
    AIR_DENSITY_KG_M3,
    INLET_SUPPLY_FLOOR_C,
    INTERVAL_MINUTES,
    LATENT_WATER_BOUND_L_PER_KWH,
    SAFETY_ENVELOPE,
    SPECIFIC_HEAT_AIR_J_KG_K,
    CoolingMode,
    DigitalTwin,
    InvalidInputError,
    carbon_emissions_gco2,
)
from src.versions import (
    LEGACY_PHYSICS_VERSION,
    PHYSICS_V1,
    PhysicsVersionError,
    active_physics_version,
    assert_same_physics_version,
)

START = datetime(2025, 6, 1, 3, 0, 0)
FLAT = np.full(24, 475.0)
CURVE = np.linspace(300.0, 600.0, 24)
MODES = list(CoolingMode)
UTILS = (0.0, 0.1, 0.5, 0.9, 1.0)
TEMPS = (-20.0, -5.0, 10.0, 25.0, 40.0, 55.0)


@pytest.fixture(autouse=True)
def flat_carbon():
    with mock.patch("src.digital_twin.load_diurnal_carbon_intensity", return_value=(FLAT, False)):
        yield


def v1(**kw) -> DigitalTwin:
    return DigitalTwin(physics_version=PHYSICS_V1, start_time=START, **kw)


def instant(**kw) -> DigitalTwin:
    """v1 twin whose thermal lag is ~0, so one step lands ON the steady-state target (isolates the equations
    from the first-order lag, which has its own tests)."""
    return v1(thermal_time_constant_min=0.01, **kw)


def legacy(**kw) -> DigitalTwin:
    return DigitalTwin(physics_version=LEGACY_PHYSICS_VERSION, start_time=START, **kw)


def one_step(u=0.5, t=25.0, mode=CoolingMode.CLOSED_LOOP, **extra):
    twin = extra.pop("twin", None) or v1()
    state = twin.step({"utilisation": u, "outside_temp_C": t, "cooling_mode": mode, **extra})
    return twin, state


def fingerprint(twin: DigitalTwin) -> dict:
    return {
        "time": twin._time,
        "util": twin._utilisation,
        "temp": twin._outside_temp_C,
        "mode": twin._cooling_mode,
        "hum": twin._humidity_pct,
        "stress": twin._water_stress,
        "cw_req": twin._requested_chilled_water_temp_C,
        "cw_applied": twin._applied_chilled_water_temp_C,
        "water": twin._water_consumed_cumulative_L,
        "inlet": twin._inlet_temp_C,
        "outlet": twin._outlet_temp_C,
        "state": twin._state.to_dict(),
    }


# =============================================================================== versioning
class TestPhysicsVersion:
    def test_v1_is_the_default(self, monkeypatch):
        monkeypatch.delenv("PHYSICS_VERSION", raising=False)
        assert active_physics_version() == PHYSICS_V1
        assert DigitalTwin(start_time=START).physics_version == PHYSICS_V1

    def test_environment_selects_legacy(self, monkeypatch):
        monkeypatch.setenv("PHYSICS_VERSION", "legacy-0")
        assert DigitalTwin(start_time=START).physics_version == LEGACY_PHYSICS_VERSION

    def test_explicit_argument_wins_over_environment(self, monkeypatch):
        monkeypatch.setenv("PHYSICS_VERSION", "legacy-0")
        assert DigitalTwin(physics_version="1", start_time=START).physics_version == "1"

    @pytest.mark.parametrize("bad", ["3", "legacy", "v1", "LEGACY-0"])  # "2" became a known version in T21
    def test_unknown_version_raises_never_falls_back(self, monkeypatch, bad):
        with pytest.raises(PhysicsVersionError):
            DigitalTwin(physics_version=bad)
        monkeypatch.setenv("PHYSICS_VERSION", bad)
        with pytest.raises(PhysicsVersionError):
            active_physics_version()

    def test_mixing_versions_is_refused(self):
        assert assert_same_physics_version("1", "1") == "1"
        with pytest.raises(PhysicsVersionError, match="mix"):
            assert_same_physics_version("1", "legacy-0")
        with pytest.raises(PhysicsVersionError):
            assert_same_physics_version("1", None)  # an unversioned record cannot join a versioned aggregate
        with pytest.raises(PhysicsVersionError):
            assert_same_physics_version()

    def test_legacy_only_supports_its_fixed_step(self):
        twin = legacy()
        twin.step({"utilisation": 0.5}, dt_seconds=300.0)  # same as the default: allowed
        with pytest.raises(InvalidInputError):
            twin.step({"utilisation": 0.5}, dt_seconds=30.0)

    def test_the_two_versions_really_differ(self):
        _, old = one_step(twin=legacy())
        _, new = one_step(twin=v1())
        assert old.server_inlet_temp_C == pytest.approx(14.0)
        assert new.server_inlet_temp_C == pytest.approx(18.0)


# =============================================================================== 1. energy closure
class TestEnergyClosure:
    @pytest.mark.parametrize("mode,u,t", list(itertools.product(MODES, UTILS, TEMPS)))
    def test_total_equals_it_plus_cooling(self, mode, u, t):
        twin, s = one_step(u, t, mode)
        assert abs(s.total_power_kw - (s.it_power_kw + s.cooling_power_kw)) < 1e-6
        if s.it_power_kw > 0.1:
            assert s.pue == pytest.approx(s.total_power_kw / s.it_power_kw, abs=1e-9)

    @pytest.mark.parametrize("cap", [None, 120.0, 300.0])
    @pytest.mark.parametrize("u", UTILS)
    def test_heat_balance_closes_with_and_without_a_capacity_limit(self, cap, u):
        twin = v1(cooling_capacity_kw=cap)
        s = twin.step({"utilisation": u, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.CLOSED_LOOP})
        b = twin.last_balance
        assert b["it_heat_kw"] == pytest.approx(b["heat_removed_kw"] + b["heat_unremoved_kw"], abs=1e-9)
        assert b["heat_rejected_kw"] == pytest.approx(b["heat_removed_kw"] + b["cooling_electrical_kw"], abs=1e-9)
        assert b["cooling_electrical_kw"] == pytest.approx(s.cooling_power_kw)
        assert b["heat_removed_kw"] <= b["capacity_kw"] + 1e-9

    @pytest.mark.parametrize("mode", MODES)
    def test_air_stream_carries_exactly_the_it_heat_at_steady_state(self, mode):
        """Q = m_dot * cp * dT: a settled twin's (outlet - inlet) accounts for all IT power."""
        twin = v1()
        for _ in range(120):  # let the first-order lag settle (it starts from the idle state)
            s = twin.step(
                {
                    "utilisation": 0.7,
                    "outside_temp_C": 5.0 if mode == CoolingMode.FREE_AIR else 25.0,
                    "cooling_mode": mode,
                }
            )
        m_cp = AIR_DENSITY_KG_M3 * twin.effective_air_flow_m3_s(s.it_power_kw) * SPECIFIC_HEAT_AIR_J_KG_K
        carried_kw = (s.server_outlet_temp_C - s.server_inlet_temp_C) * m_cp / 1000.0
        assert carried_kw == pytest.approx(s.it_power_kw, rel=1e-9)


# =============================================================================== 2. latent-heat water bound
class TestLatentHeatWaterBound:
    def test_the_bound_is_the_physical_constant(self):
        assert LATENT_WATER_BOUND_L_PER_KWH == pytest.approx(3.6e6 / 2.26e6)
        assert 1.55 < LATENT_WATER_BOUND_L_PER_KWH < 1.65  # ~1.6 L per kWh of heat

    @pytest.mark.parametrize("mode,u,t", list(itertools.product(MODES, UTILS, TEMPS)))
    @pytest.mark.parametrize("humidity", [10.0, 50.0, 100.0])
    def test_water_never_exceeds_latent_heat_of_the_heat_rejected(self, mode, u, t, humidity):
        twin, s = one_step(u, t, mode, humidity_pct=humidity)
        b = twin.last_balance
        bound_L = b["heat_rejected_kw"] * (b["dt_s"] / 3600.0) * LATENT_WATER_BOUND_L_PER_KWH
        assert b["water_evaporated_L"] <= bound_L * (1 + 1e-12)
        assert s.water_flow_lpm * (b["dt_s"] / 60.0) == pytest.approx(b["water_evaporated_L"])

    @pytest.mark.parametrize("dt_s", [1.0, 30.0, 300.0, 3600.0])
    def test_bound_holds_for_any_step_length(self, dt_s):
        twin = v1()
        twin.step(
            {"utilisation": 0.9, "outside_temp_C": 45.0, "cooling_mode": CoolingMode.EVAPORATIVE}, dt_seconds=dt_s
        )
        b = twin.last_balance
        assert b["water_evaporated_L"] <= b["heat_rejected_kw"] * (dt_s / 3600.0) * LATENT_WATER_BOUND_L_PER_KWH * (
            1 + 1e-12
        )

    def test_water_is_tied_to_heat_rejected_by_the_documented_formula(self):
        twin, s = one_step(0.5, 25.0, CoolingMode.EVAPORATIVE)
        b = twin.last_balance
        share = min(1.0, dt_mod._EVAPORATIVE_HEAT_FRACTION[CoolingMode.EVAPORATIVE] * (1 + 0.02 * (25.0 - 15.0)))
        expected = share * b["heat_rejected_kw"] * (300 / 3600) * LATENT_WATER_BOUND_L_PER_KWH
        assert b["water_evaporated_L"] == pytest.approx(expected, rel=1e-12)

    def test_water_follows_heat_not_electrical_cooling_power(self):
        """Same IT heat, same mode, but a worse COP (hot day) -> more electrical power. Water changes only
        through the (slightly larger) rejected heat and the warm-weather share, never by cooling_kW x a constant."""
        cold, _ = one_step(0.5, 16.0, CoolingMode.HYBRID)
        hot, _ = one_step(0.5, 34.0, CoolingMode.HYBRID)
        bc, bh = cold.last_balance, hot.last_balance
        assert bh["cooling_electrical_kw"] > bc["cooling_electrical_kw"]
        per_kwh = lambda b, share: b["water_evaporated_L"] / (b["heat_rejected_kw"] * 300 / 3600)  # noqa: E731
        assert per_kwh(bc, 0) == pytest.approx(min(1, 0.4 * (1 + 0.02 * 1.0)) * LATENT_WATER_BOUND_L_PER_KWH)
        assert per_kwh(bh, 0) == pytest.approx(min(1, 0.4 * (1 + 0.02 * 19.0)) * LATENT_WATER_BOUND_L_PER_KWH)

    def test_humidity_does_not_increase_water(self):
        a, _ = one_step(0.5, 25.0, CoolingMode.HYBRID, humidity_pct=20.0)
        b, _ = one_step(0.5, 25.0, CoolingMode.HYBRID, humidity_pct=95.0)
        assert a.last_balance["water_evaporated_L"] == pytest.approx(b.last_balance["water_evaporated_L"])

    def test_water_scales_linearly_with_the_step_length(self):
        a = v1()
        a.step({"utilisation": 0.5, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.EVAPORATIVE}, dt_seconds=150.0)
        b = v1()
        b.step({"utilisation": 0.5, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.EVAPORATIVE}, dt_seconds=300.0)
        assert b.last_balance["water_evaporated_L"] == pytest.approx(2 * a.last_balance["water_evaporated_L"])

    def test_mode_ordering_and_free_air_uses_no_water(self):
        water = {}
        for mode in MODES:
            twin, _ = one_step(0.6, 5.0 if mode == CoolingMode.FREE_AIR else 25.0, mode)
            water[mode] = twin.last_balance["water_evaporated_L"]
        assert water[CoolingMode.FREE_AIR] == 0.0
        assert water[CoolingMode.EVAPORATIVE] > water[CoolingMode.HYBRID] > water[CoolingMode.CLOSED_LOOP] > 0.0

    def test_wue_is_in_a_realistic_range_for_an_evaporative_plant(self):
        _, s = one_step(0.5, 25.0, CoolingMode.EVAPORATIVE)
        assert 1.0 < s.wue < 3.0  # published fleet averages are ~1.8 L/kWh
        assert s.wue <= LATENT_WATER_BOUND_L_PER_KWH * s.pue + 1e-9

    def test_cumulative_water_is_the_sum_of_steps(self):
        twin = v1()
        total = 0.0
        for _ in range(10):
            twin.step({"utilisation": 0.6, "outside_temp_C": 30.0, "cooling_mode": CoolingMode.EVAPORATIVE})
            total += twin.last_balance["water_evaporated_L"]
        assert twin.state.water_consumed_L == pytest.approx(total)

    def test_direct_water_call_keeps_the_old_signature_and_stays_bounded(self):
        twin = v1()
        flow, consumed = twin.compute_water_consumption(100.0, CoolingMode.EVAPORATIVE, 25.0)
        assert flow > 0 and consumed == pytest.approx(flow * 5)
        assert twin.compute_water_consumption(50.0, CoolingMode.FREE_AIR, 25.0) == (0.0, 0.0)

    def test_legacy_exceeded_the_bound_by_an_order_of_magnitude(self):
        """Documents the defect: legacy-0 tied water to ELECTRICAL cooling power with an unbounded coefficient."""
        twin, s = one_step(0.9, 40.0, CoolingMode.EVAPORATIVE, twin=legacy())
        bound_L = (s.it_power_kw + s.cooling_power_kw) * (5 / 60) * LATENT_WATER_BOUND_L_PER_KWH
        assert s.water_flow_lpm * 5 > 10 * bound_L


# =============================================================================== 3. finite cooling capacity
class TestFiniteCoolingCapacity:
    def test_default_capacity_covers_the_design_load_in_normal_weather(self):
        twin = v1()
        assert twin.cooling_capacity_kw(CoolingMode.CLOSED_LOOP, 25.0) == pytest.approx(1.10 * 500.0)
        _, s = one_step(1.0, 35.0, CoolingMode.CLOSED_LOOP, twin=instant())
        assert s.server_inlet_temp_C == pytest.approx(INLET_SUPPLY_FLOOR_C)

    def test_load_beyond_capacity_raises_the_inlet_by_the_unremoved_heat(self):
        twin = instant(cooling_capacity_kw=250.0)
        s = twin.step({"utilisation": 1.0, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.CLOSED_LOOP})
        b = twin.last_balance
        assert b["heat_removed_kw"] == pytest.approx(250.0)
        assert b["heat_unremoved_kw"] == pytest.approx(250.0)
        m_cp = AIR_DENSITY_KG_M3 * twin.effective_air_flow_m3_s(500.0) * SPECIFIC_HEAT_AIR_J_KG_K
        assert s.server_inlet_temp_C == pytest.approx(INLET_SUPPLY_FLOOR_C + 250.0e3 / m_cp, rel=1e-12)
        assert not SAFETY_ENVELOPE.is_safe(
            s.server_inlet_temp_C, s.server_outlet_temp_C, s.pue
        )  # outlet over its limit

    def test_cooling_power_is_for_the_heat_actually_removed(self):
        small = instant(cooling_capacity_kw=250.0)
        big = v1()
        a = small.step({"utilisation": 1.0, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.CLOSED_LOOP})
        b = big.step({"utilisation": 1.0, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.CLOSED_LOOP})
        assert a.cooling_power_kw == pytest.approx(b.cooling_power_kw * 250.0 / 500.0)

    def test_inlet_is_non_decreasing_in_load_and_rises_once_capacity_is_exceeded(self):
        inlets = []
        for u in np.linspace(0, 1, 21):
            _, s = one_step(float(u), 25.0, CoolingMode.CLOSED_LOOP, twin=instant(cooling_capacity_kw=300.0))
            inlets.append(s.server_inlet_temp_C)
        assert all(b >= a - 1e-12 for a, b in zip(inlets, inlets[1:]))
        assert inlets[-1] > inlets[0] + 1.0
        assert inlets[0] == pytest.approx(INLET_SUPPLY_FLOOR_C)  # below capacity: load does not move the inlet

    def test_hot_weather_derates_the_plant(self):
        twin = v1()
        design = twin.cooling_capacity_kw(CoolingMode.CLOSED_LOOP, 35.0)
        assert twin.cooling_capacity_kw(CoolingMode.CLOSED_LOOP, 50.0) == pytest.approx(design * 0.85)
        assert twin.cooling_capacity_kw(CoolingMode.CLOSED_LOOP, 200.0) == pytest.approx(design * 0.2)  # floor

    def test_legacy_plant_had_unlimited_capacity(self):
        _, light = one_step(0.2, 25.0, twin=legacy())
        _, heavy = one_step(1.0, 25.0, twin=legacy(cooling_capacity_kw=1.0))
        assert light.server_inlet_temp_C == heavy.server_inlet_temp_C == pytest.approx(14.0)
        assert legacy().cooling_capacity_kw(CoolingMode.CLOSED_LOOP, 25.0) == math.inf


# =============================================================================== 4. monotonicity
class TestMonotonicity:
    @pytest.mark.parametrize("cap", [None, 280.0])
    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("t", [-5.0, 10.0, 25.0, 40.0])
    def test_outlet_is_non_decreasing_in_load(self, mode, t, cap):
        outlets = [
            one_step(float(u), t, mode, twin=instant(cooling_capacity_kw=cap))[1].server_outlet_temp_C
            for u in np.linspace(0, 1, 26)
        ]
        assert all(b >= a - 1e-9 for a, b in zip(outlets, outlets[1:]))

    @pytest.mark.parametrize("cw", [6.0, 14.0, 20.0, 24.0])
    @pytest.mark.parametrize("u", [0.2, 0.9, 1.0])
    @pytest.mark.parametrize("mode", MODES)
    def test_inlet_and_outlet_are_non_decreasing_in_outside_temperature(self, mode, u, cw):
        inlets, outlets = [], []
        for t in np.arange(-20.0, 55.1, 2.5):
            twin = instant(initial_chilled_water_temp_C=cw)
            s = twin.step(
                {"utilisation": u, "outside_temp_C": float(t), "cooling_mode": mode, "chilled_water_temp_C": cw}
            )
            inlets.append(s.server_inlet_temp_C)
            outlets.append(s.server_outlet_temp_C)
        assert all(b >= a - 1e-9 for a, b in zip(inlets, inlets[1:])), inlets
        assert all(b >= a - 1e-9 for a, b in zip(outlets, outlets[1:])), outlets

    def test_monotone_across_the_automatic_mode_switches(self):
        inlets = []
        for t in np.arange(-10.0, 50.1, 1.0):
            twin = instant()
            mode = twin.select_cooling_mode(float(t), 0.0)
            inlets.append(
                twin.step({"utilisation": 0.8, "outside_temp_C": float(t), "cooling_mode": mode}).server_inlet_temp_C
            )
        assert all(b >= a - 1e-9 for a, b in zip(inlets, inlets[1:])), inlets

    def test_still_monotone_after_the_thermal_lag_has_settled(self):
        outlets = []
        for u in (0.2, 0.5, 0.8, 1.0):
            twin = v1()
            for _ in range(80):
                s = twin.step({"utilisation": u, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.HYBRID})
            outlets.append(s.server_outlet_temp_C)
        assert outlets == sorted(outlets)

    def test_warmer_setpoint_never_lowers_the_inlet(self):
        inlets = [
            one_step(0.5, 25.0, twin=instant(initial_chilled_water_temp_C=cw), chilled_water_temp_C=cw)[
                1
            ].server_inlet_temp_C
            for cw in np.arange(5.0, 30.1, 1.0)
        ]
        assert all(b >= a - 1e-12 for a, b in zip(inlets, inlets[1:]))


# =============================================================================== 5. input validation
BAD_VALUES = {
    "utilisation": [float("nan"), float("inf"), -0.01, 1.01, "0.5x", None, True],
    "outside_temp_C": [float("nan"), float("inf"), float("-inf"), -60.5, 60.5, "hot", None],
    "humidity_pct": [float("nan"), -1.0, 100.5, "wet"],
    "water_pressure_bar": [float("nan"), -0.1, 20.5],
    "water_stress": [float("nan"), -0.01, 7.0, "x"],
    "chilled_water_temp_C": [float("nan"), float("inf"), -0.1, 40.5, "cold"],
}


class TestInputValidation:
    @pytest.mark.parametrize("field,value", [(f, v) for f, vals in BAD_VALUES.items() for v in vals])
    def test_bad_input_raises_a_typed_error_naming_the_field(self, field, value):
        twin = v1()
        with pytest.raises(InvalidInputError) as exc:
            twin.step({"utilisation": 0.5, field: value})
        assert exc.value.field == field
        assert isinstance(exc.value, ValueError)  # existing `except ValueError` callers keep working

    @pytest.mark.parametrize("field,value", [(f, vals[0]) for f, vals in BAD_VALUES.items()])
    def test_a_rejected_step_changes_nothing(self, field, value):
        twin = v1()
        twin.step({"utilisation": 0.4, "outside_temp_C": 20.0, "cooling_mode": CoolingMode.HYBRID})
        before = fingerprint(twin)
        # the valid fields in the same dict must NOT be applied either
        with pytest.raises(InvalidInputError):
            twin.step({"utilisation": 0.9, "outside_temp_C": 33.0, "cooling_mode": "evaporative", field: value})
        assert fingerprint(twin) == before

    @pytest.mark.parametrize("bad", ["", "turbo", None, 3])
    def test_unknown_cooling_mode(self, bad):
        with pytest.raises(InvalidInputError) as exc:
            v1().step({"utilisation": 0.5, "cooling_mode": bad})
        assert exc.value.field == "cooling_mode"

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), 3600.1, "5", True])
    def test_bad_step_length(self, bad):
        with pytest.raises(InvalidInputError) as exc:
            v1().step({"utilisation": 0.5}, dt_seconds=bad)
        assert exc.value.field == "dt_seconds"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_it_power_kw": 0.0},
            {"max_it_power_kw": float("nan")},
            {"idle_power_fraction": 1.5},
            {"idle_power_fraction": -0.1},
            {"air_flow_m3_s": 0.0},
            {"thermal_time_constant_min": 0.0},
            {"cooling_capacity_kw": -5.0},
            {"initial_chilled_water_temp_C": float("inf")},
            {"max_chilled_water_rate_C_per_step": -1.0},
        ],
    )
    def test_bad_constructor_arguments(self, kwargs):
        with pytest.raises(InvalidInputError):
            v1(**kwargs)

    def test_boundary_values_are_accepted(self):
        twin = v1()
        for field, (lo, hi) in dt_mod.INPUT_RANGES.items():
            for value in (lo, hi):
                twin.step({"utilisation": 0.5, field: value})

    def test_numpy_numbers_are_accepted(self):
        v1().step({"utilisation": np.float32(0.5), "outside_temp_C": np.float64(20.0)})

    def test_it_power_still_rejects_bad_utilisation_in_both_versions(self):
        for twin in (v1(), legacy()):
            with pytest.raises(ValueError, match="Utilisation must be in"):
                twin.compute_it_power(1.5)
            with pytest.raises(ValueError):
                twin.compute_it_power(float("nan"))

    def test_legacy_validation_is_unchanged(self):
        twin = legacy()
        with pytest.raises(ValueError, match="utilisation must be in"):
            twin.step({"utilisation": 2.0})
        twin.step({"utilisation": 0.5, "outside_temp_C": float("nan")})  # legacy never checked this


# =============================================================================== 6. one carbon function
class TestOneCarbonFunction:
    def test_the_function(self):
        assert carbon_emissions_gco2(100.0, 475.0, 0.5) == pytest.approx(23750.0)

    @pytest.mark.parametrize("mode", MODES)
    def test_state_carbon_is_total_energy_times_intensity(self, mode):
        _, s = one_step(0.6, 5.0 if mode == CoolingMode.FREE_AIR else 25.0, mode)
        assert s.carbon_gco2 == pytest.approx(carbon_emissions_gco2(s.total_power_kw, 475.0, 5 / 60), rel=1e-12)
        assert s.carbon_gco2 > carbon_emissions_gco2(s.cooling_power_kw, 475.0, 5 / 60)  # not cooling-only any more

    def test_intensity_follows_the_simulation_hour(self):
        with mock.patch("src.digital_twin.load_diurnal_carbon_intensity", return_value=(CURVE, False)):
            twin = v1()
            for _ in range(30):
                s = twin.step({"utilisation": 0.5, "outside_temp_C": 25.0})
                assert s.carbon_intensity_gco2_per_kwh == CURVE[s.timestamp.hour]

    def test_step_length_scales_carbon(self):
        a, b = v1(), v1()
        sa = a.step({"utilisation": 0.5}, dt_seconds=150.0)
        sb = b.step({"utilisation": 0.5}, dt_seconds=300.0)
        assert sb.carbon_gco2 == pytest.approx(2 * sa.carbon_gco2)

    def test_whatif_and_state_agree(self):
        """The 4.4x gap between the two endpoints came from two definitions; now one."""
        from api.services import twin_service

        whatif = twin_service.compute_whatif(0.5, 25.0, 0.0, "hybrid", 12.0)
        state = twin_service.compute_state(0.5, 25.0, 0.0, "hybrid", live=False)
        assert whatif["total_co2_kg"] == pytest.approx(288 * state["carbon_gco2"] / 1000.0, rel=1e-9)
        assert whatif["total_co2_kg"] * 1000.0 == pytest.approx(whatif["total_energy_kwh"] * 475.0, rel=1e-9)

    def test_legacy_state_carbon_was_cooling_only(self):
        _, s = one_step(0.5, 25.0, CoolingMode.HYBRID, twin=legacy())
        assert s.carbon_gco2 == pytest.approx(s.cooling_power_kw * 475.0 * 5 / 60)

    def test_optimizer_reward_uses_the_same_definition(self):
        from src.optimizer import MAX_IT_POWER_KW, DataCentreEnv

        env = DataCentreEnv(seed=1, carbon_intensity_by_hour=CURVE, physics_version="1")
        env.reset(seed=1)
        _, _, _, _, info = env.step(np.array([0.5, 0.5], dtype=np.float32))
        st = info["state"]
        assert st["carbon_gco2"] == pytest.approx(
            carbon_emissions_gco2(st["it_power"] + st["cooling_power"], st["carbon_intensity_gco2_per_kwh"], 5 / 60),
            rel=1e-12,
        )
        assert env._carbon_norm_max == pytest.approx(MAX_IT_POWER_KW * SAFETY_ENVELOPE.pue_max * CURVE.max() * 5 / 60)
        assert env._carbon_norm_max >= st["carbon_gco2"]  # the normaliser really is a ceiling


# =============================================================================== 7. one safety envelope
class TestOneSafetyEnvelope:
    def test_module_constants_are_the_envelope(self):
        assert (dt_mod.INLET_TEMP_MIN, dt_mod.INLET_TEMP_MAX) == (
            SAFETY_ENVELOPE.inlet_min_C,
            SAFETY_ENVELOPE.inlet_max_C,
        )
        assert (dt_mod.OUTLET_TEMP_MAX, dt_mod.PUE_MAX_SAFE) == (SAFETY_ENVELOPE.outlet_max_C, SAFETY_ENVELOPE.pue_max)
        assert INLET_SUPPLY_FLOOR_C == SAFETY_ENVELOPE.inlet_min_C

    @pytest.mark.parametrize(
        "inlet,outlet,pue,expected",
        [
            (20, 40, 1.4, ()),
            (17.9, 40, 1.4, ("inlet_below_min",)),
            (27.1, 40, 1.4, ("inlet_above_max",)),
            (20, 45.1, 1.4, ("outlet_above_max",)),
            (20, 40, 2.01, ("pue_above_max",)),
            (18, 45, 2.0, ()),  # limits are inclusive
            (27, 45, 2.0, ()),
            (10, 60, 3.0, ("inlet_below_min", "outlet_above_max", "pue_above_max")),
        ],
    )
    def test_violations(self, inlet, outlet, pue, expected):
        assert SAFETY_ENVELOPE.violations(inlet, outlet, pue) == expected
        assert SAFETY_ENVELOPE.is_safe(inlet, outlet, pue) is (not expected)

    @pytest.mark.parametrize("bad", [float("nan")])
    def test_nan_is_a_violation_not_a_pass(self, bad):
        assert not SAFETY_ENVELOPE.is_safe(bad, 40, 1.4)
        assert not SAFETY_ENVELOPE.is_safe(20, bad, 1.4)
        assert not SAFETY_ENVELOPE.is_safe(20, 40, bad)

    @pytest.mark.parametrize("version", [LEGACY_PHYSICS_VERSION, PHYSICS_V1])
    def test_is_safe_uses_the_envelope(self, version):
        twin = DigitalTwin(physics_version=version, start_time=START)
        for u, t, mode in itertools.product((0.1, 0.9, 1.0), (-5.0, 25.0, 45.0), MODES):
            s = twin.step({"utilisation": u, "outside_temp_C": t, "cooling_mode": mode})
            assert twin.is_safe() == SAFETY_ENVELOPE.is_safe(s.server_inlet_temp_C, s.server_outlet_temp_C, s.pue)

    def _env_reward_with_state(self, version, **state):
        from src.optimizer import DataCentreEnv

        env = DataCentreEnv(seed=0, carbon_intensity_by_hour=FLAT, physics_version=version)
        env.reset(seed=0)
        base = {
            "hour": 12.0,
            "utilisation": 0.5,
            "outside_temp": 25.0,
            "inlet_temp": 20.0,
            "outlet_temp": 35.0,
            "it_power": 350.0,
            "cooling_power": 100.0,
            "water_consumed": 0.0,
            "pue": 1.3,
            "wue": 0.0,
            "carbon_intensity_gco2_per_kwh": 475.0,
            "carbon_gco2": 0.0,
            "water_stress": 0.0,
            "drought_override_active": False,
        }
        base.update(state)
        env._step_physics = lambda chilled, mode: dict(base)
        return env.step(np.array([0.5, 0.5], dtype=np.float32))[1]

    @pytest.mark.parametrize(
        "override", [{"inlet_temp": 15.0}, {"inlet_temp": 30.0}, {"outlet_temp": 46.0}, {"pue": 2.4}]
    )
    def test_v1_penalty_covers_the_whole_envelope(self, override):
        safe = self._env_reward_with_state("1")
        assert self._env_reward_with_state("1", **override) < safe - 1.9  # the -2.0 penalty (plus a slightly higher J)

    def test_v1_penalty_is_absent_inside_the_envelope(self):
        assert self._env_reward_with_state("1") > -1.0

    def test_legacy_penalty_only_looked_at_the_outlet(self):
        safe = self._env_reward_with_state(LEGACY_PHYSICS_VERSION)
        assert self._env_reward_with_state(LEGACY_PHYSICS_VERSION, inlet_temp=15.0) == pytest.approx(safe)
        assert self._env_reward_with_state(LEGACY_PHYSICS_VERSION, outlet_temp=46.0) < safe - 1.9

    def test_optimizer_violation_count_uses_the_envelope(self):
        import pandas as pd

        from src.optimizer import JointOptimizer

        df = pd.DataFrame(
            {"inlet_temp": [20, 15, 20, 20], "outlet_temp": [40, 40, 50, 40], "pue": [1.3, 1.3, 1.3, 2.5]}
        )
        assert JointOptimizer._count_safety_violations(df, legacy=False) == 3
        assert JointOptimizer._count_safety_violations(df, legacy=True) == 1  # outlet only, as before


# =============================================================================== 8. a reachable safe action
class TestSafeActionIsReachable:
    @pytest.mark.parametrize("u,t", [(0.2, 20.0), (0.5, 25.0), (0.7, 30.0), (0.9, 25.0)])
    def test_some_setpoint_in_the_action_range_is_safe_under_v1(self, u, t):
        from src.optimizer import CHILLED_WATER_ACTION_RANGE_C

        lo, hi = CHILLED_WATER_ACTION_RANGE_C[PHYSICS_V1]
        safe = []
        for cw in np.linspace(lo, hi, 16):
            twin = instant(initial_chilled_water_temp_C=float(cw))
            twin.step(
                {
                    "utilisation": u,
                    "outside_temp_C": t,
                    "cooling_mode": CoolingMode.CLOSED_LOOP,
                    "chilled_water_temp_C": float(cw),
                }
            )
            safe.append(twin.is_safe())
        assert any(safe)
        if u >= 0.7:  # at high load the warm end of the range really is outside the envelope (outlet > 45 C)
            assert not all(safe)

    def test_the_default_twin_runs_inside_the_envelope(self):
        for u in (0.1, 0.5, 1.0):
            twin = v1()
            for _ in range(40):
                twin.step({"utilisation": u, "outside_temp_C": 25.0, "cooling_mode": CoolingMode.HYBRID})
            assert twin.is_safe(), (u, twin.state)

    def test_free_air_in_cold_weather_is_inside_the_envelope(self):
        twin, s = one_step(0.6, -5.0, CoolingMode.FREE_AIR)
        assert twin.is_safe() and s.server_inlet_temp_C == pytest.approx(18.0)

    def test_an_env_action_exists_that_is_safe_under_v1(self):
        from src.optimizer import DataCentreEnv

        env = DataCentreEnv(seed=2, carbon_intensity_by_hour=FLAT, physics_version="1")
        env.reset(seed=2)
        safe_actions = 0
        for chilled in np.linspace(0, 1, 11):
            for mode in (0.33, 0.66, 1.0):  # closed_loop / evaporative / hybrid
                env.reset(seed=2)
                _, _, _, _, info = env.step(np.array([chilled, mode], dtype=np.float32))
                st = info["state"]
                safe_actions += not DataCentreEnv.safety_violations_of(st)
        assert safe_actions > 0

    def test_legacy_envelope_was_unreachable_for_chilled_water_modes(self):
        """Documents the defect: with legacy-0 no setpoint in 5-15 C gives an inlet inside 18-27 C."""
        for cw in np.arange(5.0, 15.01, 1.0):
            twin = legacy(initial_chilled_water_temp_C=float(cw))
            twin.step(
                {
                    "utilisation": 0.5,
                    "outside_temp_C": 25.0,
                    "cooling_mode": CoolingMode.CLOSED_LOOP,
                    "chilled_water_temp_C": float(cw),
                }
            )
            assert not twin.is_safe()

    def test_action_range_is_per_version(self):
        from src.optimizer import CHILLED_WATER_ACTION_RANGE_C, DataCentreEnv

        assert CHILLED_WATER_ACTION_RANGE_C[LEGACY_PHYSICS_VERSION] == (5.0, 15.0)
        for version in (LEGACY_PHYSICS_VERSION, PHYSICS_V1):
            env = DataCentreEnv(seed=0, carbon_intensity_by_hour=FLAT, physics_version=version)
            lo, hi = CHILLED_WATER_ACTION_RANGE_C[version]
            assert env._action_to_control(np.array([0.0, 0.0]))[0] == pytest.approx(lo)
            assert env._action_to_control(np.array([1.0, 0.0]))[0] == pytest.approx(hi)


# =============================================================================== 9. real elapsed dt
class TestRealElapsedDt:
    def test_clock_advances_by_exactly_dt(self):
        twin = v1()
        t0 = twin.state.timestamp
        twin.step({"utilisation": 0.5}, dt_seconds=2.7)
        assert twin.state.timestamp - t0 == timedelta(seconds=2.7)
        assert twin.last_step_dt_seconds == 2.7

    def test_default_step_is_five_minutes_in_both_versions(self):
        for twin in (v1(), legacy()):
            t0 = twin.state.timestamp
            twin.step({"utilisation": 0.5})
            assert twin.state.timestamp - t0 == timedelta(minutes=INTERVAL_MINUTES)
            assert twin.last_step_dt_seconds == 300.0

    def test_sim_time_scale_is_one_when_the_driver_passes_wall_time(self):
        twin = v1()
        wall_dt = 3.0
        t0 = twin.state.timestamp
        for _ in range(20):
            twin.step({"utilisation": 0.5}, dt_seconds=wall_dt)
        assert (twin.state.timestamp - t0).total_seconds() / (20 * wall_dt) == pytest.approx(1.0)

    def test_two_half_steps_equal_one_full_step_for_the_integrated_quantities(self):
        one, two = v1(), v1()
        inputs = {"utilisation": 0.7, "outside_temp_C": 30.0, "cooling_mode": CoolingMode.EVAPORATIVE}
        one.step(inputs, dt_seconds=300.0)
        two.step(inputs, dt_seconds=150.0)
        two.step(inputs, dt_seconds=150.0)
        assert two.state.water_consumed_L == pytest.approx(one.state.water_consumed_L, rel=1e-12)
        assert two.state.timestamp == one.state.timestamp

    def test_thermal_lag_composes_exactly(self):
        """First-order exponentials compose: 2 x 150 s lands where 1 x 300 s does."""
        results = []
        for steps in ((300.0,), (150.0, 150.0), (100.0, 100.0, 100.0)):
            twin = v1(thermal_time_constant_min=10.0)
            twin.step(
                {
                    "utilisation": 0.3,
                    "outside_temp_C": 25.0,
                    "chilled_water_temp_C": 22.0,
                    "cooling_mode": CoolingMode.CLOSED_LOOP,
                },
                dt_seconds=300.0,
            )
            # setpoint step: rate limit allows 2 C per 5 min -> use a generous limit to isolate the lag
            twin2 = v1(
                thermal_time_constant_min=10.0,
                max_chilled_water_rate_C_per_step=100.0,
                initial_chilled_water_temp_C=22.0,
            )
            twin2.step(
                {
                    "utilisation": 0.3,
                    "outside_temp_C": 25.0,
                    "cooling_mode": CoolingMode.CLOSED_LOOP,
                    "chilled_water_temp_C": 22.0,
                },
                dt_seconds=300.0,
            )
            for dt in steps:
                twin2.step(
                    {
                        "utilisation": 0.9,
                        "outside_temp_C": 25.0,
                        "cooling_mode": CoolingMode.CLOSED_LOOP,
                        "chilled_water_temp_C": 22.0,
                    },
                    dt_seconds=dt,
                )
            results.append(twin2.state.server_outlet_temp_C)
        assert results[1] == pytest.approx(results[0], rel=1e-12)
        assert results[2] == pytest.approx(results[0], rel=1e-12)

    def test_actuator_rate_limit_is_per_real_time(self):
        twin = v1(max_chilled_water_rate_C_per_step=2.0, initial_chilled_water_temp_C=12.0)
        twin.step({"utilisation": 0.5, "chilled_water_temp_C": 30.0}, dt_seconds=60.0)
        assert twin._applied_chilled_water_temp_C == pytest.approx(12.0 + 2.0 * 60.0 / 300.0)

    def test_energy_follows_dt(self):
        twin = v1()
        s = twin.step({"utilisation": 0.5}, dt_seconds=60.0)
        assert s.carbon_gco2 == pytest.approx(s.total_power_kw * (60.0 / 3600.0) * 475.0)


# =============================================================================== IT power curve (decision, not a change)
class TestItPowerCurveDecision:
    @pytest.mark.parametrize("twin_factory", [v1, legacy])
    def test_curve_is_unchanged_200kw_idle_470kw_at_90pct(self, twin_factory):
        """Decision recorded in the T7 report: the 40% idle fraction is KEPT. The SPECpower dataset
        needed for the comparison is not available in this environment, so it has not been reviewed;
        changing it requires a new physics version."""
        twin = twin_factory()
        assert twin.compute_it_power(0.0) == pytest.approx(200.0)
        assert twin.compute_it_power(0.9) == pytest.approx(470.0)
        assert twin.compute_it_power(1.0) == pytest.approx(500.0)


# =============================================================================== scope guard
def test_duplicate_physics_modules_are_not_used_by_production_code():
    """digital_twin_optimized.py (own COP/evaporation tables) and the PINN's hard-coded physics duplicate
    legacy equations and are OUT OF SCOPE for v1. They must not be reachable from the API or the twin."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for folder in ("api", "src"):
        for path in (root / folder).rglob("*.py"):
            if path.name == "digital_twin_optimized.py":
                continue
            if "digital_twin_optimized" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
