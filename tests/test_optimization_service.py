"""Optimizer service (T29): the API serves only a ``promoted``, compatible, plain-data policy through the NumPy runtime.

Supersedes the T14 (load-first) and T19 (gate-only 503) versions of this file. Everything runs against a throw-away
project root with a REAL exported policy (random weights written by ``src.rl.export.npz_bytes``): the registry, the
ArtifactGate, the runtime, DataCentreEnv v2 and the threading are real; torch and stable-baselines3 are not needed.
With no promoted policy the service answers HTTP 503 ``model_unavailable``; a request never trains anything.
"""

import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException

from api.services import optimization_service as svc
from src import model_registry as mr
from src import versions
from src.artifacts import loaders
from src.rl import export
from src.rl.env import DataCentreEnv, env_contract, observation_schema
from src.rl.numpy_policy import ACTION_RULE, POLICY_FORMAT, RUNTIME_VERSION

MODEL_NAME = "ppo-p1-e2-ctest0001"


def _policy_files(directory: Path, model_id: str, *, seed: int = 0, hidden=(8, 8)) -> None:
    """Write a real policy_spec.json + policy.npz with random float32 weights."""
    rng = np.random.default_rng(seed)
    obs_dim = len(observation_schema())
    arrays, prev = {}, obs_dim
    for i, size in enumerate(hidden):
        arrays[f"hidden_{i}_weight"] = rng.normal(0, 0.5, (size, prev)).astype(np.float32)
        arrays[f"hidden_{i}_bias"] = rng.normal(0, 0.1, (size,)).astype(np.float32)
        prev = size
    arrays["out_weight"] = rng.normal(0, 0.5, (2, prev)).astype(np.float32)
    arrays["out_bias"] = rng.normal(0, 0.1, (2,)).astype(np.float32)
    spec = {
        "format": POLICY_FORMAT,
        "runtime_version": RUNTIME_VERSION,
        "action_rule": ACTION_RULE,
        "obs_normalization": None,
        "obs_dim": obs_dim,
        "action_dim": 2,
        "hidden_sizes": list(hidden),
        "activation": "tanh",
        "action_low": [0.0, 0.0],
        "action_high": [1.0, 1.0],
        "dtype": "float32",
        "env_contract": env_contract(),
        "observation_names": [n for n, _, _ in observation_schema()],
        "model_id": model_id,
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "policy.npz").write_bytes(export.npz_bytes(arrays))
    (directory / "policy_spec.json").write_bytes(export.canonical_spec_bytes(spec))


def _register(root: Path, status: str = "promoted", *, seed: int = 0) -> dict:
    version = f"s{seed}"
    model_id = f"{MODEL_NAME}-{version}"
    rel = f"models/candidates/ppo/{model_id}"
    _policy_files(root / rel, model_id, seed=seed)
    entry = mr.log_model(
        MODEL_NAME,
        version=version,
        kind="ppo",
        metrics={},
        data_source="synthetic: test",
        artifact_path=rel,
        params={"seed": seed},
        seeds=[seed],
        dataset_id=None,
        dataset_manifest_sha256=None,
    )
    if status != "candidate":
        entries = mr.read_registry()
        for e in entries:
            if e["model_id"] == entry["model_id"]:
                e["status"] = status
        mr.write_registry(entries)
    return entry


def _refresh_files(entry: dict) -> None:
    """Re-record the file hashes of ``entry`` (so only the check under test can refuse the artifact)."""
    entries = mr.read_registry()
    for e in entries:
        if e["model_id"] == entry["model_id"]:
            e["files"] = mr.file_digests(mr.artifact_files(entry["relative_path"]))
    mr.write_registry(entries)


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mr, "REGISTRY_PATH", tmp_path / "models" / "registry.json")
    for var in ("ARTIFACT_VERIFY", "ARTIFACT_COMPAT", "ENVIRONMENT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_SHA", "a" * 40)
    loaders.reset_for_tests()
    monkeypatch.setattr(svc, "_optimizer", None)
    monkeypatch.setattr(svc, "_train_lock", asyncio.Lock())
    monkeypatch.setattr(svc, "_last_unavailable_at", None)
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    yield tmp_path
    loaders.reset_for_tests()


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


# ----------------------------------------------------------------------------- admission


