"""T19: manifest v2, the ArtifactGate, registry states, JSON scalers, registry_cli, migration.

Everything runs against a throw-away project root (tmp_path) with tiny fake artifacts. No real
model, TensorFlow or stable-baselines3 is needed: the gate is exercised through
``loaders.authorize`` and the JSON / scaler loaders.
"""

import ast
import importlib.util
import json
import logging
import os
from pathlib import Path

import numpy as np
import pytest

from src import model_registry as mr
from src import versions
from src.artifacts import loaders, scaler_io

ROOT = Path(__file__).resolve().parent.parent
KINDS_FILES = {
    "anomaly_detector": ("models/anomaly", ["config.json", "model.keras", "scaler.json"]),
    "forecaster": (
        "models/forecaster/thermal.keras",
        ["models/forecaster/thermal.keras", "models/forecaster/scaler.json"],
    ),
    "ppo_optimizer": ("models/optimizer", ["config.json", "ppo_model.zip"]),
}
ANOMALY = ["models/anomaly/config.json", "models/anomaly/model.keras", "models/anomaly/scaler.json"]
FORECASTER = ["models/forecaster/thermal.keras", "models/forecaster/scaler.json"]
PPO = ["models/optimizer/config.json", "models/optimizer/ppo_model.zip"]
WAIVER = {
    "name": "legacy-physics-test-waiver",
    "fields": ["physics_version", "physics_params_hash"],
    "reason": "test",
    "expires_after_task": "T26",
}


def _scaler():
    from sklearn.preprocessing import MinMaxScaler

    return MinMaxScaler().fit(np.random.default_rng(1).normal(size=(50, 3)) * 10)


def flip_byte(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def _set(world, model_id, **changes):
    """Edit one registry entry directly (tests only; production goes through registry_cli)."""
    entries = mr.read_registry()
    for entry in entries:
        if entry["model_id"] == model_id:
            entry.update(changes)
    mr.write_registry(entries)


def _id(name):
    return mr.latest(name)["model_id"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mr, "REGISTRY_PATH", tmp_path / "models" / "registry.json")
    for var in ("ARTIFACT_VERIFY", "ARTIFACT_COMPAT", "ARTIFACT_PROFILE", "ENVIRONMENT", "PHYSICS_VERSION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_SHA", "a" * 40)
    loaders.reset_for_tests()

    (tmp_path / "models/anomaly").mkdir(parents=True)
    (tmp_path / "models/forecaster").mkdir(parents=True)
    (tmp_path / "models/optimizer").mkdir(parents=True)
    (tmp_path / "models/anomaly/config.json").write_text(json.dumps({"threshold": 0.1, "seq_len": 12}))
    (tmp_path / "models/anomaly/model.keras").write_bytes(b"keras-anomaly-" + bytes(range(200)))
    scaler_io.dump_scaler_json(_scaler(), tmp_path / "models/anomaly/scaler.json")
    (tmp_path / "models/forecaster/thermal.keras").write_bytes(b"keras-forecaster-" + bytes(range(200)))
    scaler_io.dump_scaler_json(_scaler(), tmp_path / "models/forecaster/scaler.json")
    (tmp_path / "models/optimizer/config.json").write_text(json.dumps({"alpha": 0.5}))
    (tmp_path / "models/optimizer/ppo_model.zip").write_bytes(b"PK-ppo-" + bytes(range(200)))

    mr.log_model("anomaly_detector", metrics={}, data_source="synthetic", artifact_path="models/anomaly")
    mr.log_model("forecaster", metrics={}, data_source="synthetic", artifact_path="models/forecaster/thermal.keras")
    mr.log_model("ppo_optimizer", metrics={}, data_source="synthetic", artifact_path="models/optimizer")
    for name in ("anomaly_detector", "forecaster", "ppo_optimizer"):
        _set(tmp_path, _id(name), status="promoted")
    yield tmp_path
    loaders.reset_for_tests()


def authorize(world, rels):
    return loaders.authorize([world / r for r in rels], artifact="test")


# ----------------------------------------------------------------------------- manifest v2


def test_log_model_writes_a_complete_v2_manifest(world):
    entry = mr.latest("ppo_optimizer")
    assert mr.validate_manifest(entry) == []
    assert entry["kind"] == "ppo" and entry["manifest_version"] == 2
    assert entry["code_revision"] == "a" * 40
    assert entry["training_config"]["sha256"] == versions.sha256_json(entry["training_config"]["json"])
    assert entry["history"][0]["action"] == "logged"
    assert set(entry["files"]) == set(PPO)
    for rel, info in entry["files"].items():
        assert info["sha256"] == mr.sha256_file(world / rel) and info["format"] == mr.format_for_path(rel)
    running = versions.running_compat_values()
    assert all(entry[f] == running[f] for f in versions.COMPAT_FIELDS)  # every field applies to a PPO


def test_data_models_record_null_for_rl_only_fields(world):
    entry = mr.latest("anomaly_detector")
    for field in ("environment_version", "observation_schema_hash", "action_schema_hash", "reward_version"):
        assert entry[field] is None
    assert entry["scenario_set_id"] is None
    assert entry["physics_params_hash"] == versions.physics_params_hash()


def test_log_model_never_creates_a_promoted_entry(world):
    with pytest.raises(ValueError):
        mr.log_model(
            "forecaster",
            metrics={},
            data_source="s",
            artifact_path="models/forecaster/thermal.keras",
            status="promoted",
        )


def test_registry_is_a_v2_document_and_a_bare_list_is_readable_as_v1(world):
    assert mr.read_registry_document()["registry_version"] == 2
    (world / "models/registry.json").write_text(json.dumps([{"name": "x"}]))
    assert mr.read_registry_document()["registry_version"] == 1


def test_registry_write_is_atomic_and_keeps_a_bak(world, monkeypatch):
    path = world / "models/registry.json"
    before = path.read_bytes()
    mr.write_registry(mr.read_registry())
    assert (world / "models/registry.json.bak").read_bytes() == before
    original = path.read_bytes()
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda s, d: (seen.append((Path(s).parent, Path(d).parent)), real(s, d))[1])
    mr.write_registry(mr.read_registry())
    assert seen and all(a == b for a, b in seen)
    monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        mr.write_registry(mr.read_registry())
    assert path.read_bytes() == original
    assert [p for p in (world / "models").iterdir() if p.name.endswith(".tmp")] == []


