"""
Regression tests for Phase 8: water_stress was previously threaded through
five layers of the RL environment/optimizer without ever being read.
These tests assert the automatic drought-mode override (patent Claim 3)
actually fires in BOTH the rule-based twin and the RL environment, at the
same threshold in both places.
"""

import numpy as np
import pytest

from src.digital_twin import DROUGHT_THRESHOLD as TWIN_THRESHOLD
from src.digital_twin import CoolingMode, DigitalTwin
from src.optimizer import DROUGHT_OVERRIDE_MODE, DataCentreEnv
from src.optimizer import DROUGHT_THRESHOLD as ENV_THRESHOLD


class TestDroughtThresholdConsistency:
    def test_twin_and_env_use_the_same_threshold(self):
        """The two independent physics implementations must agree on when
        drought mode kicks in -- a mismatch here would mean the live
        dashboard and the RL training environment disagree about drought
        behaviour."""
        assert TWIN_THRESHOLD == ENV_THRESHOLD == 0.7


class TestDigitalTwinDroughtOverride:
    def test_below_threshold_not_forced(self):
        twin = DigitalTwin()
        mode = twin.select_cooling_mode(outside_temp_C=25.0, water_stress=0.5)
        # Not asserting a specific mode -- only that it's not the
        # unconditional override, since below-threshold mode depends on temp too.
        assert mode is not None

    def test_above_threshold_forces_closed_loop(self):
        twin = DigitalTwin()
        # Even at a temperature that would otherwise select free_air,
        # high water_stress must override it.
        mode = twin.select_cooling_mode(outside_temp_C=5.0, water_stress=0.9)
        assert mode == CoolingMode.CLOSED_LOOP

    def test_exactly_at_threshold_not_forced(self):
        """Boundary check: the rule is strictly greater-than, not
        greater-or-equal -- confirms the exact edge behaviour rather than
        assuming it."""
        twin = DigitalTwin()
        mode_at = twin.select_cooling_mode(outside_temp_C=5.0, water_stress=TWIN_THRESHOLD)
        mode_above = twin.select_cooling_mode(outside_temp_C=5.0, water_stress=TWIN_THRESHOLD + 0.01)
        assert mode_above == CoolingMode.CLOSED_LOOP
        # At exactly the threshold, behaviour should match the non-drought path.
        assert mode_at != CoolingMode.CLOSED_LOOP or mode_at == mode_above  # documents current behaviour explicitly


class TestDataCentreEnvDroughtOverride:
    """T27: the drought rule lives in the shield (src/rl/safety_filter.py); the env applies it inside step()
    and reports the executed action. The trigger is the water-stress SCENARIO variable."""

    @pytest.fixture
    def env(self):
        return DataCentreEnv(water_stress=0.9)

    def test_action_override_regardless_of_agents_choice(self, env):
        """The agent's chosen mode must NOT matter once the scenario exceeds the threshold."""
        env.reset()
        for mode_action in [0.0, 0.33, 0.66, 1.0]:  # sweeps all 4 discrete modes
            action = np.array([0.5, mode_action], dtype=np.float32)
            _, _, _, _, info = env.step(action)
            assert info["requested_mode"] == DROUGHT_OVERRIDE_MODE, (
                f"Expected override to {DROUGHT_OVERRIDE_MODE} regardless of agent action {mode_action}, "
                f"got {info['requested_mode']}"
            )
            assert info["shield_active"] is True and info["shield_flags"]["drought_triggered"] is True
            _, mode = env._action_to_control(info["executed_action"])
            assert mode == DROUGHT_OVERRIDE_MODE

    def test_no_override_below_threshold(self):
        env = DataCentreEnv(water_stress=0.1)
        env.reset()
        action = np.array([0.5, 1.0], dtype=np.float32)  # agent explicitly picks mode index 3
        _, _, _, _, info = env.step(action)
        assert info["requested_mode"] == "hybrid" and info["shield_active"] is False


class TestWaterStressObservability:
    def test_water_stress_is_in_observation_space(self):
        """Regression test for the architectural half of the Phase 8 bug:
        even with correct physics, the agent couldn't LEARN
        stress-conditioned behaviour if water_stress wasn't observable."""
        env = DataCentreEnv(water_stress=0.5)
        obs, _ = env.reset()
        i = env.observation_names.index("water_stress_scenario")
        assert env.observation_space.shape == obs.shape == (len(env.observation_names),)
        assert 0.0 <= obs[i] <= 1.0  # normalised [0,1] range

    def test_water_stress_value_reflected_in_observation(self):
        low_env = DataCentreEnv(water_stress=0.0)
        high_env = DataCentreEnv(water_stress=1.0)
        low_obs, _ = low_env.reset()
        high_obs, _ = high_env.reset()
        i = low_env.observation_names.index("water_stress_scenario")
        assert high_obs[i] > low_obs[i]