class TestAdmission:
    def test_an_empty_registry_serves_nothing(self):
        assert svc._load_saved_optimizer() is None

    @pytest.mark.parametrize("status", ["candidate", "rejected", "quarantined", "retired"])
    def test_only_promoted_policies_are_served(self, world, status):
        _register(world, status)
        assert svc._load_saved_optimizer() is None

    def test_a_promoted_compatible_policy_is_served_with_its_lineage(self, world):
        entry = _register(world, "promoted")
        served = svc._load_saved_optimizer()
        assert served is not None
        assert served.model_id == entry["model_id"]
        assert served.physics_version == versions.active_physics_version()
        assert served.environment_version == versions.ENV_VERSION
        action = served.policy.predict(np.full(len(observation_schema()), 0.5, dtype=np.float32))
        assert action.shape == (2,) and np.all((action >= 0) & (action <= 1))

    def test_the_newest_promoted_policy_wins_and_older_ones_are_not_a_fallback(self, world):
        _register(world, "promoted", seed=0)
        newest = _register(world, "promoted", seed=1)
        assert svc._load_saved_optimizer().model_id == newest["model_id"]
        target = world / newest["relative_path"] / "policy.npz"
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0xFF
        target.write_bytes(bytes(data))
        assert svc._load_saved_optimizer() is None  # tampered newest => unavailable, not silently the older one

    def test_a_tampered_file_is_refused_and_counted(self, world):
        entry = _register(world, "promoted")
        path = world / entry["relative_path"] / "policy_spec.json"
        path.write_bytes(path.read_bytes() + b" ")
        before = sum(loaders.failure_counts().values())
        assert svc._load_saved_optimizer() is None
        assert sum(loaders.failure_counts().values()) == before + 1

    @pytest.mark.parametrize(
        "field",
        [
            "environment_version",
            "observation_schema_hash",
            "action_semantics_version",
            "reward_version",
            "safety_envelope_version",
        ],
    )
    def test_an_incompatible_policy_is_refused(self, world, field):
        entry = _register(world, "promoted")
        entries = mr.read_registry()
        assert entries[-1]["model_id"] == entry["model_id"]
        entries[-1][field] = "stale"
        mr.write_registry(entries)
        assert svc._load_saved_optimizer() is None

    def test_a_spec_that_names_another_model_is_refused(self, world):
        entry = _register(world, "promoted")
        directory = world / entry["relative_path"]
        spec = json.loads((directory / "policy_spec.json").read_text())
        spec["model_id"] = "someone-else"
        (directory / "policy_spec.json").write_bytes(export.canonical_spec_bytes(spec))
        _refresh_files(entry)
        assert svc._load_saved_optimizer() is None

    def test_a_spec_with_the_wrong_environment_contract_is_refused(self, world):
        entry = _register(world, "promoted")
        directory = world / entry["relative_path"]
        spec = json.loads((directory / "policy_spec.json").read_text())
        spec["env_contract"]["observation_schema_hash"] = "0" * 64
        (directory / "policy_spec.json").write_bytes(export.canonical_spec_bytes(spec))
        _refresh_files(entry)
        assert svc._load_saved_optimizer() is None

    def test_an_sb3_zip_is_never_opened_by_the_api(self, world):
        entry = _register(world, "promoted")
        zip_path = world / entry["relative_path"] / "model.zip"
        zip_path.write_bytes(b"PK not a real zip")
        _refresh_files(entry)
        # the zip is now listed among the files, but the service authorises only the two plain-data files
        assert svc._load_saved_optimizer() is not None
        with pytest.raises(loaders.ArtifactFormatNotAllowed):
            loaders.authorize([zip_path], artifact="ppo_policy")

    def test_the_legacy_quarantined_ppo_zip_is_not_loadable(self, world):
        (world / "models" / "optimizer").mkdir(parents=True)
        (world / "models" / "optimizer" / "ppo_model.zip").write_bytes(b"PK-ppo")
        (world / "models" / "optimizer" / "config.json").write_text("{}")
        mr.log_model(
            "ppo_optimizer", metrics={}, data_source="synthetic", artifact_path="models/optimizer", status="quarantined"
        )
        assert svc._load_saved_optimizer() is None

    def test_a_corrupt_registry_serves_nothing_and_does_not_raise(self, world):
        (world / "models" / "registry.json").write_text("{not json")
        assert svc._load_saved_optimizer() is None


# ----------------------------------------------------------------------------- 503 and never training


