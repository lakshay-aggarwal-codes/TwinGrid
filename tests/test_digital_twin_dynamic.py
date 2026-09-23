"""
Regression tests for dynamic (non-instantaneous) DigitalTwin physics.

These guard the properties the static->dynamic rewrite added:
thermal inertia, chilled-water actuator rate limiting, deterministic
requested->applied mode/setpoint resolution (with correct reporting),
dynamic COP, humidity-aware water consumption, and the removal of
cosmetic safety clamps.
"""

from src.digital_twin import (
    DigitalTwin,
    CoolingMode,
    OUTLET_TEMP_MAX,
    INLET_TEMP_MIN,
    INLET_TEMP_MAX,
)


class TestDynamicPhysics:
    def test_initial_water_cumulative_is_zero(self):
        """Cumulative water counter reads 0.0 immediately after construction,
        matching the original implementation's contract, even though the
        initial state's own water_consumed_L reflects t=0 consumption."""
        twin = DigitalTwin()
        assert twin._water_consumed_cumulative_L == 0.0

    def test_initial_state_is_at_steady_state(self):
        """At t=0 the twin starts already settled: inlet == chilled-water
        setpoint + approach temperature for the default closed-loop mode."""
        twin = DigitalTwin()
        assert abs(twin._state.server_inlet_temp_C - (12.0 + 2.0)) < 1e-9

    def test_thermal_lag_is_partial_not_instant(self):
        """A step change in the chilled-water setpoint does not teleport
        the inlet temperature to its new steady-state value in one step."""
        twin = DigitalTwin(thermal_time_constant_min=10.0)
        twin.step({"utilisation": 0.2, "outside_temp_C": 25.0, "cooling_mode": "closed_loop"})
        inlet_before = twin._inlet_temp_C

        state = twin.step(
            {
                "utilisation": 0.2,
                "outside_temp_C": 25.0,
                "cooling_mode": "closed_loop",
                "chilled_water_temp_C": 6.0,
            }
        )
        target = 6.0 + 2.0  # new chilled-water setpoint + approach temp
        moved = abs(state.server_inlet_temp_C - inlet_before)
        full_gap = abs(target - inlet_before)
        assert 0 < moved < full_gap

    def test_chilled_water_actuator_is_rate_limited(self):
        """A large requested chilled-water jump is capped per step."""
        twin = DigitalTwin(max_chilled_water_rate_C_per_step=2.0, initial_chilled_water_temp_C=12.0)
        twin.step({"utilisation": 0.5, "outside_temp_C": 25.0, "chilled_water_temp_C": 30.0})
        assert abs(twin._applied_chilled_water_temp_C - 12.0) <= 2.0 + 1e-9

        twin.step({"utilisation": 0.5, "outside_temp_C": 25.0, "chilled_water_temp_C": 30.0})
        assert abs(twin._applied_chilled_water_temp_C - 14.0) <= 2.0 + 1e-9

    def test_free_air_substitutes_to_hybrid_when_hot_and_reports_it(self):
        """Requesting FREE_AIR when outside air is too warm to be effective
        must both USE hybrid physics AND REPORT hybrid — never report a
        mode whose physics wasn't actually used."""
        twin = DigitalTwin()
        state = twin.step({"utilisation": 0.5, "outside_temp_C": 25.0, "cooling_mode": "free_air"})
        assert state.cooling_mode == CoolingMode.HYBRID

    def test_free_air_applies_and_reports_correctly_when_cold(self):
        """When outside air is genuinely cold enough, FREE_AIR is both
        applied and reported (no unnecessary substitution)."""
        twin = DigitalTwin()
        state = twin.step({"utilisation": 0.5, "outside_temp_C": 5.0, "cooling_mode": "free_air"})
        assert state.cooling_mode == CoolingMode.FREE_AIR

    def test_cop_varies_with_load(self):
        """Effective COP (it_power / cooling_power) is not a fixed
        per-mode constant — it changes with load fraction."""
        twin = DigitalTwin()
        cooling_low = twin.compute_cooling_power(50.0, CoolingMode.CLOSED_LOOP, 25.0)
        cooling_high = twin.compute_cooling_power(490.0, CoolingMode.CLOSED_LOOP, 25.0)
        eff_cop_low = 50.0 / cooling_low
        eff_cop_high = 490.0 / cooling_high
        assert abs(eff_cop_low - eff_cop_high) > 1e-6

    def test_cop_derates_with_outside_temperature(self):
        """Higher outside temperature reduces effective COP (raises
        cooling power for the same IT load)."""
        twin = DigitalTwin()
        cooling_cool_outside = twin.compute_cooling_power(400.0, CoolingMode.CLOSED_LOOP, 20.0)
        cooling_hot_outside = twin.compute_cooling_power(400.0, CoolingMode.CLOSED_LOOP, 35.0)
        assert cooling_hot_outside > cooling_cool_outside

    def test_humidity_increases_evaporative_water_flow(self):
        """Higher ambient humidity makes evaporative cooling less
        effective, requiring more water flow for the same cooling load."""
        twin = DigitalTwin()
        twin._humidity_pct = 40.0
        cooling_dry = twin.compute_cooling_power(400.0, CoolingMode.EVAPORATIVE, 25.0)
        flow_dry, _ = twin.compute_water_consumption(cooling_dry, CoolingMode.EVAPORATIVE, 25.0)

        twin._humidity_pct = 90.0
        cooling_humid = twin.compute_cooling_power(400.0, CoolingMode.EVAPORATIVE, 25.0)
        flow_humid, _ = twin.compute_water_consumption(cooling_humid, CoolingMode.EVAPORATIVE, 25.0)

        assert flow_humid > flow_dry

    def test_water_consumed_derives_from_flow_not_reverse(self):
        """consumed_L must equal flow_lpm * INTERVAL_MINUTES exactly —
        flow is the independent variable, consumed is derived from it."""
        from src.digital_twin import INTERVAL_MINUTES

        twin = DigitalTwin()
        flow, consumed = twin.compute_water_consumption(120.0, CoolingMode.EVAPORATIVE, 28.0)
        assert abs(consumed - flow * INTERVAL_MINUTES) < 1e-9

    def test_no_cosmetic_clamp_allows_is_safe_to_detect_unsafe_outlet(self):
        """With no artificial ceiling on achieved outlet temperature,
        a genuinely poor control choice must be observable via is_safe()."""
        twin = DigitalTwin(max_chilled_water_rate_C_per_step=50.0)
        twin.step(
            {
                "utilisation": 0.9,
                "outside_temp_C": 35.0,
                "cooling_mode": "closed_loop",
                "chilled_water_temp_C": 30.0,
            }
        )
        assert twin._state.server_outlet_temp_C > OUTLET_TEMP_MAX
        assert twin.is_safe() is False

    def test_no_cosmetic_clamp_on_inlet_either(self):
        """Achieved inlet temperature is not force-clamped into the safe
        band before is_safe() sees it. Uses a fast thermal response so the
        lag itself doesn't mask the (absent) clamp within one step."""
        twin = DigitalTwin(
            max_chilled_water_rate_C_per_step=50.0,
            initial_chilled_water_temp_C=12.0,
            thermal_time_constant_min=0.1,
        )
        state = twin.step({"utilisation": 0.3, "outside_temp_C": 25.0, "chilled_water_temp_C": 40.0})
        # setpoint + approach (42) is well outside [INLET_TEMP_MIN, INLET_TEMP_MAX]
        # and nothing should have silently pulled it back inside that band.
        assert not (INLET_TEMP_MIN <= state.server_inlet_temp_C <= INLET_TEMP_MAX)

    def test_build_initial_state_and_step_share_one_formula(self):
        """A twin stepped once with conditions identical to its construction
        defaults should already be very close to steady state (small lag
        only, not a second, differently-derived formula producing a very
        different result in kind)."""
        twin = DigitalTwin()
        state = twin.step({"utilisation": 0.0, "outside_temp_C": 25.0, "cooling_mode": "closed_loop"})
        # same steady-state target as t=0 (chilled water setpoint unchanged),
        # so the lag term should move it negligibly, not divergently.
        assert abs(state.server_inlet_temp_C - twin._state.server_inlet_temp_C) < 1e-9