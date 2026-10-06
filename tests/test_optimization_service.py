"""Optimizer service (T19): admission through the ArtifactGate, never block the event loop, never train
in a request.

The PPO model is replaced by a small fake so these run without loading a real policy;
DataCentreEnv, the service logic and the threading are real. With no admitted optimizer the
service answers HTTP 503 ``model_unavailable`` -- that is the expected, documented state.
"""

import asyncio
import time

import numpy as np
import pytest
from fastapi import HTTPException

from api.services import optimization_service as svc
from src import model_registry as mr
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
        assert (
            obs.shape == self.observation_space.shape
        ), f"Unexpected observation shape {obs.shape} for Box environment, please use {self.observation_space.shape}"
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
    monkeypatch.setattr(svc, "_last_unavailable_at", None)


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

    def test_an_unlisted_zip_is_refused_by_the_gate_and_never_opened(self, tmp_path, monkeypatch):
        (tmp_path / "ppo_model.zip").write_bytes(b"not a zip")
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path)
        opened = []
        monkeypatch.setattr(JointOptimizer, "load", classmethod(lambda cls, path: opened.append(path)))
        assert svc._load_saved_optimizer() is None
        assert opened == []  # the service has no path that reads a PPO file

    def test_the_shipped_quarantined_ppo_artifact_is_not_loadable(self, monkeypatch):
        monkeypatch.delenv("ARTIFACT_VERIFY", raising=False)
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", mr.PROJECT_ROOT / "models" / "optimizer")
        assert svc._load_saved_optimizer() is None

    def test_the_gate_is_what_refuses_the_shipped_ppo_artifact(self, monkeypatch):
        from src.artifacts import loaders

        seen = []
        real = loaders.authorize

        def spy(paths, *, artifact):
            try:
                return real(paths, artifact=artifact)
            except mr.ModelUnavailableError as exc:
                seen.append(exc)
                raise

        monkeypatch.setattr(loaders, "authorize", spy)
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", mr.PROJECT_ROOT / "models" / "optimizer")
        assert svc._load_saved_optimizer() is None
        assert seen and isinstance(seen[0], mr.ArtifactNotPromoted | mr.ArtifactFormatNotAllowed)


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
        assert all(
            k in rows[0] for k in ("pue", "wue", "cooling_power", "chilled_water_temp_C", "cooling_mode", "reward")
        )

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
    async def test_no_admitted_optimizer_is_http_503_model_unavailable_and_nothing_is_trained(self, monkeypatch):
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", mr.PROJECT_ROOT / "models" / "optimizer")

        def must_not_train(self, *a, **k):
            raise AssertionError("the API must never train in a request")

        monkeypatch.setattr(JointOptimizer, "train", must_not_train)
        with pytest.raises(HTTPException) as exc:
            await svc.run_optimization(0.5, 0.3, 0.2, 0.0, 1)
        assert exc.value.status_code == 503 and exc.value.detail == "model_unavailable"

    @pytest.mark.asyncio
    async def test_repeated_requests_do_not_re_evaluate_the_gate_every_time(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_load_saved_optimizer", lambda: calls.append(1))
        for _ in range(5):
            with pytest.raises(HTTPException):
                await svc._ensure_optimizer(0.5, 0.3, 0.2, 0.0)
        assert len(calls) == 1  # rate-limited by MODEL_RETRY_INTERVAL_S: no log / counter flood

    @pytest.mark.asyncio
    async def test_warm_up_never_trains_and_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "OPTIMIZER_MODEL_PATH", tmp_path / "missing")

        def must_not_train(self, *a, **k):
            raise AssertionError("warm_up must not train")

        monkeypatch.setattr(JointOptimizer, "train", must_not_train)
        await svc.warm_up()
        assert svc.get_optimizer() is None
