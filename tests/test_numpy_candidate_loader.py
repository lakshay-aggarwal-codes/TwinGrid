"""Task 9: the evaluation harness can admit frozen NumPy PPO candidates, and refuses stale or altered ones.

Pure numpy / stdlib: no torch, gymnasium or stable-baselines3 (the current contract is injected)."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from src.rl.candidate_loader import CandidateLoadError, load_numpy_candidates
from src.rl.numpy_policy import ACTION_RULE, POLICY_FORMAT, RUNTIME_VERSION

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = {
    "env_version": "2",
    "action_semantics_version": "2",
    "reward_version": "2",
    "shield_version": "1",
    "safety_envelope_version": "2",
    "observation_schema_hash": "o" * 64,
    "action_schema_hash": "a" * 64,
    "physics_version": "1",
}
WEIGHTS = {"alpha": 0.5, "beta": 0.3, "gamma": 0.2}
OBS = 4


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_candidate(root: Path, name: str, seed: int, *, contract=None, weights=None, tamper: bool = False) -> Path:
    d = root / name
    d.mkdir(parents=True)
    rng = np.random.default_rng(seed)
    arrays = {
        "hidden_0_weight": rng.normal(size=(8, OBS)).astype(np.float32),
        "hidden_0_bias": rng.normal(size=(8,)).astype(np.float32),
        "out_weight": rng.normal(size=(2, 8)).astype(np.float32),
        "out_bias": rng.normal(size=(2,)).astype(np.float32),
    }
    np.savez(d / "policy.npz", **arrays)
    spec = {
        "format": POLICY_FORMAT,
        "runtime_version": RUNTIME_VERSION,
        "action_rule": ACTION_RULE,
        "activation": "tanh",
        "obs_dim": OBS,
        "action_dim": 2,
        "hidden_sizes": [8],
        "action_low": [0.0, 0.0],
        "action_high": [1.0, 1.0],
        "obs_normalization": None,
        "model_id": name,
        "seed": seed,
        "env_contract": dict(contract or CONTRACT),
    }
    (d / "policy_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    manifest = {
        "model_id": name,
        "files": {
            f"x/{name}/policy.npz": {"sha256": _sha(d / "policy.npz")},
            f"x/{name}/policy_spec.json": {"sha256": _sha(d / "policy_spec.json")},
        },
        "training_config": {"json": {"seed": seed, "reward_weights": dict(weights or WEIGHTS)}},
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if tamper:
        (d / "policy.npz").write_bytes((d / "policy.npz").read_bytes() + b"0")
    return d


def load(root: Path, seeds=(0, 1), **kw):
    return load_numpy_candidates(root, seeds, expected_contract=CONTRACT, expected_weights=WEIGHTS, obs_dim=OBS, **kw)


def test_loads_one_candidate_per_registered_seed_and_acts_in_range(tmp_path):
    make_candidate(tmp_path, "c-s0", 0)
    make_candidate(tmp_path, "c-s1", 1)
    got = load(tmp_path)
    assert list(got) == [0, 1]
    a = got[1].policy_action(np.linspace(0, 1, OBS, dtype=np.float32), deterministic=True)
    assert a.shape == (2,) and a.dtype == np.float32 and np.all((a >= 0) & (a <= 1))
    assert (got[0]._alpha, got[0]._beta, got[0]._gamma) == (0.5, 0.3, 0.2)
    # deterministic: same observation, same action
    obs = np.full(OBS, 0.3, dtype=np.float32)
    assert np.array_equal(got[0].policy_action(obs), got[0].policy_action(obs))


@pytest.mark.parametrize(
    "key,value", [("reward_version", "1"), ("observation_schema_hash", "z" * 64), ("physics_version", "legacy-0")]
)
def test_stale_environment_contract_is_refused(tmp_path, key, value):
    make_candidate(tmp_path, "c-s0", 0, contract={**CONTRACT, key: value})
    with pytest.raises(CandidateLoadError, match="retrain"):
        load(tmp_path, seeds=(0,))


def test_different_reward_weights_are_refused(tmp_path):
    make_candidate(tmp_path, "c-s0", 0, weights={"alpha": 0.4, "beta": 0.4, "gamma": 0.2})
    with pytest.raises(CandidateLoadError, match="not comparable"):
        load(tmp_path, seeds=(0,))


def test_altered_files_are_refused(tmp_path):
    make_candidate(tmp_path, "c-s0", 0, tamper=True)
    with pytest.raises(CandidateLoadError, match="sha256"):
        load(tmp_path, seeds=(0,))


def test_missing_unregistered_and_duplicate_seeds_are_refused(tmp_path):
    make_candidate(tmp_path, "c-s0", 0)
    with pytest.raises(CandidateLoadError, match="missing candidates"):
        load(tmp_path, seeds=(0, 1))
    make_candidate(tmp_path, "c-s9", 9)
    with pytest.raises(CandidateLoadError, match="not a pre-registered"):
        load(tmp_path, seeds=(0,))
    other = tmp_path / "dup"
    make_candidate(other, "a-s0", 0)
    make_candidate(other, "b-s0", 0)
    with pytest.raises(CandidateLoadError, match="two candidates claim seed 0"):
        load(other, seeds=(0,))
    assert list(load(other, seeds=(0,), model_id_prefix="a-")) == [0]


def test_wrong_observation_size_is_refused(tmp_path):
    make_candidate(tmp_path, "c-s0", 0)
    with pytest.raises(CandidateLoadError, match="obs_dim"):
        load_numpy_candidates(tmp_path, (0,), expected_contract=CONTRACT, expected_weights=WEIGHTS, obs_dim=OBS + 1)


def test_shipped_candidates_record_the_current_version_constants_and_intact_files():
    """Cheap lineage check on the committed candidates (the schema hashes need gymnasium and are checked in the real run)."""
    from src import versions as v

    root = ROOT / "models" / "candidates" / "ppo"
    dirs = sorted(p for p in root.iterdir() if p.is_dir())
    assert len(dirs) == 5
    for d in dirs:
        spec = json.loads((d / "policy_spec.json").read_text(encoding="utf-8"))
        c = spec["env_contract"]
        assert (c["env_version"], c["reward_version"], c["action_semantics_version"]) == (
            v.ENV_VERSION,
            v.REWARD_VERSION,
            v.ACTION_SEMANTICS_VERSION,
        )
        assert (c["safety_envelope_version"], c["shield_version"]) == (v.SAFETY_ENVELOPE_VERSION, v.SHIELD_VERSION)
        assert c["physics_version"] == "1"
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        want = {Path(k).name: x["sha256"] for k, x in manifest["files"].items()}
        assert want == {"policy.npz": _sha(d / "policy.npz"), "policy_spec.json": _sha(d / "policy_spec.json")}