class TestUnavailable:
    @pytest.mark.asyncio
    async def test_no_promoted_policy_is_http_503_model_unavailable_and_nothing_is_trained(self, monkeypatch):
        def must_not_train(*a, **k):
            raise AssertionError("the API must never train in a request")

        monkeypatch.setattr("src.optimizer.JointOptimizer.train", must_not_train)
        with pytest.raises(HTTPException) as exc:
            await svc.run_optimization(0.5, 0.3, 0.2, 0.0, 1)
        assert exc.value.status_code == 503 and exc.value.detail == "model_unavailable"
        assert isinstance(exc.value, svc.OptimizerUnavailableError) and exc.value.code == "model_unavailable"

    @pytest.mark.asyncio
    async def test_a_candidate_policy_is_503(self, world):
        _register(world, "candidate")
        with pytest.raises(svc.OptimizerUnavailableError):
            await svc._ensure_optimizer()

    @pytest.mark.asyncio
    async def test_repeated_requests_do_not_re_evaluate_the_gate_every_time(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_load_saved_optimizer", lambda: calls.append(1))
        for _ in range(5):
            with pytest.raises(HTTPException):
                await svc._ensure_optimizer(0.5, 0.3, 0.2, 0.0)
        assert len(calls) == 1  # rate-limited by MODEL_RETRY_INTERVAL_S: no log / counter flood

    @pytest.mark.asyncio
    async def test_warm_up_never_raises_and_admits_a_promoted_policy(self, world):
        await svc.warm_up()
        assert svc.get_optimizer() is None
        _register(world, "promoted")
        svc._last_unavailable_at = None
        await svc.warm_up()
        assert svc.get_optimizer() is not None


# ----------------------------------------------------------------------------- the rollout


class TestRunOptimization:
    @pytest.mark.asyncio
    async def test_rollout_returns_rows_summary_and_lineage(self, world):
        entry = _register(world, "promoted")
        rows, summary = await svc.run_optimization(0.5, 0.3, 0.2, 0.0, 2)
        assert len(rows) == 2 * svc.STEPS_PER_HOUR
        assert set(summary) == {
            "mean_pue", "mean_wue", "mean_cooling_power_kw", "total_water_consumed_L", "total_reward",
            "safety_violations", "model_id", "physics_version", "environment_version", "carbon_is_fallback",
        }  # fmt: skip
        assert summary["model_id"] == entry["model_id"]
        assert summary["physics_version"] == versions.active_physics_version()
        assert summary["environment_version"] == versions.ENV_VERSION
        assert isinstance(summary["carbon_is_fallback"], bool)
        for key in (
            "pue",
            "wue",
            "cooling_power",
            "chilled_water_temp_C",
            "cooling_mode",
            "reward",
            "shield_active",
            "applied_setpoint_C",
        ):
            assert key in rows[0]

    @pytest.mark.asyncio
    async def test_the_shield_is_part_of_the_rollout(self, world):
        _register(world, "promoted")
        rows, _ = await svc.run_optimization(0.5, 0.3, 0.2, 0.95, 1)  # drought scenario: the shield forces closed_loop
        assert {r["cooling_mode"] for r in rows} == {"closed_loop"} and all(r["shield_active"] for r in rows)

    @pytest.mark.asyncio
    async def test_the_policy_is_deterministic(self, world):
        _register(world, "promoted")
        served = await svc._ensure_optimizer()
        obs = np.linspace(0, 1, len(observation_schema()), dtype=np.float32)
        assert np.array_equal(served.policy.predict(obs), served.policy.predict(obs))

    @pytest.mark.asyncio
    async def test_rollout_does_not_block_the_event_loop(self, world, monkeypatch):
        _register(world, "promoted")
        served = await svc._ensure_optimizer()
        real = type(served.policy).predict

        def slow_predict(self, obs):
            time.sleep(0.003)  # BLOCKING on purpose, like real inference
            return real(self, obs)

        monkeypatch.setattr(type(served.policy), "predict", slow_predict)
        (rows, _), worst_stall = await _max_loop_stall(svc.run_optimization(0.5, 0.3, 0.2, 0.0, 24))
        assert len(rows) == 24 * svc.STEPS_PER_HOUR
        assert worst_stall < 0.25, f"event loop was blocked for {worst_stall:.3f}s"

    @pytest.mark.asyncio
    async def test_the_admitted_policy_has_the_sb3_like_adapter_shadow_mode_calls(self, world):
        _register(world, "promoted")
        served = await svc._ensure_optimizer()
        zeros = np.zeros(len(observation_schema()), dtype=np.float32)
        action, state = served._model.predict(zeros, deterministic=True)
        assert action.shape == (2,) and state is None
        with pytest.raises(ValueError):
            served._model.predict(zeros, deterministic=False)


def test_the_env_used_by_the_rollout_is_environment_v2():
    env = DataCentreEnv(max_steps=1)
    try:
        assert env.env_contract["env_version"] == versions.ENV_VERSION == "2"
    finally:
        env.close()
