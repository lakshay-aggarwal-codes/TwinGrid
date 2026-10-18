"""Load frozen NumPy PPO candidates (``scripts/train_ppo.py`` output) for the policy-evaluation harness (Task 9).

``src.policy_evaluation.load_candidates`` only reads SB3/``JointOptimizer`` directories (``seed_<n>``). The candidates that
``scripts/train_ppo.py`` produces are different artifacts: ``models/candidates/ppo/<model_id>/{policy.npz,policy_spec.json,
manifest.json}``. This module adapts them WITHOUT changing the protocol: it only loads and refuses; it never evaluates,
promotes or registers anything.

Refusals (``CandidateLoadError``) -- a candidate is rejected, never "fixed up", when:
  * a file's SHA-256 differs from the one its manifest recorded (not the artifact that was logged);
  * the spec's recorded environment contract differs from the CURRENT code's contract (stale: train again);
  * its training physics differs from the protocol's;
  * its reward weights differ from the pre-registered weights (rewards would not be comparable);
  * its recorded seed is not one pre-registered training seed, or two candidates claim the same seed, or a seed is missing;
  * the observation size differs from the environment's.

Imports numpy and the standard library only (no torch / gymnasium): the current contract is passed in by the caller.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .numpy_policy import NumpyPolicy, PolicySpecError, build_policy

POLICY_NPZ = "policy.npz"
POLICY_SPEC = "policy_spec.json"
MANIFEST = "manifest.json"
WEIGHT_TOLERANCE = 1e-12


class CandidateLoadError(RuntimeError):
    """A candidate cannot be admitted to an evaluation."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class NumpyCandidate:
    """Duck-types the part of ``JointOptimizer`` the harness uses (``policy_action`` and the objective weights)."""

    model_id: str
    seed: int
    path: Path
    policy: NumpyPolicy
    _alpha: float
    _beta: float
    _gamma: float
    files_sha256: Mapping[str, str]

    def policy_action(self, obs: np.ndarray, *, deterministic: bool = True) -> np.ndarray:
        # The NumPy runtime is deterministic by construction (the SB3 deterministic ``predict``), so the flag is moot.
        return np.asarray(self.policy.predict(obs), dtype=np.float32)


def _load_one(
    d: Path, *, expected_contract: Mapping[str, str], expected_weights: Mapping[str, float], obs_dim: int | None
) -> NumpyCandidate:
    for name in (POLICY_NPZ, POLICY_SPEC, MANIFEST):
        if not (d / name).is_file():
            raise CandidateLoadError(f"{d}: missing {name}")
    manifest = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
    spec = json.loads((d / POLICY_SPEC).read_text(encoding="utf-8"))
    model_id = str(spec.get("model_id"))
    if manifest.get("model_id") != model_id:
        raise CandidateLoadError(f"{d}: manifest model_id {manifest.get('model_id')!r} != spec {model_id!r}")

    recorded = {Path(p).name: v.get("sha256") for p, v in (manifest.get("files") or {}).items()}
    actual = {POLICY_NPZ: _sha256(d / POLICY_NPZ), POLICY_SPEC: _sha256(d / POLICY_SPEC)}
    for name, digest in actual.items():
        if recorded.get(name) != digest:
            raise CandidateLoadError(f"{model_id}: {name} sha256 differs from the manifest (not the logged artifact)")

    contract = spec.get("env_contract")
    if not isinstance(contract, Mapping):
        raise CandidateLoadError(f"{model_id}: no env_contract recorded (pre-v2 artifact): retrain")
    stale = {k: (contract.get(k), v) for k, v in expected_contract.items() if contract.get(k) != v}
    if stale:
        raise CandidateLoadError(
            f"{model_id}: environment contract differs from the current code (recorded, current): {stale}. "
            "The candidate was trained for a different environment: retrain, do not evaluate."
        )

    cfg = (manifest.get("training_config") or {}).get("json") or {}
    weights = cfg.get("reward_weights") or {}
    for k in ("alpha", "beta", "gamma"):
        if k not in weights or abs(float(weights[k]) - float(expected_weights[k])) > WEIGHT_TOLERANCE:
            raise CandidateLoadError(
                f"{model_id}: reward weight {k}={weights.get(k)!r} differs from the pre-registered "
                f"{expected_weights[k]!r}: rewards are not comparable"
            )
    if cfg.get("seed") != spec.get("seed"):
        raise CandidateLoadError(
            f"{model_id}: training_config seed {cfg.get('seed')!r} != spec seed {spec.get('seed')!r}"
        )

    try:
        with np.load(d / POLICY_NPZ, allow_pickle=False) as loaded:
            policy = build_policy(spec, {k: loaded[k] for k in loaded.files})
    except PolicySpecError as exc:
        raise CandidateLoadError(f"{model_id}: {exc}") from exc
    if obs_dim is not None and policy.obs_dim != obs_dim:
        raise CandidateLoadError(f"{model_id}: obs_dim {policy.obs_dim} != environment observation size {obs_dim}")
    return NumpyCandidate(
        model_id=model_id,
        seed=int(spec["seed"]),
        path=d,
        policy=policy,
        _alpha=float(weights["alpha"]),
        _beta=float(weights["beta"]),
        _gamma=float(weights["gamma"]),
        files_sha256=actual,
    )


def load_numpy_candidates(
    candidates_dir: Path,
    training_seeds: Sequence[int],
    *,
    expected_contract: Mapping[str, str],
    expected_weights: Mapping[str, float],
    obs_dim: int | None = None,
    model_id_prefix: str | None = None,
) -> dict[int, NumpyCandidate]:
    """Return ``{training seed: candidate}`` for exactly the pre-registered seeds, or raise ``CandidateLoadError``.

    ``model_id_prefix`` selects one training run when several configs coexist (``ppo-p1-e2-cd2345024`` ...)."""
    root = Path(candidates_dir)
    if not root.is_dir():
        raise CandidateLoadError(f"{root} is not a directory")
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / POLICY_SPEC).is_file())
    if model_id_prefix:
        dirs = [p for p in dirs if p.name.startswith(model_id_prefix)]
    found: dict[int, NumpyCandidate] = {}
    for d in dirs:
        cand = _load_one(d, expected_contract=expected_contract, expected_weights=expected_weights, obs_dim=obs_dim)
        if cand.seed not in training_seeds:
            raise CandidateLoadError(f"{cand.model_id}: seed {cand.seed} is not a pre-registered training seed")
        if cand.seed in found:
            raise CandidateLoadError(
                f"two candidates claim seed {cand.seed} ({found[cand.seed].model_id}, {cand.model_id}); "
                "pass model_id_prefix to choose one training run"
            )
        found[cand.seed] = cand
    missing = [s for s in training_seeds if s not in found]
    if missing:
        raise CandidateLoadError(f"missing candidates for pre-registered training seeds {missing} in {root}")
    return {s: found[s] for s in training_seeds}
