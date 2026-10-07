"""T29: the NumPy runtime reproduces SB3 ``predict(deterministic=True)``; export refuses a numerically different one.

Needs torch and stable-baselines3 (training side). The runtime itself is exercised without them in
tests/test_api_runtime_without_torch.py and tests/test_optimization_service.py.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from src.rl import export
from src.rl.env import DataCentreEnv, env_contract
from src.rl.numpy_policy import (
    EQUIVALENCE_TOLERANCE,
    NumpyPolicy,
    PolicySpecError,
    build_policy,
)

ROOT = Path(__file__).resolve().parent.parent
torch = pytest.importorskip("torch")
sb3 = pytest.importorskip("stable_baselines3")

pytestmark = pytest.mark.requires_sb3


def _model(*, activation=None, net_arch=None, seed=0, timesteps=512):
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    kwargs = {}
    if activation or net_arch:
        kwargs["policy_kwargs"] = {
            **({"activation_fn": activation} if activation else {}),
            **({"net_arch": net_arch} if net_arch else {}),
        }
    env = DummyVecEnv([lambda: DataCentreEnv(seed=seed)])
    model = PPO("MlpPolicy", env, n_steps=128, batch_size=64, n_epochs=2, seed=seed, device="cpu", verbose=0, **kwargs)
    model.learn(timesteps)
    return model


@pytest.fixture(scope="module")
def trained():
    return _model()


@pytest.fixture(scope="module")
def observations():
    return export.reference_observations(DataCentreEnv(seed=7), export.N_EQUIVALENCE_OBSERVATIONS, seed=3)


def _runtime(model, tmp_path, observations) -> NumpyPolicy:
    env = DataCentreEnv(seed=1)
    export.export_policy(
        model,
        tmp_path,
        contract=env_contract(),
        observation_names=list(env.observation_names),
        observations=observations,
    )
    return export.load_exported(tmp_path)


def test_there_are_exactly_1000_reference_observations(observations):
    assert observations.shape == (1000, 17) and observations.dtype == np.float32


def test_numpy_matches_sb3_within_1e_5_over_1000_observations(trained, observations, tmp_path):
    policy = _runtime(trained, tmp_path, observations)
    reference, _ = trained.predict(observations, deterministic=True)
    diff = np.max(np.abs(policy.predict(observations).astype(np.float64) - reference.astype(np.float64)))
    assert diff <= EQUIVALENCE_TOLERANCE == 1e-5
    assert diff < 1e-6  # in practice float32 rounding only


def test_single_observation_and_batch_agree(trained, observations, tmp_path):
    policy = _runtime(trained, tmp_path, observations)
    batch = policy.predict(observations[:5])
    for i in range(5):
        assert np.max(np.abs(policy.predict(observations[i]) - batch[i])) <= 1e-6  # BLAS kernels differ by rounding


def test_actions_are_clipped_to_the_action_space(trained, observations, tmp_path):
    policy = _runtime(trained, tmp_path, observations)
    extreme = np.full((4, 17), 50.0, dtype=np.float32)  # far outside the Box: the unclipped mean would leave [0, 1]
    out = policy.predict(extreme)
    assert np.all((out >= 0.0) & (out <= 1.0))
    reference, _ = trained.predict(extreme, deterministic=True)
    assert np.max(np.abs(out - reference)) <= EQUIVALENCE_TOLERANCE


@pytest.mark.parametrize("activation", ["tanh", "relu"])
@pytest.mark.parametrize("arch", [[16], {"pi": [32, 16], "vf": [8]}])
def test_other_architectures_and_activations_are_equivalent(activation, arch, observations, tmp_path):
    act = {"tanh": torch.nn.Tanh, "relu": torch.nn.ReLU}[activation]
    model = _model(activation=act, net_arch=arch, seed=2)
    policy = _runtime(model, tmp_path, observations)
    assert policy.activation == activation
    reference, _ = model.predict(observations, deterministic=True)
    assert np.max(np.abs(policy.predict(observations) - reference)) <= EQUIVALENCE_TOLERANCE


def test_export_refuses_a_numerically_different_runtime_and_writes_nothing(
    trained, observations, tmp_path, monkeypatch
):
    real = export.build_policy

    def drifted(spec, arrays):
        arrays = {k: v.copy() for k, v in arrays.items()}
        arrays["out_bias"] = arrays["out_bias"] + np.float32(1e-3)
        return real(spec, arrays)

    monkeypatch.setattr(export, "build_policy", drifted)
    target = tmp_path / "out"
    with pytest.raises(export.ExportToleranceError, match="not exporting"):
        export.export_policy(
            trained,
            target,
            contract=env_contract(),
            observation_names=list(DataCentreEnv(seed=1).observation_names),
            observations=observations,
        )
    assert not target.exists()


def test_export_is_byte_reproducible(trained, observations, tmp_path):
    names = list(DataCentreEnv(seed=1).observation_names)
    for d in ("a", "b"):
        export.export_policy(
            trained, tmp_path / d, contract=env_contract(), observation_names=names, observations=observations
        )
    for name in ("policy.npz", "policy_spec.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_the_npz_is_plain_data_and_loads_without_pickle(trained, observations, tmp_path):
    _runtime(trained, tmp_path, observations)
    with np.load(tmp_path / "policy.npz", allow_pickle=False) as z:
        assert sorted(z.files) == [
            "hidden_0_bias",
            "hidden_0_weight",
            "hidden_1_bias",
            "hidden_1_weight",
            "out_bias",
            "out_weight",
        ]
        assert all(z[k].dtype == np.float32 for k in z.files)
    spec = json.loads((tmp_path / "policy_spec.json").read_text())
    assert spec["env_contract"] == env_contract() and spec["obs_normalization"] is None


def test_unsupported_policies_are_refused(observations, tmp_path):
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    env = DummyVecEnv([lambda: DataCentreEnv(seed=0)])
    sde = PPO(
        "MlpPolicy", env, n_steps=64, batch_size=32, use_sde=True, device="cpu", seed=0, verbose=0,
        policy_kwargs={"squash_output": True},
    )  # fmt: skip
    with pytest.raises(export.UnsupportedPolicyError):
        export.extract_arrays(sde)
    elu = _model(activation=torch.nn.ELU, seed=3)
    with pytest.raises(export.UnsupportedPolicyError, match="ELU"):
        export.extract_arrays(elu)


# ----------------------------------------------------------------------------- spec validation (no torch needed)


def _spec_and_arrays():
    rng = np.random.default_rng(0)
    spec = {
        "format": "ppo-mlp-numpy", "runtime_version": "numpy-mlp-1",
        "action_rule": "clip(action_net(policy_net(obs)), action_low, action_high)",
        "obs_normalization": None, "obs_dim": 3, "action_dim": 2, "hidden_sizes": [4], "activation": "tanh",
        "action_low": [0.0, 0.0], "action_high": [1.0, 1.0],
    }  # fmt: skip
    arrays = {
        "hidden_0_weight": rng.normal(size=(4, 3)).astype(np.float32),
        "hidden_0_bias": np.zeros(4, np.float32),
        "out_weight": rng.normal(size=(2, 4)).astype(np.float32),
        "out_bias": np.zeros(2, np.float32),
    }
    return spec, arrays


def test_a_valid_spec_builds_and_predicts():
    spec, arrays = _spec_and_arrays()
    assert build_policy(spec, arrays).predict(np.zeros(3, np.float32)).shape == (2,)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s, a: s.update(format="other"),
        lambda s, a: s.update(runtime_version="numpy-mlp-2"),
        lambda s, a: s.update(activation="elu"),
        lambda s, a: s.update(obs_normalization={"mean": 1}),
        lambda s, a: s.update(hidden_sizes=[]),
        lambda s, a: s.update(action_low=[0.0]),
        lambda s, a: a.pop("out_bias"),
        lambda s, a: a.update(extra=np.zeros(1, np.float32)),
        lambda s, a: a.update(out_bias=np.zeros(2, np.float64)),
        lambda s, a: a.update(out_bias=np.array([np.nan, 0.0], np.float32)),
        lambda s, a: a.update(hidden_0_weight=np.zeros((5, 3), np.float32)),
    ],
)
def test_an_inconsistent_spec_is_rejected(mutate):
    spec, arrays = _spec_and_arrays()
    mutate(spec, arrays)
    with pytest.raises(PolicySpecError):
        build_policy(spec, arrays)


def test_wrong_observation_size_is_rejected():
    spec, arrays = _spec_and_arrays()
    with pytest.raises(PolicySpecError):
        build_policy(spec, arrays).predict(np.zeros(4, np.float32))


def test_the_runtime_module_does_not_import_torch_sb3_or_tensorflow():
    code = (
        "import sys; sys.path.insert(0, %r); import src.rl.numpy_policy; "
        "bad = [m for m in ('torch','stable_baselines3','tensorflow') if m in sys.modules]; "
        "sys.exit(1 if bad else 0)"
    ) % str(ROOT)
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=120).returncode == 0
