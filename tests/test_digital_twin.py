"""
Tests for DigitalTwin class in digital_twin.py.

Tests simulation step(), is_safe(), and cooling mode physics.
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

from src.digital_twin import DigitalTwin, CoolingMode, DataCentreState, INLET_TEMP_MIN, INLET_TEMP_MAX, OUTLET_TEMP_MAX, PUE_MAX_SAFE


def _expected_cooling_kw(it_power_kw, base_cop, outside_temp_c, max_it_kw=500.0, humidity_pct=None):
    """Dynamic-COP formula documented in DigitalTwin._effective_cop, written out
    independently from its constants: -15% COP at full load, -1% per degC above
    20 degC, and for evaporative mode -0.5% per % humidity above 40%."""
    load = max(0.0, min(1.0, it_power_kw / max_it_kw))
    cop = base_cop * (1 - 0.15 * load) * (1 - 0.01 * max(0.0, outside_temp_c - 20.0))
    if humidity_pct is not None:
        cop *= 1 - 0.5 * 0.01 * max(0.0, humidity_pct - 40.0)
    return it_power_kw / max(cop, 0.5)


class TestDigitalTwin:
    """Test suite for DigitalTwin class."""

    def test_init_default_params(self):
        """Test DigitalTwin initialization with default parameters."""
        twin = DigitalTwin()
        
        assert twin._max_it_power_kw == 500.0
        assert twin._idle_power_fraction == 0.4
        assert twin._air_flow_m3_s == 8.0
        assert twin._cooling_mode == CoolingMode.CLOSED_LOOP
        assert isinstance(twin._time, datetime)
        assert twin._utilisation == 0.0
        assert twin._outside_temp_C == 25.0
        assert twin._water_consumed_cumulative_L == 0.0
        assert twin._humidity_pct == 50.0
        assert twin._water_pressure_bar == 3.0
        assert isinstance(twin._state, DataCentreState)

    def test_init_custom_params(self):
        """Test DigitalTwin initialization with custom parameters."""
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        twin = DigitalTwin(
            max_it_power_kw=1000.0,
            idle_power_fraction=0.3,
            air_flow_m3_s=10.0,
            initial_cooling_mode=CoolingMode.FREE_AIR,
            start_time=start_time
        )
        
        assert twin._max_it_power_kw == 1000.0
        assert twin._idle_power_fraction == 0.3
        assert twin._air_flow_m3_s == 10.0
        assert twin._cooling_mode == CoolingMode.FREE_AIR
        assert twin._time == start_time

    def test_compute_it_power(self, digital_twin):
        """Test IT power computation."""
        # Test various utilisation levels
        test_cases = [
            (0.0, 200.0),  # Idle power: 500 * 0.4 = 200
            (0.5, 350.0),  # 200 + (1-0.4) * 0.5 * 500 = 200 + 150 = 350
            (1.0, 500.0),  # Full power: 200 + (1-0.4) * 1.0 * 500 = 200 + 300 = 500
        ]
        
        for utilisation, expected_power in test_cases:
            power = digital_twin.compute_it_power(utilisation)
            assert abs(power - expected_power) < 0.001

    def test_compute_it_power_invalid_utilisation(self, digital_twin):
        """Test IT power computation with invalid utilisation values."""
        with pytest.raises(ValueError, match="Utilisation must be in \\[0, 1\\]"):
            digital_twin.compute_it_power(-0.1)
        
        with pytest.raises(ValueError, match="Utilisation must be in \\[0, 1\\]"):
            digital_twin.compute_it_power(1.1)

    def test_compute_outlet_temp(self, digital_twin):
        """Test outlet temperature computation."""
        inlet_temp = 20.0
        it_power = 400.0
        airflow = 8.0
        
        outlet_temp = digital_twin.compute_outlet_temp(inlet_temp, it_power, airflow)
        
        # Outlet temp should be higher than inlet temp
        assert outlet_temp > inlet_temp
        
        # Should be reasonable (not extremely high)
        assert outlet_temp < 100.0

    def test_compute_cooling_power_free_air(self, digital_twin):
        """Test cooling power computation for free air mode."""
        it_power = 400.0
        cooling_power = digital_twin.compute_cooling_power(
            it_power, CoolingMode.FREE_AIR, 25.0
        )
        
        # Free air should have high COP (low power consumption)
        expected_cooling = _expected_cooling_kw(it_power, 8.0, 25.0)  # dynamic COP
        assert abs(cooling_power - expected_cooling) < 0.001

    def test_compute_cooling_power_closed_loop(self, digital_twin):
        """Test cooling power computation for closed loop mode."""
        it_power = 400.0
        cooling_power = digital_twin.compute_cooling_power(
            it_power, CoolingMode.CLOSED_LOOP, 25.0
        )
        
        # Closed loop should have medium COP
        expected_cooling = _expected_cooling_kw(it_power, 4.5, 25.0)  # dynamic COP
        assert abs(cooling_power - expected_cooling) < 0.001

    def test_compute_cooling_power_evaporative(self, digital_twin):
        """Test cooling power computation for evaporative mode."""
        it_power = 400.0
        cooling_power = digital_twin.compute_cooling_power(
            it_power, CoolingMode.EVAPORATIVE, 25.0
        )
        
        # Evaporative should have lower COP (higher power consumption)
        expected_cooling = _expected_cooling_kw(it_power, 3.5, 25.0, humidity_pct=50.0)  # dynamic COP
        assert abs(cooling_power - expected_cooling) < 0.001

    def test_compute_cooling_power_hybrid(self, digital_twin):
        """Test cooling power computation for hybrid mode."""
        it_power = 400.0
        cooling_power = digital_twin.compute_cooling_power(
            it_power, CoolingMode.HYBRID, 25.0
        )
        
        # Hybrid should have medium COP
        expected_cooling = _expected_cooling_kw(it_power, 4.0, 25.0)  # dynamic COP
        assert abs(cooling_power - expected_cooling) < 0.001

    def test_compute_water_consumption_free_air(self, digital_twin):
        """Test water consumption for free air mode."""
        cooling_power = 50.0
        flow, consumed = digital_twin.compute_water_consumption(
            cooling_power, CoolingMode.FREE_AIR, 25.0
        )
        
        # Free air should have no water consumption
        assert consumed == 0.0
        assert flow >= 0

    def test_compute_water_consumption_evaporative(self, digital_twin):
        """Test water consumption for evaporative mode."""
        cooling_power = 100.0
        flow, consumed = digital_twin.compute_water_consumption(
            cooling_power, CoolingMode.EVAPORATIVE, 25.0
        )
        
        # Evaporative should have significant water consumption
        assert consumed > 0
        assert flow > 0

    def test_step_basic(self, digital_twin):
        """Test basic simulation step."""
        initial_time = digital_twin._time
        
        action = {
            "utilisation": 0.8,
            "outside_temp_C": 25.0,
            "cooling_mode": "closed_loop"
        }
        
        state = digital_twin.step(action)
        
        # Check that time advanced
        assert digital_twin._time > initial_time
        assert digital_twin._time == initial_time + timedelta(minutes=5)
        
        # Check that state was updated
        assert isinstance(state, DataCentreState)
        assert state.timestamp == digital_twin._time
        assert state.server_utilisation == 0.8
        assert state.outside_temp_C == 25.0
        assert state.cooling_mode == CoolingMode.CLOSED_LOOP

    def test_step_partial_action(self, digital_twin):
        """Test simulation step with partial action dict."""
        initial_utilisation = digital_twin._utilisation
        
        # Only update utilisation
        action = {"utilisation": 0.6}
        state = digital_twin.step(action)
        
        # Check that only utilisation changed
        assert state.server_utilisation == 0.6
        assert state.outside_temp_C == digital_twin._outside_temp_C  # Unchanged
        assert state.cooling_mode == digital_twin._cooling_mode  # Unchanged

    def test_step_invalid_utilisation(self, digital_twin):
        """Test simulation step with invalid utilisation."""
        action = {
            "utilisation": 1.5,  # Invalid
            "outside_temp_C": 25.0
        }
        
        with pytest.raises(ValueError, match="utilisation must be in \\[0, 1\\]"):
            digital_twin.step(action)

    def test_step_cooling_mode_string(self, digital_twin):
        """Test simulation step with cooling mode as string."""
        action = {
            "utilisation": 0.8,
            "outside_temp_C": 25.0,
            "cooling_mode": "evaporative"
        }
        
        state = digital_twin.step(action)
        assert state.cooling_mode == CoolingMode.EVAPORATIVE

    def test_step_cooling_mode_enum(self, digital_twin):
        """Test simulation step with cooling mode as enum."""
        action = {
            "utilisation": 0.8,
            "outside_temp_C": 25.0,
            "cooling_mode": CoolingMode.HYBRID
        }
        
        state = digital_twin.step(action)
        assert state.cooling_mode == CoolingMode.HYBRID

    def test_step_with_humidity_and_pressure(self, digital_twin):
        """Test simulation step with humidity and water pressure."""
        action = {
            "utilisation": 0.8,
            "outside_temp_C": 25.0,
            "humidity_pct": 60.0,
            "water_pressure_bar": 2.8
        }
        
        state = digital_twin.step(action)
        assert state.humidity_pct == 60.0
        assert state.water_pressure_bar == 2.8

    def test_is_safe_true(self, digital_twin):
        """Test is_safe() when conditions are safe."""
        # Set safe conditions
        digital_twin._state = DataCentreState(
            timestamp=datetime.now(),
            server_utilisation=0.8,
            outside_temp_C=25.0,
            server_inlet_temp_C=20.0,  # Within range [18, 27]
            server_outlet_temp_C=35.0,  # Below 45°C
            it_power_kw=400.0,
            cooling_power_kw=100.0,
            total_power_kw=500.0,
            pue=1.25,  # Below 2.0
            water_flow_lpm=50.0,
            water_consumed_L=100.0,
            wue=0.02,
            humidity_pct=50.0,
            water_pressure_bar=3.0,
            cooling_mode=CoolingMode.CLOSED_LOOP,
            anomaly=0
        )
        
        assert digital_twin.is_safe() is True

    def test_is_safe_false_inlet_too_low(self, digital_twin):
        """Test is_safe() when inlet temperature is too low."""
        digital_twin._state = DataCentreState(
            timestamp=datetime.now(),
            server_utilisation=0.8,
            outside_temp_C=25.0,
            server_inlet_temp_C=15.0,  # Below minimum 18°C
            server_outlet_temp_C=35.0,
            it_power_kw=400.0,
            cooling_power_kw=100.0,
            total_power_kw=500.0,
            pue=1.25,
            water_flow_lpm=50.0,
            water_consumed_L=100.0,
            wue=0.02,
            humidity_pct=50.0,
            water_pressure_bar=3.0,
            cooling_mode=CoolingMode.CLOSED_LOOP,
            anomaly=0
        )
        
        assert digital_twin.is_safe() is False

    def test_is_safe_false_inlet_too_high(self, digital_twin):
        """Test is_safe() when inlet temperature is too high."""
        digital_twin._state = DataCentreState(
            timestamp=datetime.now(),
            server_utilisation=0.8,
            outside_temp_C=25.0,
            server_inlet_temp_C=28.0,  # Above maximum 27°C
            server_outlet_temp_C=35.0,
            it_power_kw=400.0,
            cooling_power_kw=100.0,
            total_power_kw=500.0,
            pue=1.25,
            water_flow_lpm=50.0,
            water_consumed_L=100.0,
            wue=0.02,
            humidity_pct=50.0,
            water_pressure_bar=3.0,
            cooling_mode=CoolingMode.CLOSED_LOOP,
            anomaly=0
        )
        
        assert digital_twin.is_safe() is False

    def test_is_safe_false_outlet_too_high(self, digital_twin):
        """Test is_safe() when outlet temperature is too high."""
        digital_twin._state = DataCentreState(
            timestamp=datetime.now(),
            server_utilisation=0.8,
            outside_temp_C=25.0,
            server_inlet_temp_C=20.0,
            server_outlet_temp_C=50.0,  # Above maximum 45°C
            it_power_kw=400.0,
            cooling_power_kw=100.0,
            total_power_kw=500.0,
            pue=1.25,
            water_flow_lpm=50.0,
            water_consumed_L=100.0,
            wue=0.02,
            humidity_pct=50.0,
            water_pressure_bar=3.0,
            cooling_mode=CoolingMode.CLOSED_LOOP,
            anomaly=0
        )
        
        assert digital_twin.is_safe() is False

    def test_is_safe_false_pue_too_high(self, digital_twin):
        """Test is_safe() when PUE is too high."""
        digital_twin._state = DataCentreState(
            timestamp=datetime.now(),
            server_utilisation=0.8,
            outside_temp_C=25.0,
            server_inlet_temp_C=20.0,
            server_outlet_temp_C=35.0,
            it_power_kw=400.0,
            cooling_power_kw=100.0,
            total_power_kw=500.0,
            pue=2.5,  # Above maximum 2.0
            water_flow_lpm=50.0,
            water_consumed_L=100.0,
            wue=0.02,
            humidity_pct=50.0,
            water_pressure_bar=3.0,
            cooling_mode=CoolingMode.CLOSED_LOOP,
            anomaly=0
        )
        
        assert digital_twin.is_safe() is False

    def test_cooling_mode_physics_consistency(self, digital_twin):
        """Test that cooling mode physics are consistent."""
        it_power = 400.0
        outside_temp = 25.0
        
        # Test all cooling modes
        modes = [CoolingMode.FREE_AIR, CoolingMode.CLOSED_LOOP, CoolingMode.EVAPORATIVE, CoolingMode.HYBRID]
        cooling_powers = []
        water_consumptions = []
        
        for mode in modes:
            cooling_power = digital_twin.compute_cooling_power(it_power, mode, outside_temp)
            flow, consumed = digital_twin.compute_water_consumption(cooling_power, mode, outside_temp)
            
            cooling_powers.append(cooling_power)
            water_consumptions.append(consumed)
        
        # Free air should have lowest cooling power (highest COP)
        assert cooling_powers[0] == min(cooling_powers)
        
        # Free air should have zero water consumption
        assert water_consumptions[0] == 0.0
        
        # Evaporative should have highest water consumption
        assert water_consumptions[2] == max(water_consumptions)

    def test_energy_balance(self, digital_twin):
        """Test that energy balance is maintained."""
        action = {
            "utilisation": 0.8,
            "outside_temp_C": 25.0,
            "cooling_mode": "closed_loop"
        }
        
        state = digital_twin.step(action)
        
        # Check energy balance: total_power = it_power + cooling_power
        assert abs(state.total_power_kw - (state.it_power_kw + state.cooling_power_kw)) < 0.001

    def test_water_accumulation(self, digital_twin):
        """Test that water consumption accumulates correctly."""
        initial_water = digital_twin._water_consumed_cumulative_L
        
        # Take multiple steps
        for i in range(5):
            action = {
                "utilisation": 0.8,
                "outside_temp_C": 25.0,
                "cooling_mode": "evaporative"  # Uses water
            }
            digital_twin.step(action)
        
        # Water should have accumulated
        assert digital_twin._water_consumed_cumulative_L > initial_water

    def test_state_to_dict(self, digital_twin):
        """Test DataCentreState to_dict conversion."""
        state = digital_twin._state
        state_dict = state.to_dict()
        
        # Check that all fields are present
        expected_fields = [
            "timestamp", "server_utilisation", "outside_temp_C", "server_inlet_temp_C",
            "server_outlet_temp_C", "it_power_kw", "cooling_power_kw", "total_power_kw",
            "pue", "water_flow_lpm", "water_consumed_L", "wue", "humidity_pct",
            "water_pressure_bar", "cooling_mode", "anomaly"
        ]
        
        for field in expected_fields:
            assert field in state_dict
        
        # Check that cooling mode is converted to string
        assert isinstance(state_dict["cooling_mode"], str)

    def test_multiple_steps_consistency(self, digital_twin):
        """Test that multiple steps produce consistent results."""
        states = []
        
        # Take 10 steps
        for i in range(10):
            action = {
                "utilisation": 0.5 + 0.3 * np.sin(i * 0.5),
                "outside_temp_C": 20 + 10 * np.sin(i * 0.3),
                "cooling_mode": "closed_loop"
            }
            state = digital_twin.step(action)
            states.append(state)
        
        # Check that timestamps are monotonic
        timestamps = [state.timestamp for state in states]
        assert all(timestamps[i] < timestamps[i+1] for i in range(len(timestamps)-1))
        
        # Check that time intervals are consistent
        intervals = [(timestamps[i+1] - timestamps[i]).total_seconds() / 60 for i in range(len(timestamps)-1)]
        assert all(interval == 5.0 for interval in intervals)  # 5-minute intervals

    def test_extreme_conditions(self, digital_twin):
        """Test behavior under extreme conditions."""
        # Test extreme utilisation
        action = {
            "utilisation": 1.0,  # Maximum
            "outside_temp_C": 40.0,  # Very hot
            "cooling_mode": "evaporative"
        }
        
        state = digital_twin.step(action)
        
        # System should still function
        assert state.server_utilisation == 1.0
        assert state.outside_temp_C == 40.0
        assert state.it_power_kw > 0
        assert state.cooling_power_kw > 0

    def test_zero_conditions(self, digital_twin):
        """Test behavior with zero/near-zero conditions."""
        action = {
            "utilisation": 0.0,  # No load
            "outside_temp_C": 15.0,  # Cool outside
            "cooling_mode": "free_air"
        }
        
        state = digital_twin.step(action)
        
        # Should have minimal power consumption
        assert state.server_utilisation == 0.0
        assert state.it_power_kw > 0  # Still has idle power
        assert state.cooling_power_kw >= 0
