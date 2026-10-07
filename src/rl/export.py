"""Export a trained SB3 PPO policy to plain data (T29). TRAINING SIDE ONLY: imports torch lazily; the API never imports this.

Two files are written to a candidate directory:

    policy.npz         float32 arrays ``hidden_<i>_weight/_bias``, ``out_weight``, ``out_bias``  (no pickle)
    policy_spec.json   layer sizes, activation, action bounds, the action rule, the environment contract
                       (versions + observation/action schema hashes) and the runtime version

``policy.npz`` is written byte-reproducibly (fixed archive timestamps) so that "same seed, same machine" can be
checked with a file hash. Export REFUSES to write when the NumPy runtime differs from SB3's
``predict(deterministic=True)`` by more than ``EQUIVALENCE_TOLERANCE`` over the reference observations
(``ExportToleranceError``): a numerically different runtime must not ship.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .numpy_policy import (
    ACTION_RULE,
    EQUIVALENCE_TOLERANCE,
    POLICY_FORMAT,
    RUNTIME_VERSION,
    SUPPORTED_ACTIVATIONS,
    NumpyPolicy,
    PolicySpecError,
    build_policy,
)

POLICY_NPZ = "policy.npz"
POLICY_SPEC = "policy_spec.json"
N_EQUIVALENCE_OBSERVATIONS = 1000
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ExportToleranceError(RuntimeError):
    """The NumPy runtime does not reproduce the SB3 policy within tolerance. Nothing was written."""


class UnsupportedPolicyError(ValueError):
    """The SB3 policy has a structure the NumPy runtime does not implement."""


def _activation_name(fn_class: type) -> str:
    name = fn_class.__name__.lower()
    if name not in SUPPORTED_ACTIVATIONS:
        raise UnsupportedPolicyError(
            f"activation {fn_class.__name__} is not supported (supported: {SUPPORTED_ACTIVATIONS})"
        )
    return name


def extract_arrays(model: Any) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """(spec fragment, arrays) of an SB3 ``PPO`` model with a plain ``MlpPolicy`` on a Box/Box problem."""
    import torch
    from gymnasium import spaces

    policy = model.policy
    if type(policy).__name__ != "ActorCriticPolicy":
        raise UnsupportedPolicyError(f"policy class {type(policy).__name__} is not supported")
    if type(policy.features_extractor).__name__ != "FlattenExtractor":
        raise UnsupportedPolicyError("only FlattenExtractor is supported")
    if getattr(policy, "squash_output", False):
        raise UnsupportedPolicyError("squash_output=True is not supported")
    if getattr(model, "_vec_normalize_env", None) is not None:
        raise UnsupportedPolicyError("VecNormalize observation statistics are not exported")
    if not isinstance(model.action_space, spaces.Box) or not isinstance(model.observation_space, spaces.Box):
        raise UnsupportedPolicyError("only Box observation and action spaces are supported")
    if getattr(policy, "share_features_extractor", True) is False:
        raise UnsupportedPolicyError("separate features extractors are not supported")

    seq = policy.mlp_extractor.policy_net
    layers = [m for m in seq if isinstance(m, torch.nn.Linear)]
    acts = [m for m in seq if not isinstance(m, torch.nn.Linear)]
    if not layers or len(acts) != len(layers) or any(type(a) is not type(acts[0]) for a in acts):
        raise UnsupportedPolicyError("policy_net must be Linear/activation pairs with one activation type")
    activation = _activation_name(type(acts[0]))

    def np32(t: Any) -> np.ndarray:
        return t.detach().cpu().numpy().astype(np.float32, copy=True)

    arrays: dict[str, np.ndarray] = {}
    for i, layer in enumerate(layers):
        arrays[f"hidden_{i}_weight"] = np32(layer.weight)
        arrays[f"hidden_{i}_bias"] = np32(layer.bias)
    arrays["out_weight"] = np32(policy.action_net.weight)
    arrays["out_bias"] = np32(policy.action_net.bias)

    spec = {
        "format": POLICY_FORMAT,
        "runtime_version": RUNTIME_VERSION,
        "action_rule": ACTION_RULE,
        "obs_normalization": None,
        "obs_dim": int(np.prod(model.observation_space.shape)),
        "action_dim": int(np.prod(model.action_space.shape)),
        "hidden_sizes": [int(layer.out_features) for layer in layers],
        "activation": activation,
        "action_low": [float(v) for v in np.asarray(model.action_space.low, dtype=np.float32).reshape(-1)],
        "action_high": [float(v) for v in np.asarray(model.action_space.high, dtype=np.float32).reshape(-1)],
        "dtype": "float32",
    }
    return spec, arrays


def npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """A ``.npz`` that ``numpy.load(..., allow_pickle=False)`` reads, with fixed entry order and timestamps."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name in sorted(arrays):
            info = zipfile.ZipInfo(f"{name}.npy", date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            inner = io.BytesIO()
            np.lib.format.write_array(inner, np.ascontiguousarray(arrays[name]), allow_pickle=False)
            zf.writestr(info, inner.getvalue())
    return buf.getvalue()


def canonical_spec_bytes(spec: Mapping[str, Any]) -> bytes:
    return (json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def reference_observations(env: Any, n: int = N_EQUIVALENCE_OBSERVATIONS, *, seed: int = 0) -> np.ndarray:
    """``n`` observations: half uniform over the Box [0, 1]^d (covers corners and unusual combinations), half taken
    from real environment trajectories under random actions (the one-hot / structured observations a policy sees)."""
    rng = np.random.default_rng(seed)
    d = int(np.prod(env.observation_space.shape))
    n_uniform = n // 2
    uniform = rng.uniform(0.0, 1.0, size=(n_uniform, d)).astype(np.float32)
    rolled: list[np.ndarray] = []
    obs, _ = env.reset(seed=int(rng.integers(0, 2**31 - 1)))
    while len(rolled) < n - n_uniform:
        rolled.append(np.asarray(obs, dtype=np.float32))
        obs, _r, terminated, truncated, _info = env.step(
            rng.uniform(0.0, 1.0, size=env.action_space.shape).astype(np.float32)
        )
        if terminated or truncated:
            obs, _ = env.reset(seed=int(rng.integers(0, 2**31 - 1)))
    return np.concatenate([uniform, np.stack(rolled)], axis=0)


def sb3_actions(model: Any, observations: np.ndarray) -> np.ndarray:
    actions, _ = model.predict(observations, deterministic=True)
    return np.asarray(actions, dtype=np.float32)


def max_abs_difference(model: Any, policy: NumpyPolicy, observations: np.ndarray) -> float:
    reference = sb3_actions(model, observations)
    ours = policy.predict(observations)
    return float(np.max(np.abs(reference.astype(np.float64) - ours.astype(np.float64))))


def verify_equivalence(
    model: Any, policy: NumpyPolicy, observations: np.ndarray, *, tolerance: float = EQUIVALENCE_TOLERANCE
) -> dict[str, Any]:
    diff = max_abs_difference(model, policy, observations)
    report = {"max_abs_diff": diff, "n_observations": int(len(observations)), "tolerance": float(tolerance)}
    if not diff <= tolerance:  # also catches NaN
        raise ExportToleranceError(
            f"NumPy policy differs from SB3 predict(deterministic=True) by {diff!r} > {tolerance!r} over "
            f"{len(observations)} observations; not exporting"
        )
    return report


def export_policy(
    model: Any,
    out_dir: Path,
    *,
    contract: Mapping[str, Any],
    observation_names: list[str],
    observations: np.ndarray,
    extra_spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write ``policy.npz`` and ``policy_spec.json`` into ``out_dir`` after the equivalence check passes.

    Returns ``{"equivalence": {...}, "files": {name: Path}}``. The directory is created only after verification.
    """
    spec, arrays = extract_arrays(model)
    spec["env_contract"] = dict(contract)
    spec["observation_names"] = list(observation_names)
    if len(observation_names) != spec["obs_dim"]:
        raise UnsupportedPolicyError("observation_names does not match the policy's observation size")
    if extra_spec:
        clash = set(extra_spec) & set(spec)
        if clash:
            raise ValueError(f"extra_spec may not override {sorted(clash)}")
        spec.update(extra_spec)

    payload = npz_bytes(arrays)
    # Verify the thing that will be written: parse the bytes back exactly as the API will.
    with np.load(io.BytesIO(payload), allow_pickle=False) as loaded:
        runtime = build_policy(spec, {k: loaded[k] for k in loaded.files})
    equivalence = verify_equivalence(model, runtime, observations)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / POLICY_NPZ).write_bytes(payload)
    (out_dir / POLICY_SPEC).write_bytes(canonical_spec_bytes(spec))
    return {"equivalence": equivalence, "files": {POLICY_NPZ: out_dir / POLICY_NPZ, POLICY_SPEC: out_dir / POLICY_SPEC}}


def load_exported(out_dir: Path) -> NumpyPolicy:
    """Load a directory written by ``export_policy`` with NO admission gate (tests / tooling only; the API uses the gate)."""
    spec = json.loads((out_dir / POLICY_SPEC).read_text(encoding="utf-8"))
    with np.load(out_dir / POLICY_NPZ, allow_pickle=False) as loaded:
        return build_policy(spec, {k: loaded[k] for k in loaded.files})


__all__ = [
    "ExportToleranceError",
    "PolicySpecError",
    "UnsupportedPolicyError",
    "export_policy",
    "extract_arrays",
    "load_exported",
    "max_abs_difference",
    "npz_bytes",
    "reference_observations",
    "verify_equivalence",
]