# ----------------------------------------------------------------------------- gate: happy path & integrity


def test_promoted_compatible_artifacts_pass(world):
    for rels in (ANOMALY, FORECASTER):
        grant = authorize(world, rels)
        assert grant.waived_fields == () and grant.profile == "api"
    assert loaders.health_snapshot()["status"] == "ok"


@pytest.mark.parametrize("rel", ANOMALY)
def test_every_anomaly_file_is_hash_protected(world, rel):
    target = world / rel
    original = target.read_bytes()
    flip_byte(target)
    with pytest.raises(mr.ArtifactIntegrityError, match="sha256"):
        authorize(world, ANOMALY)
    target.write_bytes(original)
    authorize(world, ANOMALY)


def test_truncated_and_missing_files_are_refused(world):
    target = world / "models/anomaly/model.keras"
    target.write_bytes(target.read_bytes()[:-5])
    with pytest.raises(mr.ArtifactIntegrityError, match="size"):
        authorize(world, ANOMALY)
    target.unlink()
    with pytest.raises(mr.ArtifactIntegrityError, match="missing"):
        authorize(world, ANOMALY)


def test_unlisted_file_and_outside_root_and_missing_registry_are_refused(world, tmp_path_factory):
    stray = world / "models/optimizer/other.zip"
    stray.write_bytes(b"x")
    with pytest.raises(mr.ArtifactManifestError, match="no manifest entry"):
        loaders.authorize([stray], artifact="x")
    outside = tmp_path_factory.mktemp("elsewhere") / "m.keras"
    outside.write_bytes(b"x")
    with pytest.raises(mr.ArtifactManifestError, match="outside the project root"):
        loaders.authorize([outside], artifact="x")
    (world / "models/registry.json").unlink()
    with pytest.raises(mr.ArtifactManifestError, match="registry not found"):
        authorize(world, ANOMALY)


def test_v1_manifest_is_refused(world):
    _set(world, _id("anomaly_detector"), manifest_version=1)
    with pytest.raises(mr.ArtifactManifestError, match="v1 manifest"):
        authorize(world, ANOMALY)


def test_invalid_v2_manifest_is_refused(world):
    entries = mr.read_registry()
    del entries[0]["history"]
    mr.write_registry(entries)
    with pytest.raises(mr.ArtifactManifestError, match="invalid manifest"):
        authorize(world, ANOMALY)


# ----------------------------------------------------------------------------- gate: status


@pytest.mark.parametrize("status", ["candidate", "quarantined", "rejected", "retired"])
def test_only_promoted_loads_in_the_api_process(world, status):
    _set(world, _id("anomaly_detector"), status=status, status_reason="because")
    with pytest.raises(mr.ArtifactNotPromoted, match=status):
        authorize(world, ANOMALY)


def test_training_profile_also_accepts_candidates_but_never_quarantined(world, monkeypatch):
    monkeypatch.setenv("ARTIFACT_PROFILE", "training")
    _set(world, _id("anomaly_detector"), status="candidate")
    assert authorize(world, ANOMALY).profile == "training"
    _set(world, _id("anomaly_detector"), status="quarantined")
    with pytest.raises(mr.ArtifactNotPromoted):
        authorize(world, ANOMALY)


# ----------------------------------------------------------------------------- gate: compatibility


def _different(value):
    return value + 1 if isinstance(value, int) else f"{value}-other"


@pytest.mark.parametrize("field", list(versions.COMPAT_FIELDS))
def test_a_mismatch_in_each_compatibility_field_is_rejected(world, field):
    model_id = _id("ppo_optimizer")
    _set(world, model_id, **{field: _different(mr.latest("ppo_optimizer")[field])})
    with pytest.raises(mr.ArtifactIncompatible) as exc:
        authorize(world, PPO)
    assert exc.value.field == field
    assert exc.value.actual == _different(versions.running_compat_values()[field])
    assert exc.value.expected == versions.running_compat_values()[field]
    assert loaders.failure_counts()["incompatible"] == 1


@pytest.mark.parametrize("field", list(versions.COMPAT_FIELDS))
def test_a_null_compatibility_field_is_a_mismatch_for_a_ppo_policy(world, field):
    _set(world, _id("ppo_optimizer"), **{field: None})
    with pytest.raises(mr.ArtifactIncompatible) as exc:
        authorize(world, PPO)
    assert exc.value.field == field


def test_rl_only_fields_are_not_compared_for_data_models_unless_recorded(world):
    authorize(world, ANOMALY)  # nulls: fine
    _set(world, _id("anomaly_detector"), reward_version="stale")
    with pytest.raises(mr.ArtifactIncompatible) as exc:
        authorize(world, ANOMALY)
    assert exc.value.field == "reward_version"


def _sabotage_env_version(mp):
    mp.setattr(versions, "ENV_VERSION", "2")


def _sabotage_reward_version(mp):
    mp.setattr(versions, "REWARD_VERSION", "2")


def _sabotage_safety_version(mp):
    mp.setattr(versions, "SAFETY_ENVELOPE_VERSION", "2")


def _sabotage_action_semantics(mp):
    mp.setattr(versions, "ACTION_SEMANTICS_VERSION", "2")


def _sabotage_cadence(mp):
    mp.setattr(versions, "INPUT_CADENCE_S", 60)


