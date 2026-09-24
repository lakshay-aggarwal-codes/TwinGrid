"""Optimizer service: load-first, never block the event loop, one-time fallback training.

The PPO model is replaced by a small fake so these run without training/loading a
real policy; DataCentreEnv, the service logic and the threading are real.
"""

import asyncio
import time

import numpy as np
import pytest

from api.services import optimization_service as svc
from src.optimizer import JointOptimizer


class _Space:
    def __init__(self, shape):
        self.shape = shape


class FakeModel:
    """Stands in for a stable-baselines3 PPO model."""

    def __init__(self, obs_shape=(9,), act_shape=(2,), delay=0.0):
        self.observation_space = _Space(obs_shape)
        self.action_space = _Space(act_shape)
        self.delay = delay

    def predict(self, obs, deterministic=True):
        assert obs.shape == self.observation_space.shape, (
            f"Unexpected observation shape {obs.shape} for Box environment, "
            f"please use {self.observation_space.shape}"
        )
        if self.delay:
            time.sleep(self.delay)  # BLOCKING on purpose, like real torch inference
        return np.array([0.5, 0.5], dtype=np.float32), None


def _optimizer_with(model) -> JointOptimizer:
    opt = JointOptimizer.__new__(JointOptimizer)  # skip __init__: no carbon-curve loading needed
    opt._model = model
    return opt


@pytest.fixture(autouse=True)
def _fresh_service_state(monkeypatch):
    monkeypatch.setattr(svc, "_optimizer", None)
    monkeypatch.setattr(svc, "_train_lock", asyncio.Lock())


async def _max_loop_stall(coro):
    """Run `coro` while a 10 ms heartbeat measures how long the event loop was blocked."""
    stop, gaps = asyncio.Event(), []

    async def heartbeat():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    hb = asyncio.create_task(heartbeat())
    try:
        result = await coro
    finally:
        stop.set()
        await hb
    return result, max(gaps)


class TestLoadSavedOptimizer:
    def test_missing_artifacts_return_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path / "does-not-exist")
        assert svc._load_saved_optimizer() is None

    def test_corrupt_model_returns_none_instead_of_raising(self, tmp_path, monkeypatch):
        (tmp_path / "ppo_model.zip").write_bytes(b"not a zip")
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path)

        def boom(cls, path):
            raise ValueError("corrupt")

        monkeypatch.setattr(JointOptimizer, "load", classmethod(boom))
        assert svc._load_saved_optimizer() is None

    def test_stale_8_dim_policy_is_rejected(self, tmp_path, monkeypatch):
        """models/optimizer/ppo_model.zip in the repo was trained with 8-dim
        observations; DataCentreEnv now emits 9. PPO.load() succeeds but predict()
        would fail on the first request, so it must be treated as not loadable."""
        (tmp_path / "ppo_model.zip").write_bytes(b"x")
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path)
        stale = _optimizer_with(FakeModel(obs_shape=(8,)))
        monkeypatch.setattr(JointOptimizer, "load", classmethod(lambda cls, path: stale))
        assert svc._load_saved_optimizer() is None

    def test_compatible_policy_is_accepted(self, tmp_path, monkeypatch):
        (tmp_path / "ppo_model.zip").write_bytes(b"x")
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path)
        good = _optimizer_with(FakeModel())
        monkeypatch.setattr(JointOptimizer, "load", classmethod(lambda cls, path: good))
        assert svc._load_saved_optimizer() is good


class TestRunOptimization:
    @pytest.mark.asyncio
    async def test_rollout_returns_rows_and_summary(self, monkeypatch):
        monkeypatch.setattr(svc, "_optimizer", _optimizer_with(FakeModel()))
        rows, summary = await svc.run_optimization(0.5, 0.3, 0.2, 0.0, 2)
        assert len(rows) == 2 * svc.STEPS_PER_HOUR
        assert set(summary) == {
            "mean_pue",
            "mean_wue",
            "mean_cooling_power_kw",
            "total_water_consumed_L",
            "total_reward",
            "safety_violations",
        }
        assert all(k in rows[0] for k in ("pue", "wue", "cooling_power", "chilled_water_temp_C", "cooling_mode", "reward"))

    @pytest.mark.asyncio
    async def test_rollout_does_not_block_the_event_loop(self, monkeypatch):
        # 288 predict() calls x 3 ms of blocking work ~ 0.9 s. Run on the loop this
        # would stall it for ~0.9 s (and /healthz with it); in a worker thread the
        # 10 ms heartbeat keeps ticking.
        monkeypatch.setattr(svc, "_optimizer", _optimizer_with(FakeModel(delay=0.003)))
        (rows, _), worst_stall = await _max_loop_stall(svc.run_optimization(0.5, 0.3, 0.2, 0.0, 24))
        assert len(rows) == 24 * svc.STEPS_PER_HOUR
        assert worst_stall < 0.25, f"event loop was blocked for {worst_stall:.3f}s"

    @pytest.mark.asyncio
    async def test_fallback_training_happens_once_in_a_thread(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path / "missing")
        trained = []

        def fake_train(self, total_timesteps=0, **kwargs):
            time.sleep(0.5)  # BLOCKING, like PPO.learn()
            trained.append(total_timesteps)
            self._model = FakeModel()

        monkeypatch.setattr(JointOptimizer, "train", fake_train)
        monkeypatch.setattr(JointOptimizer, "__init__", lambda self, **kw: None)

        async def five_concurrent_first_requests():
            return await asyncio.gather(*[svc.run_optimization(0.5, 0.3, 0.2, 0.0, 1) for _ in range(5)])

        results, worst_stall = await _max_loop_stall(five_concurrent_first_requests())
        assert trained == [svc.FALLBACK_TRAIN_TIMESTEPS]  # exactly once, despite 5 racing requests
        assert all(len(rows) == svc.STEPS_PER_HOUR for rows, _ in results)
        assert worst_stall < 0.25, f"training blocked the event loop for {worst_stall:.3f}s"

    @pytest.mark.asyncio
    async def test_warm_up_never_trains_and_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path / "missing")

        def must_not_train(self, *a, **k):
            raise AssertionError("warm_up must not train")

        monkeypatch.setattr(JointOptimizer, "train", must_not_train)
        await svc.warm_up()
        assert svc.get_optimizer() is None
