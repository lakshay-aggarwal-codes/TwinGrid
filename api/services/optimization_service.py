"""Optimizer singleton + business logic for POST /api/optimize.

Nothing in here may block the event loop: model admission and the per-step policy rollout are synchronous,
CPU-bound work, so each one runs in a worker thread (``asyncio.to_thread``).

T29: the API serves ONLY a ``promoted``, compatible, plain-data policy through the NumPy runtime
(``src/rl/numpy_policy.py``). The process is locked to the ``api`` artifact profile (formats json / npz / keras);
an SB3 ``.zip`` is not loadable here, PyTorch and stable-baselines3 are not installed in the API image, and a
request never trains anything. The newest registry entry of kind ``ppo`` with status ``promoted`` is run through the
ArtifactGate (status, integrity, compatibility, format); if there is none, or it is rejected, ``/api/optimize``
answers ``503 model_unavailable`` (``model_load_failures_total{reason}`` counts the rejection). Candidates, rejected
and quarantined artifacts are never served; promotion is T30 (``scripts/registry_cli.py promote``). The 503 is
rate-limited internally (one gate evaluation per ``MODEL_RETRY_INTERVAL_S``) so a client hammering the endpoint
cannot flood the logs or the failure counter.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from api.errors import ApiError
from api.middleware.metrics import MODEL_INFERENCE_COUNT, registry
from src import model_registry as mr
from src.artifacts import loaders
from src.rl.env import DataCentreEnv, assert_env_contract, observation_schema
from src.rl.numpy_policy import NumpyPolicy, PolicySpecError, build_policy
from src.versions import ENV_VERSION

logger = logging.getLogger(__name__)

# The API process may never load a pickle container. Lock the artifact profile for the life of the
# process (ARTIFACT_PROFILE can no longer change it) and publish the artifact metrics.
loaders.lock_profile("api")
loaders.bind_prometheus(registry)

MODEL_UNAVAILABLE_DETAIL = "model_unavailable"
MODEL_RETRY_INTERVAL_S = 30.0
ARTIFACT_NAME = "ppo_policy"

# Legacy location of the quarantined SB3 artifact. Kept so existing callers/tests that set it keep working; since T29
# nothing reads it: the policy to serve comes from the registry (status ``promoted``), never from this path.
OPTIMIZER_MODEL_PATH = Path(os.getenv("OPTIMIZER_MODEL_PATH", "models/optimizer"))

STEPS_PER_HOUR = 12

_POLICY_FILES = ("policy_spec.json", "policy.npz")


class OptimizerUnavailableError(ApiError):
    """No admitted policy: HTTP 503 ``model_unavailable`` (problem type ``urn:twingrid:error:model_unavailable``)."""

    def __init__(self) -> None:
        super().__init__(503, "model_unavailable", MODEL_UNAVAILABLE_DETAIL)


class _NumpyModel:
    """Adapter exposing ``predict(obs, deterministic=True) -> (action, None)`` like an SB3 model (shadow mode calls it)."""

    def __init__(self, policy: NumpyPolicy) -> None:
        self._policy = policy

    def predict(self, obs: Any, deterministic: bool = True) -> tuple[np.ndarray, None]:
        if not deterministic:
            raise ValueError("the NumPy runtime serves deterministic actions only")
        return self._policy.predict(obs), None


@dataclass(frozen=True)
class ServedPolicy:
    """A promoted, gate-admitted policy and the lineage the API reports with its answers."""

    model_id: str
    policy: NumpyPolicy
    physics_version: str
    environment_version: str

    @property
    def _model(self) -> _NumpyModel:  # shadow-mode compatibility (api/services/shadow_mode_service.py)
        return _NumpyModel(self.policy)


_optimizer: Optional[ServedPolicy] = None
_train_lock = asyncio.Lock()  # name kept for compatibility: serialises the one-time admission check
_last_unavailable_at: Optional[float] = None


def get_optimizer() -> Optional[ServedPolicy]:
    """The admitted policy, or None if none has been admitted yet."""
    return _optimizer


def _promoted_policy_entry() -> Optional[dict[str, Any]]:
    """The newest registry entry of kind ``ppo`` with status ``promoted``, or None."""
    try:
        entries = mr.read_registry()
    except (OSError, ValueError):
        logger.warning("Model registry unreadable; no policy can be served")
        return None
    return next((e for e in reversed(entries) if e.get("kind") == "ppo" and e.get("status") == "promoted"), None)


def _load_saved_optimizer() -> Optional[ServedPolicy]:
    """BLOCKING. Admit the newest promoted policy through the ArtifactGate, or return None. Never raises.

    The gate checks status (``promoted`` only in the api profile), integrity (SHA-256 and size of both files),
    compatibility (every version and schema hash equals the running code) and format (json / npz only). Any refusal
    is counted in ``model_load_failures_total{reason}`` by the gate; startup continues and the feature reports itself
    unavailable.
    """
    entry = _promoted_policy_entry()
    if entry is None:
        logger.info("No promoted ppo policy in the registry; /api/optimize reports model_unavailable")
        return None
    files = entry.get("files") or {}
    try:
        spec_rel = next(r for r in files if r.endswith("/" + _POLICY_FILES[0]))
        npz_rel = next(r for r in files if r.endswith("/" + _POLICY_FILES[1]))
    except StopIteration:
        logger.warning("Promoted policy %s does not list %s", entry.get("model_id"), _POLICY_FILES)
        loaders.record_load_failure(ARTIFACT_NAME, "manifest")
        return None
    spec_path, npz_path = mr.PROJECT_ROOT / spec_rel, mr.PROJECT_ROOT / npz_rel
    try:
        grant = loaders.authorize([spec_path, npz_path], artifact=ARTIFACT_NAME)
        spec = loaders.load_json(spec_path, artifact=ARTIFACT_NAME, grant=grant)
        arrays = loaders.load_npz(npz_path, artifact=ARTIFACT_NAME, grant=grant)
        if spec.get("model_id") != entry.get("model_id"):
            raise PolicySpecError("policy_spec.json names a different model_id than the registry entry")
        assert_env_contract(spec.get("env_contract"), entry.get("physics_version"))
        policy = build_policy(spec, arrays)
        if policy.obs_dim != len(observation_schema(entry.get("physics_version"))) or policy.action_dim != 2:
            raise PolicySpecError("policy dimensions do not match the running environment")
    except loaders.ModelUnavailableError as exc:
        logger.warning("Policy %s unavailable: %s", entry.get("model_id"), exc.reason)
        return None
    except Exception as exc:  # noqa: BLE001 - a bad artifact must never take the API down
        logger.warning("Policy %s failed to load: %s", entry.get("model_id"), type(exc).__name__)
        loaders.record_load_failure(ARTIFACT_NAME, "load_error")
        return None
    logger.info("Serving promoted policy %s", entry["model_id"])
    return ServedPolicy(
        model_id=str(entry["model_id"]),
        policy=policy,
        physics_version=str(entry["physics_version"]),
        environment_version=str(entry.get("environment_version") or ENV_VERSION),
    )


def _raise_model_unavailable() -> None:
    raise OptimizerUnavailableError()


async def warm_up() -> None:
    """Best-effort admission check at startup. Never trains, never raises."""
    global _optimizer, _last_unavailable_at
    try:
        async with _train_lock:
            if _optimizer is None:
                _optimizer = await asyncio.to_thread(_load_saved_optimizer)
                if _optimizer is None:
                    _last_unavailable_at = time.monotonic()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Optimizer warm-up failed -- /api/optimize will report model_unavailable")


async def _ensure_optimizer(
    alpha: float = 0.5, beta: float = 0.3, gamma: float = 0.2, water_stress: float = 0.0
) -> ServedPolicy:
    """The admitted policy, else HTTP 503 ``model_unavailable``. Never trains in a request.

    ``alpha``/``beta``/``gamma``/``water_stress`` are unused (they fed the removed fallback training) and kept so
    existing callers keep working.
    """
    global _optimizer, _last_unavailable_at
    if _optimizer is not None:
        return _optimizer
    async with _train_lock:
        if _optimizer is not None:
            return _optimizer
        now = time.monotonic()
        if _last_unavailable_at is not None and now - _last_unavailable_at < MODEL_RETRY_INTERVAL_S:
            _raise_model_unavailable()
        _optimizer = await asyncio.to_thread(_load_saved_optimizer)
        if _optimizer is None:
            _last_unavailable_at = time.monotonic()
            _raise_model_unavailable()
        return _optimizer


def _rollout(
    served: ServedPolicy, alpha: float, beta: float, gamma: float, water_stress: float, hours: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """BLOCKING. Roll the policy out on a FRESH DataCentreEnv built from this call's own alpha/beta/gamma, so
    concurrent requests stay isolated. The environment applies the shield (contract 13.5): the policy's env action
    ``a_e`` goes to ``env.step``; the executed action, shield flag and applied actuator state come back in ``info``."""
    n_steps = hours * STEPS_PER_HOUR
    env = DataCentreEnv(
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        water_stress=water_stress,
        max_steps=n_steps,
        physics_version=served.physics_version,
    )
    rows: list[dict[str, Any]] = []
    try:
        obs, _ = env.reset()
        for _ in range(n_steps):
            action = served.policy.predict(obs)
            next_obs, reward, term, trunc, info = env.step(action)
            rows.append(
                {
                    **info["state"],
                    "chilled_water_temp_C": info["requested_setpoint_C"],
                    "cooling_mode": info["requested_mode"],
                    "applied_setpoint_C": info["applied_setpoint_C"],
                    "applied_mode": info["applied_mode"],
                    "shield_active": bool(info["shield_active"]),
                    "reward": reward,
                }
            )
            obs = next_obs
            if term or trunc:
                break
        carbon_is_fallback = bool(env.carbon_basis.get("is_fallback", True))
    finally:
        env.close()

    df = pd.DataFrame(rows)
    summary = {
        "mean_pue": float(df["pue"].mean()),
        "mean_wue": float(df["wue"].mean()),
        "mean_cooling_power_kw": float(df["cooling_power"].mean()),
        "total_water_consumed_L": float(df["water_consumed"].sum()),
        "total_reward": float(df["reward"].sum()),
        "safety_violations": _count_violations(df),
        # lineage of the answer (T29)
        "model_id": served.model_id,
        "physics_version": served.physics_version,
        "environment_version": served.environment_version,
        "carbon_is_fallback": carbon_is_fallback,
    }
    return df.to_dict("records"), summary


def _count_violations(df: pd.DataFrame) -> int:
    """Steps that breach THE SafetyEnvelope (inlet, outlet, PUE); NaN counts as a violation."""
    from src.optimizer import JointOptimizer

    return JointOptimizer._count_safety_violations(df)


async def run_optimization(
    alpha: float, beta: float, gamma: float, water_stress: float, hours: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Run the served policy, returning (raw_results, summary). The summary carries ``model_id``,
    ``physics_version``, ``environment_version`` and ``carbon_is_fallback``.

    Raises HTTP 503 ``model_unavailable`` when no promoted, compatible policy is admitted (see module docstring).

    Concurrency note: the rollout always uses a FRESH DataCentreEnv built from this call's own alpha/beta/gamma, so
    per-request results are isolated even under concurrent requests. The only shared mutable state is whether the
    policy has been admitted yet; ``_train_lock`` makes sure only one concurrent request evaluates that.
    Results still need api.serialization.to_jsonable before being stored or returned.
    """
    served = await _ensure_optimizer(alpha, beta, gamma, water_stress)
    MODEL_INFERENCE_COUNT.labels(model="ppo_optimizer").inc()
    return await asyncio.to_thread(_rollout, served, alpha, beta, gamma, water_stress, hours)