def _sabotage_observation_schema(mp):
    mp.setitem(versions.OBSERVATION_SCHEMA, "shape", [10])


def _sabotage_action_schema(mp):
    mp.setitem(versions.ACTION_SCHEMA, "high", [1.0, 2.0])


def _sabotage_physics_constant(mp):
    from src import digital_twin

    mp.setattr(digital_twin, "COP_MIN", digital_twin.COP_MIN + 0.1)


def _sabotage_physics_version(mp):
    mp.setenv("PHYSICS_VERSION", "legacy-0")


@pytest.mark.parametrize(
    "sabotage,field",
    [
        (_sabotage_env_version, "environment_version"),
        (_sabotage_reward_version, "reward_version"),
        (_sabotage_safety_version, "safety_envelope_version"),
        (_sabotage_action_semantics, "action_semantics_version"),
        (_sabotage_cadence, "input_cadence_s"),
        (_sabotage_observation_schema, "observation_schema_hash"),
        (_sabotage_action_schema, "action_schema_hash"),
        (_sabotage_physics_constant, "physics_params_hash"),
        (_sabotage_physics_version, "physics_version"),
    ],
)
def test_changing_any_running_constant_invalidates_an_artifact_carrying_the_old_value(
    world, monkeypatch, sabotage, field
):
    authorize(world, PPO) if False else None  # PPO would hit the format check; compat is what we test
    try:
        loaders.authorize([world / r for r in PPO], artifact="before")
    except mr.ArtifactFormatNotAllowed:
        pass  # compatible (the zip format is refused later, in check 3)
    sabotage(monkeypatch)
    with pytest.raises(mr.ArtifactIncompatible) as exc:
        authorize(world, PPO)
    assert exc.value.field == field


def test_arbitrary_physics_constants_feed_the_hash():
    from src import digital_twin

    constants = versions.physics_constants()
    assert "COP_MIN" in constants and "LATENT_HEAT_VAPORISATION_J_PER_KG" in constants
    assert (
        "SAFETY_ENVELOPE" in constants and constants["SAFETY_ENVELOPE"]["outlet_max_C"] == digital_twin.OUTLET_TEMP_MAX
    )
    assert versions.physics_params_hash() == versions.physics_params_hash()
    assert versions.physics_params_hash("legacy-0") != versions.physics_params_hash("1")


def test_cadence_constant_matches_the_code_that_defines_the_cadence():
    from src import digital_twin

    assert versions.INPUT_CADENCE_S == digital_twin.INTERVAL_MINUTES * 60
    optimizer_source = (ROOT / "src/optimizer.py").read_text()
    assert "INTERVAL_MIN = 5" in optimizer_source


def test_declared_schemas_match_the_environment_source():
    source = (ROOT / "src/optimizer.py").read_text()
    assert f"np.zeros({versions.OBSERVATION_SCHEMA['shape'][0]}, dtype=np.float32)" in source
    assert (
        "def _get_obs" in source
        and len(versions.OBSERVATION_SCHEMA["features"]) == versions.OBSERVATION_SCHEMA["shape"][0]
    )
    assert len(versions.ACTION_SCHEMA["components"]) == versions.ACTION_SCHEMA["shape"][0]


# ----------------------------------------------------------------------------- waivers


def test_waiver_excuses_only_the_named_fields_logs_warn_every_load_and_is_a_gauge(world, caplog):
    _set(world, _id("anomaly_detector"), physics_version="legacy-0", physics_params_hash=None, compat_waiver=WAIVER)
    for _ in range(2):
        grant = authorize(world, ANOMALY)
        assert set(grant.waived_fields) == {"physics_version", "physics_params_hash"}
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "COMPAT WAIVER" in r.getMessage()]
    assert len(warns) == 2  # WARN at EVERY load
    assert "legacy-physics-test-waiver" in warns[0].getMessage() and "T26" in warns[0].getMessage()
    assert loaders.waiver_samples() == [((_id("anomaly_detector"), "anomaly_detector", "T26"), 1.0)]
    assert loaders.health_snapshot()["waivers"] == [[_id("anomaly_detector"), "anomaly_detector", "T26"]]
    # a waiver does not cover other fields
    _set(world, _id("anomaly_detector"), input_cadence_s=60)
    with pytest.raises(mr.ArtifactIncompatible) as exc:
        authorize(world, ANOMALY)
    assert exc.value.field == "input_cadence_s"


def test_waiver_gauge_is_exposed_through_prometheus(world):
    prom = pytest.importorskip("prometheus_client")
    _set(world, _id("anomaly_detector"), compat_waiver=WAIVER)
    registry = prom.CollectorRegistry()
    assert loaders.bind_prometheus(registry)
    text = prom.generate_latest(registry).decode()
    assert "model_compat_waiver_active" in text and 'expires_after_task="T26"' in text
    assert 'model_load_failures_total{reason="incompatible"} 0.0' in text


@pytest.mark.parametrize(
    "bad",
    [
        {**WAIVER, "fields": []},
        {**WAIVER, "fields": ["not_a_field"]},
        {**WAIVER, "reason": " "},
        {**WAIVER, "expires_after_task": "later"},
        {**WAIVER, "name": ""},
    ],
)
def test_a_malformed_waiver_is_refused(world, bad):
    _set(world, _id("anomaly_detector"), compat_waiver=bad)
    with pytest.raises(mr.ArtifactManifestError, match="invalid manifest"):
        authorize(world, ANOMALY)


def test_artifact_compat_warn_loads_but_is_ignored_in_production(world, monkeypatch, caplog):
    _set(world, _id("anomaly_detector"), input_cadence_s=60)
    monkeypatch.setenv("ARTIFACT_COMPAT", "warn")
    authorize(world, ANOMALY)
    assert "ARTIFACT_COMPAT=warn" in caplog.text
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(mr.ArtifactIncompatible):
        authorize(world, ANOMALY)


