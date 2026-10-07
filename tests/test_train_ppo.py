"""T29: scripts/train_ppo.py -- config checks, naming, determinism per seed, registration, manifest completeness, rollback.

Training tests use configs/ppo/ppo_v2_tiny.json (two seeds, 512 timesteps) against a throw-away project root.
Needs torch and stable-baselines3 (training side).
"""

import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from src import model_registry as mr
from src.artifacts import loaders

ROOT = Path(__file__).resolve().parent.parent
pytest.importorskip("torch")
pytest.importorskip("stable_baselines3")

pytestmark = pytest.mark.requires_sb3


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tp = _load("t29_train_ppo", ROOT / "scripts" / "train_ppo.py")
BASELINE = ROOT / "configs" / "ppo" / "ppo_v2_baseline.json"
TINY = ROOT / "configs" / "ppo" / "ppo_v2_tiny.json"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mr, "REGISTRY_PATH", tmp_path / "models" / "registry.json")
    for var in ("ARTIFACT_VERIFY", "ARTIFACT_COMPAT", "ARTIFACT_PROFILE", "ENVIRONMENT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_SHA", "b" * 40)
    loaders.reset_for_tests()
    (tmp_path / "models").mkdir()
    yield tmp_path
    loaders.reset_for_tests()


def cfg_of(path: Path = TINY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_cfg(tmp_path: Path, cfg: dict) -> Path:
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- the shipped configs


def test_baseline_config_has_the_contract_fields_and_five_seeds():
    cfg = tp.load_config(BASELINE)
    assert cfg["seeds"] == [0, 1, 2, 3, 4]
    assert set(tp.REQUIRED_FIELDS) <= set(cfg)
    assert set(cfg["hyperparameters"]) == set(tp.PPO_HYPERPARAMETERS)  # the FULL PPO set
    assert cfg["n_envs"] == 4 and cfg["total_timesteps"] % (cfg["n_envs"] * cfg["hyperparameters"]["n_steps"]) == 0
    assert cfg["reward_weights"] == {"alpha": 0.5, "beta": 0.3, "gamma": 0.2}


def test_the_baseline_config_agrees_with_the_code_constants():
    cfg = tp.load_config(BASELINE)
    contract = tp.check_versions(cfg)
    assert contract["env_version"] == "2" and contract["physics_version"] == "1"
    assert cfg["physics_version"] == "1" and cfg["environment_version"] == "2"


def test_names_follow_the_pattern_and_share_one_config_hash():
    cfg = tp.load_config(BASELINE)
    ids = [tp.candidate_model_id(cfg, s) for s in cfg["seeds"]]
    assert len(set(ids)) == 5
    for seed, model_id in zip(cfg["seeds"], ids):
        assert re.fullmatch(rf"ppo-p1-e2-c[0-9a-f]{{8}}-s{seed}", model_id)
    assert len({i.rsplit("-s", 1)[0] for i in ids}) == 1


def test_the_config_hash_ignores_seeds_but_not_hyperparameters():
    a = cfg_of(BASELINE)
    b = copy.deepcopy(a)
    b["seeds"] = [9]
    assert tp.config_hash8(a) == tp.config_hash8(b)
    b["hyperparameters"]["learning_rate"] = 0.001
    assert tp.config_hash8(a) != tp.config_hash8(b)


# ----------------------------------------------------------------------------- abort rules (exit 2, nothing written)


@pytest.mark.parametrize("field", tp.REQUIRED_FIELDS)
def test_a_missing_contract_field_is_rejected(tmp_path, field):
    cfg = cfg_of()
    del cfg[field]
    with pytest.raises(tp.ConfigError, match=field):
        tp.load_config(write_cfg(tmp_path, cfg))


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda c: c.update(seeds=[]), "seeds"),
        (lambda c: c.update(seeds=[0, 0]), "distinct"),
        (lambda c: c.update(total_timesteps=0), "total_timesteps"),
        (lambda c: c.update(n_envs=-1), "n_envs"),
        (lambda c: c["reward_weights"].pop("beta"), "reward_weights"),
        (lambda c: c["hyperparameters"].pop("gae_lambda"), "full PPO set"),
        (lambda c: c["hyperparameters"].update(surprise=1), "unknown"),
        (lambda c: c["hyperparameters"].update(device="cuda"), "device"),
        (lambda c: c["hyperparameters"].update(activation="elu"), "activation"),
        (lambda c: c.update(water_stress_levels=[1.5]), "water_stress_levels"),
    ],
)
def test_invalid_configs_are_rejected(tmp_path, mutate, match):
    cfg = cfg_of()
    mutate(cfg)
    with pytest.raises(tp.ConfigError, match=match):
        tp.load_config(write_cfg(tmp_path, cfg))


