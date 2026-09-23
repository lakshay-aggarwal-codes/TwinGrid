"""Tests that the observation space widened correctly in Phase 8 and that
reset()/step() stay internally consistent with it."""

import numpy as np

from src.optimizer import DataCentreEnv


class TestObservationSpaceShape:
    def test_reset_returns_matching_shape(self):
        env = DataCentreEnv()
        obs, info = env.reset()
        assert obs.shape == env.observation_space.shape == (9,)

    def test_step_returns_matching_shape(self):
        env = DataCentreEnv()
        env.reset()
        action = env.action_space.sample()
        obs, reward, term, trunc, info = env.step(action)
        assert obs.shape == (9,)
        assert isinstance(reward, float)
        assert "state" in info

    def test_observations_stay_within_declared_bounds(self):
        """The Box space declares low=0, high=1 -- normalisation bugs
        (e.g. a wrong OBS_RANGES entry) would silently produce
        out-of-bounds values that PPO would still technically accept."""
        env = DataCentreEnv()
        obs, _ = env.reset()
        for _ in range(20):
            action = env.action_space.sample()
            obs, *_ = env.step(action)
            assert np.all(obs >= 0.0) and np.all(obs <= 1.0), f"Observation out of [0,1] bounds: {obs}"