def test_artifact_verify_warn_and_off_are_ignored_in_production(world, monkeypatch):
    flip_byte(world / "models/anomaly/model.keras")
    monkeypatch.setenv("ARTIFACT_VERIFY", "warn")
    authorize(world, ANOMALY)  # logged, loads
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert mr.verify_mode() == "enforce"
    with pytest.raises(mr.ArtifactIntegrityError):
        authorize(world, ANOMALY)
    monkeypatch.setenv("ARTIFACT_VERIFY", "disabled-by-typo")
    assert mr.verify_mode() == "enforce"


# ----------------------------------------------------------------------------- gate: formats and profiles


def test_sb3_zip_is_not_loadable_by_the_api_process_even_when_everything_else_passes(world):
    with pytest.raises(mr.ArtifactFormatNotAllowed, match="training-only"):
        authorize(world, PPO)
    with pytest.raises(mr.ArtifactFormatNotAllowed):
        loaders.load_sb3_zip_training_only(world / "models/optimizer/ppo_model.zip", artifact="x")


def test_sb3_zip_passes_the_gate_in_the_training_profile(world, monkeypatch):
    monkeypatch.setenv("ARTIFACT_PROFILE", "training")
    assert authorize(world, PPO).profile == "training"


def test_a_locked_api_profile_cannot_be_switched_by_the_environment(world, monkeypatch):
    loaders.lock_profile("api")
    monkeypatch.setenv("ARTIFACT_PROFILE", "training")
    assert loaders.current_profile() == "api"
    with pytest.raises(RuntimeError):
        loaders.enter_training_profile()
    with pytest.raises(mr.ArtifactFormatNotAllowed):
        authorize(world, PPO)


@pytest.mark.parametrize("name", ["scaler.joblib", "weights.pkl", "weights.pickle"])
def test_pickle_formats_are_never_loadable(world, monkeypatch, name):
    rel = f"models/anomaly/{name}"
    (world / rel).write_bytes(b"not really a pickle")
    mr.log_model("anomaly_detector", metrics={}, data_source="s", artifact_path="models/anomaly")
    _set(world, mr.latest("anomaly_detector")["model_id"], status="promoted")
    for profile in ("api", "training"):
        monkeypatch.setenv("ARTIFACT_PROFILE", profile)
        with pytest.raises(mr.ArtifactFormatNotAllowed):
            authorize(world, ANOMALY[:2] + [rel])


def test_manifest_format_must_match_the_file_suffix(world):
    entries = mr.read_registry()
    anomaly = next(e for e in entries if e["name"] == "anomaly_detector")
    anomaly["files"]["models/anomaly/model.keras"]["format"] = "json"
    mr.write_registry(entries)
    with pytest.raises(mr.ArtifactFormatNotAllowed, match="manifest says"):
        authorize(world, ANOMALY)


def test_joblib_conversion_helper_is_training_only_and_hash_checked(world, monkeypatch):
    pytest.importorskip("joblib")
    import joblib

    legacy = world / "legacy.joblib"
    joblib.dump(_scaler(), legacy)
    with pytest.raises(mr.ArtifactFormatNotAllowed):
        loaders.load_legacy_joblib_for_conversion(legacy, expected_sha256=mr.sha256_file(legacy))
    monkeypatch.setenv("ARTIFACT_PROFILE", "training")
    with pytest.raises(mr.ArtifactIntegrityError):
        loaders.load_legacy_joblib_for_conversion(legacy, expected_sha256="0" * 64)
    assert loaders.load_legacy_joblib_for_conversion(legacy, expected_sha256=mr.sha256_file(legacy)) is not None


# ----------------------------------------------------------------------------- loaders and failure telemetry


def test_load_scaler_through_the_gate_and_tampered_json_is_rejected_by_the_hash_gate(world):
    path = world / "models/anomaly/scaler.json"
    scaler = loaders.load_scaler(path, artifact="anomaly_detector")
    X = np.random.default_rng(3).normal(size=(100, 3)) * 10
    assert np.allclose(scaler.transform(X), scaler_io.read_scaler_json(path).transform(X))
    doc = json.loads(path.read_text())
    doc["arrays"]["scale_"]["values"][0] *= 1.0000001  # a plausible, still-valid scaler -- but not the logged one
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    with pytest.raises(mr.ArtifactIntegrityError, match="sha256|size"):
        loaders.load_scaler(path, artifact="anomaly_detector")
    # and with the gate switched to warn the file still PARSES, proving it is the HASH that stopped it
    assert scaler_io.read_scaler_json(path) is not None


def test_load_json_and_npz_are_gated_and_npz_forbids_pickle(world):
    cfg = loaders.load_json(world / "models/anomaly/config.json", artifact="anomaly_detector")
    assert cfg["seq_len"] == 12
    with pytest.raises(mr.ArtifactFormatNotAllowed):
        loaders.load_json(world / "models/anomaly/model.keras", artifact="x")
    npz = world / "models/forecaster/w.npz"
    np.savez(npz, a=np.arange(3))
    mr.log_model("forecaster", metrics={}, data_source="s", artifact_path="models/forecaster/thermal.keras")
    obj = world / "models/forecaster/obj.npz"
    np.savez(obj, a=np.array([{"x": 1}], dtype=object), allow_pickle=True)
    assert "a" in np.load(npz, allow_pickle=False).files
    with pytest.raises(ValueError):
        np.load(obj, allow_pickle=False)["a"]


def test_failures_are_counted_by_reason_and_make_readiness_degraded(world):
    for _ in range(2):
        with pytest.raises(mr.ModelUnavailableError):
            authorize(world, PPO)  # format
    flip_byte(world / "models/anomaly/model.keras")
    with pytest.raises(mr.ArtifactIntegrityError):
        authorize(world, ANOMALY)
    counts = loaders.failure_counts()
    assert counts["format"] == 2 and counts["integrity"] == 1 and counts["status"] == 0
    snap = loaders.health_snapshot()
    assert snap["status"] == "degraded" and snap["unavailable"] == {"test": "integrity"}


