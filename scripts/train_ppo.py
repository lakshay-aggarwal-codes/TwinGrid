#!/usr/bin/env python3
"""Train PPO candidates on environment v2 and register them (T29). The only training entry point.

    python scripts\\train_ppo.py --config configs\\ppo\\ppo_v2_baseline.json
    python scripts\\train_ppo.py --config configs\\ppo\\ppo_v2_baseline.json --check-only

For every seed in the config one CANDIDATE is produced, named ``ppo-p<physics>-e<env>-c<cfg8>-s<seed>``:

    models/candidates/ppo/<model_id>/policy.npz          plain float32 arrays (no pickle)
    models/candidates/ppo/<model_id>/policy_spec.json    layers, activation, action rule, environment contract
    models/candidates/ppo/<model_id>/manifest.json       the registry's manifest-v2 entry (a copy; the registry is authoritative)
    artifacts_training/<model_id>/model.zip              the SB3 zip. Training-only: the API process cannot load it
    artifacts_training/<model_id>/train_config.json      exactly the training_config the manifest hashes
    models/registry.json                                 one ``candidate`` entry per seed (history[] starts with "logged")
    reports/runs/<run_id>/                               a T24 run recording the five candidates

Nothing here evaluates, promotes or claims anything about a candidate. A candidate is served only after T30 promotes it
(``scripts/registry_cli.py promote``). To undo a run: ``python scripts\\registry_cli.py reject <model_id> --reason ...``.

Rules enforced before anything is written (exit status 2):
  * every version in the config equals the code's constant (physics, environment, reward, action semantics, safety
    envelope, shield); the scenario-set and split ids equal the content ids of the config files on disk;
  * the config has every field of the contract; no candidate with the same name already exists.
Export refuses (exit 1, nothing registered) if the NumPy runtime differs from SB3 ``predict(deterministic=True)`` by
more than 1e-5 over 1 000 observations.

``cfg8`` is the first 8 hex characters of the SHA-256 of the canonical config WITHOUT ``seeds`` (all seeds of one
config share it); the per-candidate ``training_config`` is that config plus ``"seed": <n>``.

Exit status: 0 done; 1 failed after work started (partial output removed, nothing registered unless stated);
2 bad config or version mismatch (nothing written).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CANDIDATE_SUBDIR = Path("models") / "candidates" / "ppo"
TRAINING_SUBDIR = Path("artifacts_training")
EXPERIMENT_NAME = "ppo_training"

REQUIRED_FIELDS = (
    "physics_version",
    "environment_version",
    "reward_weights",
    "scenario_set_id",
    "split_id",
    "seeds",
    "total_timesteps",
    "hyperparameters",
    "n_envs",
)
# Present in the shipped configs; when present they must equal the code constants (they are part of the lineage).
VERSION_FIELDS = {
    "reward_version": "REWARD_VERSION",
    "action_semantics_version": "ACTION_SEMANTICS_VERSION",
    "safety_envelope_version": "SAFETY_ENVELOPE_VERSION",
    "shield_version": "SHIELD_VERSION",
}
PPO_HYPERPARAMETERS = (
    "policy",
    "net_arch",
    "activation",
    "learning_rate",
    "n_steps",
    "batch_size",
    "n_epochs",
    "gamma",
    "gae_lambda",
    "clip_range",
    "clip_range_vf",
    "normalize_advantage",
    "ent_coef",
    "vf_coef",
    "max_grad_norm",
    "use_sde",
    "sde_sample_freq",
    "target_kl",
    "device",
)
DATA_SOURCE = "synthetic: DataCentreEnv v2 (src/rl/env.py); no external dataset is read"


class ConfigError(ValueError):
    """Bad config or a version that differs from the code. Raised before anything is written."""


class TrainingError(RuntimeError):
    """Training or export failed after work started."""


# ----------------------------------------------------------------------------- configuration


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_config(path: Path) -> dict[str, Any]:
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc.strerror}") from None
    except ValueError:
        raise ConfigError(f"config {path} is not valid JSON") from None
    if not isinstance(cfg, dict):
        raise ConfigError("config must be a JSON object")
    missing = [k for k in REQUIRED_FIELDS if k not in cfg]
    if missing:
        raise ConfigError(f"config is missing fields: {', '.join(missing)}")
    seeds = cfg["seeds"]
    if not (
        isinstance(seeds, list)
        and seeds
        and all(isinstance(s, int) and not isinstance(s, bool) and s >= 0 for s in seeds)
    ):
        raise ConfigError("seeds must be a non-empty list of non-negative integers")
    if len(set(seeds)) != len(seeds):
        raise ConfigError("seeds must be distinct")
    for key in ("total_timesteps", "n_envs"):
        if not (isinstance(cfg[key], int) and not isinstance(cfg[key], bool) and cfg[key] > 0):
            raise ConfigError(f"{key} must be a positive integer")
    weights = cfg["reward_weights"]
    if not (isinstance(weights, dict) and set(weights) == {"alpha", "beta", "gamma"}):
        raise ConfigError("reward_weights must be an object with exactly alpha, beta, gamma")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in weights.values()):
        raise ConfigError("reward_weights must be non-negative numbers")
    hp = cfg["hyperparameters"]
    if not isinstance(hp, dict):
        raise ConfigError("hyperparameters must be an object")
    absent = [k for k in PPO_HYPERPARAMETERS if k not in hp]
    if absent:
        raise ConfigError(f"hyperparameters is missing the full PPO set: {', '.join(absent)}")
    unknown = sorted(set(hp) - set(PPO_HYPERPARAMETERS))
    if unknown:
        raise ConfigError(f"hyperparameters has unknown entries: {', '.join(unknown)}")
    if hp["policy"] != "MlpPolicy" or hp["activation"] not in ("tanh", "relu"):
        raise ConfigError("only policy=MlpPolicy with activation tanh or relu can be exported to the NumPy runtime")
    if hp["device"] != "cpu":
        raise ConfigError("device must be 'cpu' (training must be reproducible on the same machine)")
    levels = cfg.get("water_stress_levels", [0.0])
    if not (
        isinstance(levels, list) and levels and all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in levels)
    ):
        raise ConfigError("water_stress_levels must be a non-empty list of numbers in [0, 1]")
    return cfg


def check_versions(cfg: dict[str, Any]) -> dict[str, str]:
    """Abort (ConfigError) if any version or id in the config differs from the code. Returns the running contract."""
    from src import data_pipeline as dp
    from src import versions
    from src.rl.env import env_contract

    running = {
        "physics_version": versions.active_physics_version(),
        "environment_version": versions.ENV_VERSION,
    }
    for field, constant in VERSION_FIELDS.items():
        running[field] = getattr(versions, constant)
    differ = [(k, cfg[k], v) for k, v in running.items() if k in cfg and cfg[k] != v]
    if differ:
        detail = "; ".join(f"{k}: config {c!r} != code {v!r}" for k, c, v in differ)
        raise ConfigError(f"config versions differ from the code constants ({detail}); not training")
    contract = env_contract(cfg["physics_version"])
    if contract["physics_version"] != cfg["physics_version"]:
        raise ConfigError("physics_version of the config is not the one the environment builds")

    for key, loader, path_key in (
        ("scenario_set_id", dp.load_scenario_config, "scenario_set_path"),
        ("split_id", dp.load_split_config, "split_path"),
    ):
        if path_key in cfg:
            actual = dp.config_id(loader(REPO_ROOT / cfg[path_key]))
            if cfg[key] != actual:
                raise ConfigError(f"{key} {cfg[key]!r} is not the content id of {cfg[path_key]} ({actual!r})")
    return contract


def config_core(cfg: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in cfg.items() if k != "seeds"}


def config_hash8(cfg: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical(config_core(cfg)).encode("utf-8")).hexdigest()[:8]


def model_name(cfg: dict[str, Any]) -> str:
    return f"ppo-p{cfg['physics_version']}-e{cfg['environment_version']}-c{config_hash8(cfg)}"


def candidate_model_id(cfg: dict[str, Any], seed: int) -> str:
    return f"{model_name(cfg)}-s{seed}"


def training_params(cfg: dict[str, Any], seed: int) -> dict[str, Any]:
    return {**config_core(cfg), "seed": int(seed)}


# ----------------------------------------------------------------------------- training


def _make_policy_kwargs(hp: dict[str, Any]) -> dict[str, Any]:
    import torch

    return {
        "net_arch": hp["net_arch"],
        "activation_fn": {"tanh": torch.nn.Tanh, "relu": torch.nn.ReLU}[hp["activation"]],
    }


def train_one(cfg: dict[str, Any], seed: int, carbon: Any) -> Any:
    """Train one PPO model for ``seed``. Same seed + same machine + same package versions -> identical weights."""
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    from src.carbon_provider import carbon_basis
    from src.rl.env import DataCentreEnv

    w = cfg["reward_weights"]
    levels = cfg.get("water_stress_levels", [0.0])
    curve, basis = carbon.curve_by_site_local_hour, carbon_basis(carbon)

    def env_factory(i: int):
        def make() -> DataCentreEnv:
            return DataCentreEnv(
                alpha=w["alpha"],
                beta=w["beta"],
                gamma=w["gamma"],
                water_stress=float(levels[i % len(levels)]),
                physics_version=cfg["physics_version"],
                carbon_intensity_by_hour=curve,
                carbon_basis=basis,
            )

        return make

    hp = dict(cfg["hyperparameters"])
    policy = hp.pop("policy")
    hp.pop("activation")
    hp.pop("net_arch")
    hp.pop("device")
    previous_threads = torch.get_num_threads()
    previous_deterministic = torch.are_deterministic_algorithms_enabled()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    try:
        venv = DummyVecEnv([env_factory(i) for i in range(cfg["n_envs"])])
        try:
            model = PPO(
                policy,
                venv,
                seed=int(seed),
                device="cpu",
                verbose=0,
                policy_kwargs=_make_policy_kwargs(cfg["hyperparameters"]),
                **hp,
            )
            model.learn(total_timesteps=cfg["total_timesteps"])
        finally:
            venv.close()
    finally:
        torch.use_deterministic_algorithms(previous_deterministic)
        torch.set_num_threads(previous_threads)
    return model


def declared_null_reasons(entry_preview: dict[str, Any]) -> dict[str, str]:
    """Reason for every manifest field that is null. A null without a reason fails the run (contract: no silent nulls)."""
    reasons = {
        "dataset_id": "no dataset: the policy is trained on the synthetic DataCentreEnv v2 day (src/rl/env.py); dataset v2 "
        "does not exist yet (T25 needs owner-supplied cleaned inputs)",
        "dataset_manifest_sha256": "no dataset manifest: same reason as dataset_id",
        "evaluation_ref": "not evaluated: evaluation and promotion are T30",
        "compat_waiver": "no waiver: the candidate is fully compatible with the running code",
        "code_revision": "the code revision could not be determined (no git checkout and no GIT_SHA at training time)",
    }
    return {k: reasons.get(k, "no reason declared") for k, v in entry_preview.items() if v is None}


# ----------------------------------------------------------------------------- registration & recording


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def register_candidate(
    cfg: dict[str, Any],
    seed: int,
    *,
    cand_dir: Path,
    training_dir: Path,
    equivalence: dict[str, Any],
    carbon_basis: dict,
) -> dict[str, Any]:
    from src import model_registry as mr

    params = training_params(cfg, seed)
    model_id = candidate_model_id(cfg, seed)
    rel_train = Path(os.path.relpath(training_dir, mr.PROJECT_ROOT)).as_posix()
    zip_path = training_dir / "model.zip"
    preview = {
        "dataset_id": None,
        "dataset_manifest_sha256": None,
        "evaluation_ref": None,
        "compat_waiver": None,
        "code_revision": mr.current_code_revision(),
    }
    extra = {
        "null_reasons": declared_null_reasons(preview),
        "training_artifact": {
            "path": f"{rel_train}/model.zip",
            "sha256": mr.sha256_file(zip_path),
            "size": zip_path.stat().st_size,
            "format": "sb3_zip",
            "note": "training-only; the API process cannot load an SB3 zip",
        },
        "train_config_file": f"{rel_train}/train_config.json",
        "export": {"runtime_version": "numpy-mlp-1", "equivalence": equivalence},
        "carbon_basis": carbon_basis,
        "scenario_use": "lineage only: DataCentreEnv v2 generates its own synthetic day; scenario windows of the "
        "scenario set are not consumed during training",
        "claim": "candidate only; not evaluated, not promoted; no statement is made about its quality or safety",
    }
    entry = mr.log_model(
        model_name(cfg),
        version=f"s{seed}",
        kind="ppo",
        status="candidate",
        metrics=extra,
        data_source=DATA_SOURCE,
        artifact_path=str(cand_dir),
        params=params,
        seeds=[int(seed)],
        scenario_set_id=cfg["scenario_set_id"],
        split_id=cfg["split_id"],
        dataset_id=None,
        dataset_manifest_sha256=None,
        physics_version=cfg["physics_version"],
    )
    if entry["model_id"] != model_id:
        raise TrainingError(f"registry assigned {entry['model_id']!r}, expected {model_id!r}")
    undeclared = sorted(
        k for k, v in entry.items() if v is None and k not in extra["null_reasons"] and k in _MANIFEST_V2_FIELDS
    )
    if undeclared:
        raise TrainingError(f"{model_id}: manifest fields null without a declared reason: {undeclared}")
    _write_json(cand_dir / "manifest.json", entry)
    return entry


_MANIFEST_V2_FIELDS = (
    "model_id name kind status created_at_utc code_revision physics_version physics_params_hash environment_version "
    "observation_schema_hash action_schema_hash action_semantics_version reward_version safety_envelope_version "
    "training_config seeds dataset_id dataset_manifest_sha256 scenario_set_id split_id input_cadence_s package_versions "
    "files evaluation_ref compat_waiver history"
).split()


def _experiment(config: dict[str, Any], seeds: list[int], rng_factory: Any) -> dict[str, Any]:
    """T24 experiment: a pure summary of the candidates already written (no clock, no randomness, no writes)."""
    from src import model_registry as mr
    from src.repro import RESULTS_SCHEMA

    rows = []
    for seed in seeds:
        model_id = candidate_model_id(config, seed)
        manifest = json.loads(
            (mr.PROJECT_ROOT / CANDIDATE_SUBDIR / model_id / "manifest.json").read_text(encoding="utf-8")
        )
        files = manifest["files"]
        npz = next(v for k, v in files.items() if k.endswith("policy.npz"))
        eq = manifest["metrics"]["export"]["equivalence"]
        rows.append(
            [
                model_id,
                int(seed),
                manifest["status"],
                npz["sha256"],
                manifest["training_config"]["sha256"],
                float(eq["max_abs_diff"]),
                int(config["total_timesteps"]),
            ]
        )
    return {
        "schema": RESULTS_SCHEMA,
        "experiment": EXPERIMENT_NAME,
        "title": "PPO candidate generation (T29): lineage record, no evaluation",
        "seeds": list(seeds),
        "summary": {
            "n_candidates": len(rows),
            "all_status_candidate": "yes" if all(r[2] == "candidate" for r in rows) else "no",
            "max_numpy_vs_sb3_abs_diff": max(r[5] for r in rows),
            "numpy_tolerance": 1e-5,
            "claim": "candidates with recorded lineage; no performance or safety statement",
        },
        "tables": {
            "candidates": {
                "title": "Registered candidates",
                "columns": [
                    "model_id",
                    "seed",
                    "status",
                    "policy_npz_sha256",
                    "training_config_sha256",
                    "numpy_vs_sb3_max_abs_diff",
                    "total_timesteps",
                ],
                "rows": rows,
            }
        },
        "figures": {},
        "notes": [
            "Candidate generation only: no policy here was evaluated, promoted or compared with a baseline.",
            "The SB3 zips under artifacts_training/ are training-only; the API serves the NumPy export of a promoted policy.",
        ],
    }


def record_run(cfg_path: Path, cfg: dict[str, Any], model_ids: list[str], run_id: str | None) -> Any:
    from src import model_registry as mr
    from src.repro import experiments
    from src.repro.run import RunRequest, run

    experiments.register(EXPERIMENT_NAME, _experiment, replace=True)
    chosen = run_id or f"ppo-train-c{config_hash8(cfg)}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    request = RunRequest(
        experiment=EXPERIMENT_NAME,
        config_paths=[os.path.relpath(cfg_path, mr.PROJECT_ROOT).replace("\\", "/")],
        seeds=cfg["seeds"],
        artifacts=model_ids,
        scenario_set_id=cfg["scenario_set_id"],
        split_id=cfg["split_id"],
        run_id=chosen,
        argv=tuple(sys.argv),
    )
    return run(request, mr.PROJECT_ROOT)


# ----------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True, help=r"e.g. configs\ppo\ppo_v2_baseline.json")
    p.add_argument(
        "--check-only", action="store_true", help="validate the config and print the candidate names; write nothing"
    )
    p.add_argument("--run-id", help="id of the T24 run directory (default: ppo-train-c<cfg8>-<UTC time>)")
    p.add_argument("--no-run-record", action="store_true", help="skip the T24 run record (tests only)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    from src import model_registry as mr

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = (Path.cwd() / cfg_path).resolve()
    try:
        cfg = load_config(cfg_path)
        contract = check_versions(cfg)
        ids = [candidate_model_id(cfg, s) for s in cfg["seeds"]]
        taken = {e.get("model_id") for e in mr.read_registry()} if mr.REGISTRY_PATH.exists() else set()
        clash = [
            i
            for i in ids
            if i in taken
            or (mr.PROJECT_ROOT / CANDIDATE_SUBDIR / i).exists()
            or (mr.PROJECT_ROOT / TRAINING_SUBDIR / i).exists()
        ]
        if clash:
            raise ConfigError(
                f"candidate(s) already exist: {', '.join(clash)}. Reject them with scripts/registry_cli.py and delete "
                "their directories, or change the config (a changed config has a different cfg8)"
            )
    except ConfigError as exc:
        print(f"train_ppo: {exc}", file=sys.stderr)
        return 2
    if args.check_only:
        print(json.dumps({"cfg8": config_hash8(cfg), "model_ids": ids, "env_contract": contract}, indent=2))
        return 0

    import numpy as np  # noqa: F401  (fail early if the training stack is missing)

    from src.carbon_provider import carbon_basis as basis_of
    from src.carbon_provider import load_carbon_signal
    from src.rl import export
    from src.rl.env import DataCentreEnv

    carbon = load_carbon_signal()
    basis = basis_of(carbon)
    print(
        f"train_ppo: {len(ids)} candidates, {cfg['total_timesteps']} timesteps each, carbon is_fallback={basis.get('is_fallback')}"
    )

    written: list[Path] = []
    equivalence: dict[str, dict[str, Any]] = {}
    try:
        for seed, model_id in zip(cfg["seeds"], ids):
            cand_dir = mr.PROJECT_ROOT / CANDIDATE_SUBDIR / model_id
            training_dir = mr.PROJECT_ROOT / TRAINING_SUBDIR / model_id
            model = train_one(cfg, seed, carbon)
            observer = DataCentreEnv(
                physics_version=cfg["physics_version"],
                carbon_intensity_by_hour=carbon.curve_by_site_local_hour,
                carbon_basis=basis,
            )
            observations = export.reference_observations(observer, export.N_EQUIVALENCE_OBSERVATIONS, seed=int(seed))
            written += [cand_dir, training_dir]
            result = export.export_policy(
                model,
                cand_dir,
                contract=contract,
                observation_names=list(observer.observation_names),
                observations=observations,
                extra_spec={"model_id": model_id, "seed": int(seed)},
            )
            equivalence[model_id] = result["equivalence"]
            training_dir.mkdir(parents=True, exist_ok=True)
            model.save(str(training_dir / "model.zip"))
            (training_dir / "train_config.json").write_text(canonical(training_params(cfg, seed)), encoding="utf-8")
            print(f"  {model_id}: exported, numpy-vs-sb3 max abs diff {result['equivalence']['max_abs_diff']:.3e}")
    except Exception as exc:
        for path in written:
            shutil.rmtree(path, ignore_errors=True)
        print(
            f"train_ppo: failed before registration ({type(exc).__name__}: {exc}); output removed, nothing registered",
            file=sys.stderr,
        )
        return 1

    registered: list[str] = []
    try:
        for seed, model_id in zip(cfg["seeds"], ids):
            register_candidate(
                cfg,
                seed,
                cand_dir=mr.PROJECT_ROOT / CANDIDATE_SUBDIR / model_id,
                training_dir=mr.PROJECT_ROOT / TRAINING_SUBDIR / model_id,
                equivalence=equivalence[model_id],
                carbon_basis=basis,
            )
            registered.append(model_id)
    except Exception as exc:
        print(
            f"train_ppo: registration failed after {len(registered)} of {len(ids)} ({type(exc).__name__}: {exc}). "
            f"Registered so far: {registered}. Reject them with scripts/registry_cli.py reject.",
            file=sys.stderr,
        )
        return 1

    if not args.no_run_record:
        outcome = record_run(cfg_path, cfg, ids, args.run_id)
        print(
            f"train_ppo: T24 run {outcome.run_id}: {outcome.state}" + (f" ({outcome.error})" if outcome.error else "")
        )
        if outcome.state != "completed":
            return 1
    print("train_ppo: done. Candidates are NOT evaluated and NOT promoted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