@pytest.mark.parametrize(
    "field,value",
    [
        ("physics_version", "2"),
        ("environment_version", "1"),
        ("reward_version", "1"),
        ("action_semantics_version", "1"),
        ("safety_envelope_version", "1"),
        ("shield_version", "9"),
        ("scenario_set_id", "0" * 64),
        ("split_id", "f" * 64),
    ],
)
def test_training_aborts_when_a_version_or_id_differs_from_the_code(world, field, value, capsys):
    cfg = cfg_of()
    cfg[field] = value
    path = write_cfg(world, cfg)
    assert tp.main(["--config", str(path), "--no-run-record"]) == 2
    err = capsys.readouterr().err
    assert field in err or "content id" in err
    assert not (world / "models" / "candidates").exists() and not (world / "artifacts_training").exists()
    assert not (world / "models" / "registry.json").exists()


def test_a_missing_config_file_is_exit_2(world, capsys):
    assert tp.main(["--config", str(world / "nope.json")]) == 2
    assert "cannot read config" in capsys.readouterr().err


def test_check_only_writes_nothing_and_prints_the_names(world, capsys):
    assert tp.main(["--config", str(TINY), "--check-only"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["model_ids"] == [tp.candidate_model_id(cfg_of(), s) for s in (0, 1)]
    assert not (world / "models" / "candidates").exists()


# ----------------------------------------------------------------------------- determinism


def _carbon():
    from src.carbon_provider import load_carbon_signal

    return load_carbon_signal()


def _weights(model):
    return {k: v.detach().cpu().numpy().copy() for k, v in model.policy.state_dict().items()}


def test_tiny_training_is_deterministic_per_seed_on_the_same_machine():
    cfg = tp.load_config(TINY)
    carbon = _carbon()
    first, again, other = (_weights(tp.train_one(cfg, s, carbon)) for s in (0, 0, 1))
    assert first.keys() == again.keys()
    for k in first:
        assert np.array_equal(first[k], again[k]), k
    assert any(not np.array_equal(first[k], other[k]) for k in first), "different seeds must give different policies"


def test_the_exported_file_is_identical_for_the_same_seed(world):
    from src.rl import export
    from src.rl.env import DataCentreEnv, env_contract

    cfg = tp.load_config(TINY)
    carbon = _carbon()
    names = list(DataCentreEnv(seed=1).observation_names)
    obs = export.reference_observations(DataCentreEnv(seed=1), 64, seed=0)
    blobs = []
    for i in range(2):
        model = tp.train_one(cfg, 0, carbon)
        export.export_policy(model, world / f"o{i}", contract=env_contract(), observation_names=names, observations=obs)
        blobs.append((world / f"o{i}" / "policy.npz").read_bytes())
    assert blobs[0] == blobs[1]


# ----------------------------------------------------------------------------- end to end (tiny)


@pytest.fixture
def trained(world):
    assert tp.main(["--config", str(TINY), "--no-run-record"]) == 0
    return world


def _entries():
    return [e for e in mr.read_registry() if e["kind"] == "ppo"]


def test_one_candidate_per_seed_is_registered_with_status_candidate(trained):
    cfg = tp.load_config(TINY)
    assert [e["model_id"] for e in _entries()] == [tp.candidate_model_id(cfg, s) for s in cfg["seeds"]]
    assert {e["status"] for e in _entries()} == {"candidate"}
    for e in _entries():
        assert [h["action"] for h in e["history"]] == ["logged"] and e["history"][0]["to"] == "candidate"


def test_the_output_layout_matches_the_contract(trained):
    for e in _entries():
        d = trained / "models" / "candidates" / "ppo" / e["model_id"]
        assert sorted(p.name for p in d.iterdir()) == ["manifest.json", "policy.npz", "policy_spec.json"]
        t = trained / "artifacts_training" / e["model_id"]
        assert sorted(p.name for p in t.iterdir()) == ["model.zip", "train_config.json"]


def test_manifest_v2_is_complete_and_every_null_has_a_declared_reason(trained):
    for e in _entries():
        assert mr.validate_manifest(e) == []
        missing = [f for f in tp._MANIFEST_V2_FIELDS if f not in e]
        assert missing == [], missing
        reasons = e["metrics"]["null_reasons"]
        nulls = [f for f in tp._MANIFEST_V2_FIELDS if e[f] is None]
        assert nulls and set(nulls) <= set(reasons), set(nulls) - set(reasons)
        assert all(isinstance(reasons[f], str) and len(reasons[f]) > 15 for f in nulls)
        assert "no reason declared" not in json.dumps(reasons)
        # the fields that identify the environment are NOT null
        for f in ("physics_version", "physics_params_hash", "environment_version", "observation_schema_hash", "action_schema_hash",
                  "action_semantics_version", "reward_version", "safety_envelope_version", "scenario_set_id", "split_id",
                  "input_cadence_s", "package_versions", "training_config", "seeds"):  # fmt: skip
            assert e[f] not in (None, "", [], {}), f


def test_the_manifest_config_hash_equals_the_hash_of_train_config_json(trained):
    for e in _entries():
        raw = (trained / "artifacts_training" / e["model_id"] / "train_config.json").read_bytes()
        assert e["training_config"]["sha256"] == hashlib.sha256(raw).hexdigest()
        assert json.loads(raw) == e["training_config"]["json"]
        assert e["training_config"]["json"]["seed"] == e["seeds"][0]
        assert "seeds" not in e["training_config"]["json"]


def test_the_manifest_json_copy_is_the_registry_entry_and_files_verify(trained):
    for e in _entries():
        copy_ = json.loads((trained / "models" / "candidates" / "ppo" / e["model_id"] / "manifest.json").read_text())
        assert copy_ == e
        assert set(e["files"]) == {
            f"models/candidates/ppo/{e['model_id']}/{n}" for n in ("policy.npz", "policy_spec.json")
        }
        for rel, info in e["files"].items():
            assert info["sha256"] == mr.sha256_file(trained / rel)
        z = e["metrics"]["training_artifact"]
        assert z["path"].endswith("model.zip") and z["sha256"] == mr.sha256_file(trained / z["path"])
        assert z["path"] not in e["files"]  # the SB3 zip is training-only, never part of the API-loadable set


def test_the_equivalence_report_is_recorded_and_within_tolerance(trained):
    for e in _entries():
        eq = e["metrics"]["export"]["equivalence"]
        assert eq["n_observations"] == 1000 and eq["tolerance"] == 1e-5 and eq["max_abs_diff"] <= 1e-5


def test_candidates_are_not_servable_and_carry_no_quality_claim(trained):
    for e in _entries():
        with pytest.raises(loaders.ArtifactNotPromoted):
            loaders.authorize([trained / r for r in e["files"]], artifact="ppo_policy")
        assert "no statement is made about its quality or safety" in e["metrics"]["claim"]
        assert e["evaluation_ref"] is None


def test_training_the_same_config_twice_is_refused_not_duplicated(trained, capsys):
    assert tp.main(["--config", str(TINY), "--no-run-record"]) == 2
    assert "already exist" in capsys.readouterr().err
    assert len(_entries()) == 2


def test_rollback_reject_makes_a_candidate_unservable_and_keeps_history(trained):
    registry_cli = _load("t29_registry_cli", ROOT / "scripts" / "registry_cli.py")
    entries = mr.read_registry()
    victim = entries[0]["model_id"]
    mr.write_registry(registry_cli.transition(entries, victim, "rejected", actor="test", reason="rollback"))
    after = {e["model_id"]: e for e in mr.read_registry()}
    assert after[victim]["status"] == "rejected"
    assert [h["action"] for h in after[victim]["history"]][0] == "logged" and len(after[victim]["history"]) == 2


def test_a_failure_while_exporting_removes_its_output_and_registers_nothing(world, monkeypatch, capsys):
    from src.rl import export

    def boom(*a, **k):
        raise export.ExportToleranceError("simulated drift")

    monkeypatch.setattr(export, "export_policy", boom)
    assert tp.main(["--config", str(TINY), "--no-run-record"]) == 1
    assert "nothing registered" in capsys.readouterr().err
    assert not (world / "models" / "registry.json").exists() or _entries() == []
    for sub in ("models/candidates/ppo", "artifacts_training"):
        assert not (world / sub).exists() or list((world / sub).iterdir()) == []


# ----------------------------------------------------------------------------- recorded through T24


def test_the_run_is_recorded_through_the_t24_framework(world):
    for rel in (
        "configs/ppo/ppo_v2_tiny.json",
        "configs/scenarios/scenario_set_v2.json",
        "configs/splits/split_v2.json",
        "requirements.lock",
    ):
        (world / rel).parent.mkdir(parents=True, exist_ok=True)
        (world / rel).write_bytes((ROOT / rel).read_bytes())
    assert tp.main(["--config", str(world / "configs/ppo/ppo_v2_tiny.json"), "--run-id", "ppo-train-test"]) == 0
    run_dir = world / "reports" / "runs" / "ppo-train-test"
    assert json.loads((run_dir / "status.json").read_text())["state"] == "completed"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    cfg = tp.load_config(TINY)
    assert manifest["experiment"] == "ppo_training" and manifest["seeds"] == cfg["seeds"]
    assert manifest["scenario_set_id"] == cfg["scenario_set_id"] and manifest["split_id"] == cfg["split_id"]
    assert [a["model_id"] for a in manifest["artifacts"]] == [tp.candidate_model_id(cfg, s) for s in cfg["seeds"]]
    results = json.loads((run_dir / "results.json").read_text())
    assert results["summary"]["n_candidates"] == 2 and results["summary"]["all_status_candidate"] == "yes"
    assert results["summary"]["max_numpy_vs_sb3_abs_diff"] <= 1e-5
    assert "performance or safety" in results["summary"]["claim"]


# ----------------------------------------------------------------------------- the shipped baseline run


def test_the_shipped_registry_holds_five_baseline_candidates_with_lineage():
    cfg = tp.load_config(BASELINE)
    ids = {tp.candidate_model_id(cfg, s) for s in cfg["seeds"]}
    entries = {e["model_id"]: e for e in json.loads((ROOT / "models" / "registry.json").read_text())["artifacts"]}
    assert ids <= set(entries), f"missing candidates: {sorted(ids - set(entries))}"
    for model_id in ids:
        e = entries[model_id]
        assert e["kind"] == "ppo" and e["status"] in {"candidate", "rejected", "retired"}  # never promoted by T29
        assert e["history"][0]["action"] == "logged" and e["history"][0]["to"] == "candidate"
        raw = (ROOT / "artifacts_training" / model_id / "train_config.json").read_bytes()
        assert e["training_config"]["sha256"] == hashlib.sha256(raw).hexdigest()
        for rel, info in e["files"].items():
            assert info["sha256"] == mr.sha256_file(ROOT / rel), rel
        assert e["metrics"]["export"]["equivalence"]["max_abs_diff"] <= 1e-5