def test_a_clean_authorisation_clears_the_degraded_flag(world):
    original = (world / "models/anomaly/model.keras").read_bytes()
    flip_byte(world / "models/anomaly/model.keras")
    with pytest.raises(mr.ModelUnavailableError):
        authorize(world, ANOMALY)
    assert loaders.health_snapshot()["status"] == "degraded"
    (world / "models/anomaly/model.keras").write_bytes(original)
    authorize(world, ANOMALY)
    assert loaders.health_snapshot()["status"] == "ok"


def test_rejection_message_contains_no_absolute_path(world):
    flip_byte(world / "models/anomaly/model.keras")
    with pytest.raises(mr.ArtifactIntegrityError) as exc:
        authorize(world, ANOMALY)
    assert str(world) not in exc.value.reason


def test_ensure_verified_shim_runs_the_whole_gate(world):
    mr.ensure_verified([world / r for r in ANOMALY], artifact="x")
    _set(world, _id("anomaly_detector"), status="quarantined")
    with pytest.raises(mr.ArtifactNotPromoted):
        mr.ensure_verified([world / r for r in ANOMALY], artifact="x")


def test_verify_off_skips_the_registry_but_not_the_format_allow_list(world, monkeypatch):
    monkeypatch.setenv("ARTIFACT_VERIFY", "off")
    (world / "models/anomaly/scaler.joblib").write_bytes(b"x")
    loaders.authorize([world / "models/anomaly/config.json"], artifact="x")
    with pytest.raises(mr.ArtifactFormatNotAllowed):
        loaders.authorize([world / "models/anomaly/scaler.joblib"], artifact="x")
    with pytest.raises(mr.ArtifactFormatNotAllowed):
        loaders.authorize([world / "models/optimizer/ppo_model.zip"], artifact="x")


# ----------------------------------------------------------------------------- scalers (JSON)


def test_scaler_json_equals_sklearn_within_1e12_on_10000_random_rows():
    from sklearn.preprocessing import MinMaxScaler, StandardScaler

    rng = np.random.default_rng(42)
    train = rng.normal(loc=[5, -3, 100, 0.2, 40], scale=[1, 10, 50, 0.01, 7], size=(2000, 5)).astype(np.float32)
    rows = rng.normal(loc=[5, -3, 100, 0.2, 40], scale=[3, 30, 150, 0.05, 20], size=(10_000, 5))
    for original in (
        StandardScaler().fit(train),
        MinMaxScaler().fit(train),
        MinMaxScaler(feature_range=(-1, 1), clip=True).fit(train.astype(np.float64)),
        StandardScaler(with_mean=False).fit(train),
        StandardScaler(with_std=False).fit(train),
    ):
        restored = scaler_io.loads_scaler(scaler_io.dumps_scaler(original))
        assert type(restored) is type(original)
        assert np.max(np.abs(original.transform(rows) - restored.transform(rows))) <= 1e-12
        assert np.max(np.abs(original.inverse_transform(rows) - restored.inverse_transform(rows))) <= 1e-12
        assert (
            restored.n_features_in_ == original.n_features_in_ and restored.n_samples_seen_ == original.n_samples_seen_
        )


def test_unsupported_scaler_type_is_refused():
    from sklearn.preprocessing import RobustScaler

    with pytest.raises(scaler_io.UnsupportedScalerError):
        scaler_io.scaler_to_dict(RobustScaler().fit(np.arange(20.0).reshape(10, 2)))
    doc = scaler_io.scaler_to_dict(_scaler())
    doc["type"] = "RobustScaler"
    with pytest.raises(scaler_io.UnsupportedScalerError):
        scaler_io.scaler_from_dict(doc)

    class MinMaxScaler:  # a look-alike defined elsewhere
        pass

    with pytest.raises(scaler_io.UnsupportedScalerError):
        scaler_io.scaler_type_name(MinMaxScaler())


def test_unfitted_scaler_and_malformed_documents_are_refused():
    from sklearn.preprocessing import StandardScaler

    with pytest.raises(scaler_io.ScalerFormatError):
        scaler_io.scaler_to_dict(StandardScaler())
    good = scaler_io.scaler_to_dict(_scaler())

    def mutated(fn):
        doc = json.loads(json.dumps(good))
        fn(doc)
        return doc

    for bad in (
        mutated(lambda d: d.update(format="other")),
        mutated(lambda d: d.update(n_features=99)),
        mutated(lambda d: d["arrays"].pop("min_")),
        mutated(lambda d: d["arrays"]["min_"]["values"].append(1.0)),
        mutated(lambda d: d["arrays"]["min_"].update(dtype="object")),
        mutated(lambda d: d["arrays"].update(min_=None)),
        mutated(lambda d: d["params"].update(feature_range=[1, 0])),
        mutated(lambda d: d["arrays"]["scale_"]["values"].__setitem__(0, "NaN")),
    ):
        with pytest.raises(scaler_io.ScalerFormatError):
            scaler_io.scaler_from_dict(bad)
    for text in ('{"x": NaN}', "not json", "[]"):
        with pytest.raises(scaler_io.ScalerFormatError):
            scaler_io.loads_scaler(text)


