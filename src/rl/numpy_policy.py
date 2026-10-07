"""NumPy runtime for an exported PPO policy (T29).

The API process serves a policy without PyTorch or stable-baselines3. This module is the whole runtime: it
loads two plain-data files (``policy_spec.json`` and ``policy.npz``, allow_pickle=False) and reproduces
stable-baselines3's ``MlpPolicy.predict(obs, deterministic=True)``:

    features   = flatten(obs.astype(float32))                      (FlattenExtractor, no normalisation)
    hidden     = activation(Linear(...)) repeated for each layer    (the *policy* network only)
    mean       = action_net(hidden)
    action     = clip(mean, action_low, action_high)                (``squash_output`` is False for PPO's Box policy)

The deterministic action of a diagonal Gaussian is its mean, so ``log_std`` and the value network are not part
of the runtime. The returned vector is the *env action* ``a_e`` of contract 13.5; the shield is applied by the
environment (``DataCentreEnv.step``), never here.

Arithmetic is float32 end to end, as in PyTorch. ``tests/test_numpy_policy.py`` and ``export.verify_equivalence``
prove the maximum absolute difference to SB3 stays below ``EQUIVALENCE_TOLERANCE`` over 1 000 observations;
export refuses to write a policy that exceeds it.

This file must stay importable without torch, stable-baselines3 or tensorflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

RUNTIME_VERSION = "numpy-mlp-1"
POLICY_FORMAT = "ppo-mlp-numpy"
EQUIVALENCE_TOLERANCE = 1e-5
SUPPORTED_ACTIVATIONS = ("tanh", "relu")

# SB3's deterministic ``predict`` clips a Box action to the action space.
ACTION_RULE = "clip(action_net(policy_net(obs)), action_low, action_high)"


class PolicySpecError(ValueError):
    """The spec or the arrays are not a policy this runtime can run (or are inconsistent with each other)."""


def _activation(name: str):
    if name == "tanh":
        return np.tanh
    if name == "relu":
        return lambda x: np.maximum(x, np.float32(0.0))
    raise PolicySpecError(f"unsupported activation {name!r}; supported: {SUPPORTED_ACTIVATIONS}")


@dataclass(frozen=True)
class NumpyPolicy:
    """An MLP policy as plain arrays. Immutable: the arrays are read-only copies."""

    weights: tuple[np.ndarray, ...]  # hidden layers, each (out, in), float32
    biases: tuple[np.ndarray, ...]  # each (out,), float32
    out_weight: np.ndarray  # (action_dim, last hidden), float32
    out_bias: np.ndarray  # (action_dim,), float32
    activation: str
    action_low: np.ndarray
    action_high: np.ndarray

    @property
    def obs_dim(self) -> int:
        return int(self.weights[0].shape[1]) if self.weights else int(self.out_weight.shape[1])

    @property
    def action_dim(self) -> int:
        return int(self.out_weight.shape[0])

    def predict(self, obs: Any) -> np.ndarray:
        """Deterministic action(s). ``obs`` is (obs_dim,) or (n, obs_dim); the result has the matching leading shape."""
        x = np.asarray(obs, dtype=np.float32)
        single = x.ndim == 1
        if single:
            x = x[None, :]
        if x.ndim != 2 or x.shape[1] != self.obs_dim:
            raise PolicySpecError(f"observation must have {self.obs_dim} features, got shape {tuple(x.shape)}")
        act = _activation(self.activation)
        h = x
        for w, b in zip(self.weights, self.biases):
            h = act(h @ w.T + b)
        mean = h @ self.out_weight.T + self.out_bias
        out = np.clip(mean, self.action_low, self.action_high).astype(np.float32)
        return out[0] if single else out


def _array(arrays: Mapping[str, np.ndarray], key: str, shape: tuple[int, ...]) -> np.ndarray:
    if key not in arrays:
        raise PolicySpecError(f"policy.npz has no array {key!r}")
    a = np.asarray(arrays[key])
    if a.dtype != np.float32:
        raise PolicySpecError(f"{key}: dtype must be float32, got {a.dtype}")
    if a.shape != shape:
        raise PolicySpecError(f"{key}: shape {a.shape} does not match the spec {shape}")
    if not np.all(np.isfinite(a)):
        raise PolicySpecError(f"{key}: contains NaN or infinity")
    out = np.array(a, dtype=np.float32, copy=True)
    out.setflags(write=False)
    return out


def build_policy(spec: Mapping[str, Any], arrays: Mapping[str, np.ndarray]) -> NumpyPolicy:
    """Validate ``spec`` against ``arrays`` and construct the runtime. Raises ``PolicySpecError``."""
    if not isinstance(spec, Mapping):
        raise PolicySpecError("policy_spec.json must be an object")
    if spec.get("format") != POLICY_FORMAT:
        raise PolicySpecError(f"format must be {POLICY_FORMAT!r}, got {spec.get('format')!r}")
    if spec.get("runtime_version") != RUNTIME_VERSION:
        raise PolicySpecError(f"runtime_version {spec.get('runtime_version')!r} != {RUNTIME_VERSION!r}")
    if spec.get("action_rule") != ACTION_RULE:
        raise PolicySpecError("action_rule differs from this runtime's rule")
    if spec.get("obs_normalization") is not None:
        raise PolicySpecError("observation normalisation is not supported by this runtime")
    activation = spec.get("activation")
    _activation(str(activation))
    obs_dim, action_dim = spec.get("obs_dim"), spec.get("action_dim")
    hidden = spec.get("hidden_sizes")
    if not (isinstance(obs_dim, int) and isinstance(action_dim, int) and obs_dim > 0 and action_dim > 0):
        raise PolicySpecError("obs_dim and action_dim must be positive integers")
    if not (isinstance(hidden, list) and hidden and all(isinstance(h, int) and h > 0 for h in hidden)):
        raise PolicySpecError("hidden_sizes must be a non-empty list of positive integers")
    low, high = spec.get("action_low"), spec.get("action_high")
    if not (isinstance(low, list) and isinstance(high, list) and len(low) == len(high) == action_dim):
        raise PolicySpecError("action_low / action_high must be lists of length action_dim")

    weights: list[np.ndarray] = []
    biases: list[np.ndarray] = []
    prev = obs_dim
    for i, size in enumerate(hidden):
        weights.append(_array(arrays, f"hidden_{i}_weight", (size, prev)))
        biases.append(_array(arrays, f"hidden_{i}_bias", (size,)))
        prev = size
    expected = {f"hidden_{i}_{p}" for i in range(len(hidden)) for p in ("weight", "bias")} | {"out_weight", "out_bias"}
    extra = sorted(set(arrays) - expected)
    if extra:
        raise PolicySpecError(f"policy.npz has unexpected arrays: {extra}")
    return NumpyPolicy(
        weights=tuple(weights),
        biases=tuple(biases),
        out_weight=_array(arrays, "out_weight", (action_dim, prev)),
        out_bias=_array(arrays, "out_bias", (action_dim,)),
        activation=str(activation),
        action_low=np.asarray(low, dtype=np.float32),
        action_high=np.asarray(high, dtype=np.float32),
    )