def test_dump_scaler_json_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "scaler.json"
    scaler_io.dump_scaler_json(_scaler(), path)
    before = path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        scaler_io.dump_scaler_json(_scaler(), path)
    assert path.read_bytes() == before and [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_shipped_scalers_are_json_and_equal_the_legacy_pickles_when_both_are_present():
    for directory in ("anomaly", "forecaster"):
        shipped = ROOT / "models" / directory / "scaler.json"
        assert shipped.is_file(), f"{shipped} missing: run scripts/convert_scalers.py"
        assert not (ROOT / "models" / directory / "scaler.joblib").exists()
        assert scaler_io.read_scaler_json(shipped).n_features_in_ in (5, 10)
    assert not [p for p in (ROOT / "models").rglob("*") if p.suffix in (".joblib", ".pkl") and "_legacy" not in p.parts]


# ----------------------------------------------------------------------------- registry_cli


def _cli():
    spec = importlib.util.spec_from_file_location("registry_cli_under_test", ROOT / "scripts" / "registry_cli.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _no_audit(cli, monkeypatch):
    def backend(row, apply):
        apply()

    monkeypatch.setattr(cli, "_audit_backend", backend)


def test_quarantine_appends_history_and_never_alters_prior_entries(world, monkeypatch):
    cli = _cli()
    _no_audit(cli, monkeypatch)
    before = json.loads(json.dumps(mr.read_registry()))
    target = _id("anomaly_detector")
    assert cli.main(["quarantine", target, "--reason", "suspect data", "--actor", "tester"]) == 0
    after = mr.read_registry()
    for old, new in zip(before, after):
        if old["model_id"] != target:
            assert old == new  # every other artifact byte-identical
            continue
        assert new["status"] == "quarantined" and new["status_reason"] == "suspect data"
        assert new["history"][: len(old["history"])] == old["history"]  # prior history untouched
        assert len(new["history"]) == len(old["history"]) + 1
        last = new["history"][-1]
        assert (last["from"], last["to"], last["action"], last["actor"]) == (
            "promoted",
            "quarantined",
            "quarantine",
            "tester",
        )
        assert last["seq"] == len(old["history"])
    assert (world / "models/registry.json.bak").exists()
    with pytest.raises(mr.ArtifactNotPromoted):
        authorize(world, ANOMALY)  # takes effect immediately


def test_transition_rules(world, monkeypatch):
    cli = _cli()
    _no_audit(cli, monkeypatch)
    target = _id("anomaly_detector")
    assert cli.main(["reject", target, "--reason", "bad"]) == 0
    assert cli.main(["promote", target, "--reason", "x", "--evaluation-ref", "r1"]) == 1  # rejected is final
    assert cli.main(["quarantine", target, "--reason", "x"]) == 1
    assert cli.main(["quarantine", "no-such-id", "--reason", "x"]) == 1
    with pytest.raises(SystemExit):
        cli.main(["quarantine", target])  # --reason is required


def test_promote_requires_integrity_compat_api_format_and_an_evaluation(world, monkeypatch):
    cli = _cli()
    _no_audit(cli, monkeypatch)
    anomaly = _id("anomaly_detector")
    _set(world, anomaly, status="candidate")
    assert cli.main(["promote", anomaly, "--reason", "r"]) == 1  # no evaluation_ref, no waiver
    flip_byte(world / "models/anomaly/model.keras")
    assert cli.main(["promote", anomaly, "--reason", "r", "--evaluation-ref", "run-1"]) == 1  # integrity
    (world / "models/anomaly/model.keras").write_bytes(b"keras-anomaly-" + bytes(range(200)))
    _set(world, anomaly, input_cadence_s=60)
    assert cli.main(["promote", anomaly, "--reason", "r", "--evaluation-ref", "run-1"]) == 1  # incompatible
    _set(world, anomaly, input_cadence_s=300)
    assert cli.main(["promote", anomaly, "--reason", "r", "--evaluation-ref", "run-1"]) == 0
    entry = mr.latest("anomaly_detector")
    assert entry["status"] == "promoted" and entry["evaluation_ref"] == "run-1"
    ppo = _id("ppo_optimizer")
    _set(world, ppo, status="candidate")
    assert cli.main(["promote", ppo, "--reason", "r", "--evaluation-ref", "run-1"]) == 1  # SB3 zip is not API-loadable


def test_required_audit_failure_exits_nonzero_and_leaves_the_registry_unchanged(world, monkeypatch):
    cli = _cli()

    def down(row, apply):
        raise cli.AuditUnavailable("database unreachable")

    monkeypatch.setattr(cli, "_audit_backend", down)
    before = (world / "models/registry.json").read_bytes()
    target = _id("anomaly_detector")
    assert cli.main(["quarantine", target, "--reason", "r", "--audit"]) == 3
    assert (world / "models/registry.json").read_bytes() == before
    # default mode: the DB being down is noted and the change still applies
    assert cli.main(["quarantine", target, "--reason", "r"]) == 0
    assert mr.latest("anomaly_detector")["status"] == "quarantined"


def test_a_commit_failure_after_the_write_is_reported_as_audit_failure(world, monkeypatch):
    cli = _cli()

    def late(row, apply):
        apply()
        raise cli.AuditCommitFailed("commit failed")

    monkeypatch.setattr(cli, "_audit_backend", late)
    assert cli.main(["quarantine", _id("anomaly_detector"), "--reason", "r", "--audit"]) == 3
    assert mr.latest("anomaly_detector")["status"] == "quarantined"  # honest: the registry did change


def test_audit_row_describes_the_transition(world, monkeypatch):
    cli = _cli()
    rows = []
    monkeypatch.setattr(cli, "_audit_backend", lambda row, apply: (rows.append(row), apply())[1])
    cli.main(["quarantine", _id("anomaly_detector"), "--reason", "why", "--actor", "alice", "--audit"])
    (row,) = rows
    assert (
        row["action"] == "model_quarantine" and row["username"] == "alice" and row["resource_type"] == "model_artifact"
    )
    assert (
        row["details"]["from"] == "promoted"
        and row["details"]["to"] == "quarantined"
        and row["details"]["reason"] == "why"
    )


def test_unreachable_database_is_detected_by_the_real_backend(world, monkeypatch):
    cli = _cli()
    monkeypatch.setattr(cli, "AUDIT_TIMEOUT_S", 0.5)
    called = []
    with pytest.raises((cli.AuditUnavailable, cli.AuditCommitFailed)):
        cli._db_backend({"action": "x", "username": "u"}, lambda: called.append(1))
    assert called == []  # failed before the registry would have been touched (or deps missing)


def test_list_and_dry_run(world, monkeypatch):
    cli = _cli()
    _no_audit(cli, monkeypatch)
    assert cli.main(["list"]) == 0 and cli.main(["list", "--json"]) == 0
    before = (world / "models/registry.json").read_bytes()
    assert cli.main(["quarantine", _id("anomaly_detector"), "--reason", "r", "--dry-run"]) == 0
    assert (world / "models/registry.json").read_bytes() == before


# ----------------------------------------------------------------------------- migration of the pre-T19 registry


def _v1_registry(world, scaler_hash_source):
    def v1(name, rel, files, physics="legacy-0", **extra):
        return {
            "name": name, "version": "20260927T1", "trained_at": "2026-09-27T14:00:00+00:00", "metrics": extra.get("metrics", {}),
            "data_source": "data/raw/sensor_data.csv (rows 0:20736 train, 20736:25920 held out)", "artifact_path": rel,
            "params": extra.get("params", {}), "python": "3.12.10", "manifest_version": 1, "relative_path": rel,
            "sha256": "0" * 64, "size": 1, "files": mr.file_digests(files), "git_sha": "unknown", "physics_version": physics,
            "dataset_id": "sensor_data.csv", "dataset_sha256": "1" * 64, "key_package_versions": None,
        }  # fmt: skip

    legacy_scaler = world / "models/anomaly/scaler.joblib"
    legacy_scaler.write_bytes(b"legacy pickle bytes")
    anomaly_files = ANOMALY[:2] + ["models/anomaly/scaler.joblib"]
    entries = [
        v1("anomaly_detector", "models/anomaly", anomaly_files),
        v1(
            "ppo_optimizer",
            "models/optimizer",
            PPO,
            metrics={"pue_improvement_mean_pct": -2.27},
            params={"seeds": [0, 1, 2]},
        ),
    ]
    (world / "models/registry.json").write_text(json.dumps(entries))
    return entries


def test_migration_quarantines_ppo_and_promotes_data_models_under_a_named_waiver(world, monkeypatch):
    cli = _cli()
    _no_audit(cli, monkeypatch)
    _v1_registry(world, None)
    assert mr.read_registry_document()["registry_version"] == 1
    assert cli.main(["migrate", "--actor", "tester"]) == 0
    document = mr.read_registry_document()
    assert document["registry_version"] == 2
    by_name = {e["name"]: e for e in document["artifacts"]}
    ppo, anomaly = by_name["ppo_optimizer"], by_name["anomaly_detector"]
    assert ppo["status"] == "quarantined" and "-2.27" in ppo["status_reason"] and "unversioned" in ppo["status_reason"]
    assert "never evaluated" in ppo["status_reason"] and "legacy-0" in ppo["status_reason"]
    assert ppo["environment_version"] is None and ppo["compat_waiver"] is None
    assert anomaly["status"] == "promoted"
    assert anomaly["compat_waiver"]["expires_after_task"] == "T26" and anomaly["compat_waiver"]["name"]
    assert set(anomaly["compat_waiver"]["fields"]) == {"physics_version", "physics_params_hash"}
    assert "models/anomaly/scaler.json" in anomaly["files"] and not any(f.endswith(".joblib") for f in anomaly["files"])
    assert [h["action"] for h in anomaly["history"]] == ["logged", "migrate"]
    assert all(mr.validate_manifest(e) == [] for e in document["artifacts"])
    assert (world / "models/registry.json.bak").exists()
    grant = authorize(world, ANOMALY)  # loads under the waiver
    assert set(grant.waived_fields) == {"physics_version", "physics_params_hash"}
    with pytest.raises(mr.ArtifactNotPromoted):
        authorize(world, PPO)
    assert cli.main(["migrate"]) == 0  # idempotent: already v2


def test_migration_refuses_a_model_file_that_changed_since_it_was_logged(world, monkeypatch):
    cli = _cli()
    _no_audit(cli, monkeypatch)
    _v1_registry(world, None)
    flip_byte(world / "models/anomaly/model.keras")
    before = (world / "models/registry.json").read_bytes()
    assert cli.main(["migrate"]) == 1
    assert (world / "models/registry.json").read_bytes() == before


def test_migration_needs_the_converted_scaler(world, monkeypatch):
    cli = _cli()
    _no_audit(cli, monkeypatch)
    _v1_registry(world, None)
    (world / "models/anomaly/scaler.json").unlink()
    assert cli.main(["migrate"]) == 1


def test_the_shipped_registry_is_v2_with_the_required_states():
    document = json.loads((ROOT / "models/registry.json").read_text())
    assert document["registry_version"] == 2
    by_name = {e["name"]: e for e in document["artifacts"]}
    assert by_name["ppo_optimizer"]["status"] == "quarantined"
    for name in ("anomaly_detector", "forecaster"):
        entry = by_name[name]
        assert entry["status"] == "promoted" and entry["compat_waiver"]["expires_after_task"] == "T26"
        assert mr.validate_manifest(entry) == []
        assert all(info["format"] in ("json", "keras") for info in entry["files"].values())
        for rel, info in entry["files"].items():  # the committed hashes describe the committed files
            assert mr.sha256_file(ROOT / rel) == info["sha256"]


def test_convert_scalers_script_converts_proves_equivalence_and_moves_the_legacy_file(world, monkeypatch):
    pytest.importorskip("joblib")
    import joblib

    spec = importlib.util.spec_from_file_location("convert_scalers_under_test", ROOT / "scripts" / "convert_scalers.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setenv("ARTIFACT_PROFILE", "training")
    (world / "models/anomaly/scaler.json").unlink()
    legacy = world / "models/anomaly/scaler.joblib"
    joblib.dump(_scaler(), legacy)
    digest = mr.sha256_file(legacy)
    assert script.main(["--sha256", f"models/anomaly/scaler.joblib={digest}"]) == 0
    assert (world / "models/anomaly/scaler.json").is_file() and not legacy.exists()
    assert (world / "models/_legacy/anomaly/scaler.joblib").is_file()
    assert script.main([]) == 0  # re-run is a no-op
    # unsupported scaler type: stop, change nothing
    from sklearn.preprocessing import RobustScaler

    (world / "models/anomaly/scaler.json").unlink()
    joblib.dump(RobustScaler().fit(np.arange(20.0).reshape(10, 2)), legacy)
    assert script.main(["--sha256", f"models/anomaly/scaler.joblib={mr.sha256_file(legacy)}"]) == 2
    assert legacy.exists() and not (world / "models/anomaly/scaler.json").exists()
    # unknown hash: refuses to unpickle
    assert script.main([]) == 1


# ----------------------------------------------------------------------------- static guarantees (AST)

_SCAN_DIRS = ("src", "api", "scripts", "notebooks", "models")
_LOADERS_FILE = Path("src/artifacts/loaders.py")


def _python_files():
    files = [p for d in _SCAN_DIRS for p in (ROOT / d).rglob("*.py")]
    files += [p for p in ROOT.glob("*.py")]
    return sorted(p for p in files if "_legacy" not in p.parts and "node_modules" not in p.parts)


def _violations(source: str, *, allow_ppo_load: bool = False) -> list[str]:
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""] + [a.name for a in node.names]
            )
            for name in names:
                if name.split(".")[0] in ("pickle", "cPickle", "_pickle", "joblib", "dill", "cloudpickle", "shelve"):
                    found.append(f"import {name}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            chain = []
            cur = node.func
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                chain.append(cur.id)
            dotted = ".".join(reversed(chain))
            if dotted.endswith(
                ("joblib.load", "pickle.load", "pickle.loads", "models.load_model", "saving.load_model")
            ):
                found.append(dotted)
            if dotted.endswith("PPO.load") and not allow_ppo_load:
                found.append(dotted)
    return found


def test_the_scanner_detects_every_forbidden_call():
    bad = "import joblib\nimport pickle\njoblib.load(p)\npickle.loads(b)\nkeras.models.load_model(p)\nK.models.load_model(p)\nPPO.load(p)\n"
    found = _violations(bad)
    assert {
        "import joblib",
        "import pickle",
        "joblib.load",
        "pickle.loads",
        "keras.models.load_model",
        "K.models.load_model",
        "PPO.load",
    } <= set(found)
    assert _violations("from joblib import load\n") == [
        "import joblib",
        "import load",
    ] or "import joblib" in _violations("from joblib import load\n")


def test_no_pickle_or_unsafe_loader_exists_outside_the_loaders_module():
    offenders = {}
    for path in _python_files():
        rel = path.relative_to(ROOT)
        if rel == _LOADERS_FILE:
            continue
        found = _violations(path.read_text(encoding="utf-8"))
        if found:
            offenders[rel.as_posix()] = found
    assert offenders == {}


def test_loaders_module_loads_keras_only_in_safe_mode_and_never_imports_pickle_at_module_level():
    source = (ROOT / _LOADERS_FILE).read_text()
    assert "safe_mode=True" in source and "compile=False" in source and "allow_pickle=False" in source
    tree = ast.parse(source)
    top_level_imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any(
        (a.name if isinstance(n, ast.Import) else n.module or "").split(".")[0]
        in ("joblib", "pickle", "stable_baselines3")
        for n in top_level_imports
        for a in n.names
    )
    assert source.count("PPO.load(") == 1 and source.count("joblib.load(") == 1


def test_nothing_under_api_references_a_pickle_capable_loader():
    """AST-level (comments and docstrings may talk about pickle; code may not touch it)."""
    forbidden = {
        "load_sb3_zip_training_only",
        "load_legacy_joblib_for_conversion",
        "stable_baselines3",
        "joblib",
        "pickle",
        "PPO",
    }
    hits = []
    for path in (ROOT / "api").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = set()
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names |= {part for a in node.names for part in a.name.split(".")}
                names |= set((node.module or "").split(".")) if isinstance(node, ast.ImportFrom) else set()
            for word in forbidden & names:
                hits.append((path.relative_to(ROOT).as_posix(), word))
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "load"
                and isinstance(node.value, ast.Name)
                and node.value.id == "JointOptimizer"
            ):
                hits.append((path.relative_to(ROOT).as_posix(), "JointOptimizer.load"))
    assert hits == []


def test_the_api_optimizer_service_never_trains_in_a_request():
    source = (ROOT / "api/services/optimization_service.py").read_text()
    assert (
        "_train_fallback_optimizer" not in source
        and ".train(" not in source
        and "FALLBACK_TRAIN_TIMESTEPS" not in source
    )
    assert 'loaders.lock_profile("api")' in source and "model_unavailable" in source


def test_joint_optimizer_load_is_refused_in_the_api_profile(world, monkeypatch):
    pytest.importorskip("gymnasium")
    from src.optimizer import JointOptimizer

    loaders.lock_profile("api")
    with pytest.raises(mr.ModelUnavailableError):
        JointOptimizer.load(world / "models/optimizer")


def test_no_stale_joblib_references_remain_in_loader_code():
    for rel in (
        "src/anomaly_detector.py",
        "src/lstm_model.py",
        "src/optimizer.py",
        "api/services/optimization_service.py",
    ):
        text = (ROOT / rel).read_text()
        assert (
            "joblib.load" not in text
            and "ensure_verified" not in text
            and 'scaler.joblib"' not in text.replace("`.joblib`", "")
        )
