"""T6: model artifact integrity -- manifest, SHA-256 verification before load,
ARTIFACT_VERIFY modes, atomic registry writes, relative paths, job-response
scrubbing and the docker-compose hardening.

Everything runs against a throw-away project root (tmp_path) with tiny fake
artifacts; no real model is trained or loaded. Tamper tests rely on every loader
verifying BEFORE it touches TensorFlow / stable-baselines3, so they need neither.
"""

import importlib.util
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import joblib
import pytest
import yaml
from sklearn.preprocessing import StandardScaler

from src import model_registry as mr
from src.model_registry import ModelUnavailableError, ensure_verified
from src.versions import PHYSICS_VERSION

ROOT = Path(__file__).resolve().parent.parent
DATASET_SHA = "11f3d473cd9eedd7db7f3a23de56cc72f88f5794f6e0c2a78543b623d06f07d5"

ARTIFACT_FILES = {
    "anomaly": ["models/anomaly/config.json", "models/anomaly/model.keras", "models/anomaly/scaler.joblib"],
    "optimizer": ["models/optimizer/config.json", "models/optimizer/ppo_model.zip"],
    "forecaster": ["models/forecaster/thermal.keras", "models/forecaster/scaler.joblib"],
}


def _scaler_bytes(path: Path, offset: float = 0.0) -> None:
    scaler = StandardScaler().fit([[0.0 + offset, 1.0], [2.0 + offset, 3.0], [4.0 + offset, 9.0]])
    joblib.dump(scaler, path)


def flip_byte(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A project root with the three artifacts and a registry logged through log_model()."""
    monkeypatch.setattr(mr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mr, "REGISTRY_PATH", tmp_path / "models" / "registry.json")
    monkeypatch.setenv("ARTIFACT_VERIFY", "enforce")
    monkeypatch.delenv("GIT_SHA", raising=False)

    for rel in [f for files in ARTIFACT_FILES.values() for f in files]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "models/anomaly/config.json").write_text(json.dumps({"threshold": 0.1, "seq_len": 12}))
    (tmp_path / "models/anomaly/model.keras").write_bytes(b"keras-anomaly-" + bytes(range(200)))
    _scaler_bytes(tmp_path / "models/anomaly/scaler.joblib")
    (tmp_path / "models/optimizer/config.json").write_text(json.dumps({"alpha": 0.5}))
    (tmp_path / "models/optimizer/ppo_model.zip").write_bytes(b"PK-ppo-" + bytes(range(200)))
    (tmp_path / "models/forecaster/thermal.keras").write_bytes(b"keras-forecaster-" + bytes(range(200)))
    _scaler_bytes(tmp_path / "models/forecaster/scaler.joblib")

    mr.log_model("anomaly_detector", metrics={}, data_source="synthetic", artifact_path="models/anomaly")
    mr.log_model("ppo_optimizer", metrics={}, data_source="synthetic", artifact_path="models/optimizer")
    mr.log_model("forecaster", metrics={}, data_source="synthetic", artifact_path="models/forecaster/thermal.keras")
    return tmp_path


# ----------------------------------------------------------------------------- registry: manifest, paths, round trip


def test_log_model_records_manifest_with_relative_paths(world):
    entries = mr.read_registry()
    anomaly = next(e for e in entries if e["name"] == "anomaly_detector")
    assert anomaly["relative_path"] == anomaly["artifact_path"] == "models/anomaly"
    assert set(anomaly["files"]) == set(ARTIFACT_FILES["anomaly"])
    for rel, info in anomaly["files"].items():
        assert info["sha256"] == mr.sha256_file(world / rel)
        assert info["size"] == (world / rel).stat().st_size
    assert anomaly["sha256"] == mr.aggregate_sha256(anomaly["files"])
    assert anomaly["size"] == sum(i["size"] for i in anomaly["files"].values())
    assert anomaly["physics_version"] == PHYSICS_VERSION == "legacy-0"
    for key in ("git_sha", "dataset_id", "dataset_sha256", "python", "key_package_versions", "trained_at", "version"):
        assert key in anomaly
    assert anomaly["git_sha"] == "unknown"  # tmp root is not a git checkout and GIT_SHA is unset


def test_forecaster_manifest_also_covers_the_sibling_scaler(world):
    forecaster = mr.latest("forecaster")
    assert set(forecaster["files"]) == set(ARTIFACT_FILES["forecaster"])


def test_registry_contains_no_absolute_paths(world):
    text = (world / "models" / "registry.json").read_text()
    assert str(world) not in text
    assert "C:\\" not in text and ":\\\\" not in text


def test_absolute_artifact_path_inside_root_is_stored_relative(world):
    entry = mr.log_model("anomaly_detector", metrics={}, data_source="x", artifact_path=str(world / "models/anomaly"))
    assert entry["artifact_path"] == "models/anomaly"


def test_artifact_path_outside_root_is_rejected(world, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    (outside / "m.keras").write_bytes(b"x")
    with pytest.raises(ValueError):
        mr.log_model("x", metrics={}, data_source="x", artifact_path=str(outside / "m.keras"))
    with pytest.raises(ValueError):
        mr.log_model("x", metrics={}, data_source="x", artifact_path="../escape")


def test_missing_artifact_cannot_be_logged(world):
    with pytest.raises(FileNotFoundError):
        mr.log_model("x", metrics={}, data_source="x", artifact_path="models/nope")


def test_dataset_id_and_hash_are_derived_from_an_existing_data_file(world):
    (world / "data" / "raw").mkdir(parents=True)
    csv = world / "data" / "raw" / "sensor_data.csv"
    csv.write_text("a,b\n1,2\n")
    entry = mr.log_model(
        "anomaly_detector", metrics={}, data_source=f"{csv} (rows 0:1 train)", artifact_path="models/anomaly"
    )
    assert entry["dataset_id"] == "sensor_data.csv"
    assert entry["dataset_sha256"] == mr.sha256_file(csv)
    assert entry["data_source"] == "data/raw/sensor_data.csv (rows 0:1 train)"


def test_registry_round_trip_and_history_is_append_only(world):
    before = mr.read_registry()
    new = mr.log_model("anomaly_detector", metrics={"f1": 1.0}, data_source="s", artifact_path="models/anomaly")
    after = mr.read_registry()
    assert after[:-1] == before and after[-1] == new
    assert mr.latest("anomaly_detector") == new
    assert mr.latest("never-logged") is None


def test_old_registry_without_manifest_fields_is_still_readable(world):
    legacy = [{"name": "forecaster", "version": "v1", "artifact_path": "models/forecaster/thermal.keras", "params": {}}]
    (world / "models" / "registry.json").write_text(json.dumps(legacy))
    assert mr.latest("forecaster")["version"] == "v1"
    with pytest.raises(ModelUnavailableError):  # readable, but nothing to verify against
        ensure_verified([world / "models/forecaster/thermal.keras"], artifact="forecaster")
    mr.log_model("forecaster", metrics={}, data_source="s", artifact_path="models/forecaster/thermal.keras")
    assert [e["version"] for e in mr.read_registry()][0] == "v1"  # legacy entry preserved


# ----------------------------------------------------------------------------- atomic writes


def _no_temp_files(world):
    return [p.name for p in (world / "models").iterdir() if p.name.endswith(".tmp")]


def test_failed_replace_leaves_the_previous_registry_intact(world, monkeypatch):
    path = world / "models" / "registry.json"
    original = path.read_bytes()

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        mr.log_model("anomaly_detector", metrics={}, data_source="s", artifact_path="models/anomaly")
    assert path.read_bytes() == original
    assert _no_temp_files(world) == []


def test_serialisation_failure_leaves_the_previous_registry_intact(world):
    path = world / "models" / "registry.json"
    original = path.read_bytes()
    with pytest.raises(TypeError):
        mr.log_model("anomaly_detector", metrics={"bad": object()}, data_source="s", artifact_path="models/anomaly")
    assert path.read_bytes() == original
    assert _no_temp_files(world) == []


def test_write_goes_through_a_temp_file_in_the_same_directory(world, monkeypatch):
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    mr.log_model("anomaly_detector", metrics={}, data_source="s", artifact_path="models/anomaly")
    ((src, dst),) = seen
    assert src.parent == dst.parent and src != dst and dst.name == "registry.json"


def test_corrupt_registry_is_set_aside_not_silently_discarded(world):
    path = world / "models" / "registry.json"
    path.write_text("{ not json")
    mr.log_model("anomaly_detector", metrics={}, data_source="s", artifact_path="models/anomaly")
    backups = [p for p in (world / "models").iterdir() if ".corrupt-" in p.name]
    assert len(backups) == 1 and backups[0].read_text() == "{ not json"
    assert [e["name"] for e in mr.read_registry()] == ["anomaly_detector"]


# ----------------------------------------------------------------------------- verification core


def test_untampered_artifacts_verify(world):
    for files in ARTIFACT_FILES.values():
        ensure_verified([world / rel for rel in files], artifact="x")  # does not raise


def test_verification_does_not_depend_on_the_working_directory(world, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))
    ensure_verified([world / rel for rel in ARTIFACT_FILES["anomaly"]], artifact="x")


@pytest.mark.parametrize("artifact", sorted(ARTIFACT_FILES))
def test_every_file_of_every_artifact_is_hash_protected(world, artifact):
    for rel in ARTIFACT_FILES[artifact]:
        target = world / rel
        original = target.read_bytes()
        flip_byte(target)
        with pytest.raises(ModelUnavailableError) as exc:
            ensure_verified([world / r for r in ARTIFACT_FILES[artifact]], artifact=artifact)
        assert "sha256" in exc.value.reason and str(world) not in exc.value.reason
        target.write_bytes(original)
    ensure_verified([world / r for r in ARTIFACT_FILES[artifact]], artifact=artifact)


def test_truncated_and_deleted_files_are_refused(world):
    target = world / "models/optimizer/ppo_model.zip"
    files = [world / r for r in ARTIFACT_FILES["optimizer"]]
    target.write_bytes(target.read_bytes()[:-5])
    with pytest.raises(ModelUnavailableError, match="size"):
        ensure_verified(files, artifact="ppo")
    target.unlink()
    with pytest.raises(ModelUnavailableError, match="missing"):
        ensure_verified(files, artifact="ppo")


def test_file_without_a_manifest_entry_is_refused(world):
    stray = world / "models" / "optimizer" / "ppo_model_v2.zip"
    stray.write_bytes(b"unlisted")
    with pytest.raises(ModelUnavailableError, match="no manifest entry"):
        ensure_verified([stray], artifact="ppo")


def test_path_outside_the_project_root_is_refused(world, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "model.keras"
    outside.write_bytes(b"x")
    with pytest.raises(ModelUnavailableError, match="outside the project root"):
        ensure_verified([outside], artifact="x")


def test_symlink_pointing_out_of_the_root_is_refused(world, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "evil.zip"
    outside.write_bytes(b"x")
    link = world / "models" / "optimizer" / "ppo_model.zip"
    link.unlink()
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(ModelUnavailableError):
        ensure_verified([world / r for r in ARTIFACT_FILES["optimizer"]], artifact="ppo")


def test_physics_version_mismatch_is_refused(world, monkeypatch):
    monkeypatch.setattr(mr, "PHYSICS_VERSION", "v1-test")
    with pytest.raises(ModelUnavailableError, match="physics_version"):
        ensure_verified([world / r for r in ARTIFACT_FILES["anomaly"]], artifact="anomaly")


def test_missing_registry_is_refused_in_enforce(world):
    (world / "models" / "registry.json").unlink()
    with pytest.raises(ModelUnavailableError, match="registry not found"):
        ensure_verified([world / r for r in ARTIFACT_FILES["anomaly"]], artifact="anomaly")


def test_a_newer_entry_supersedes_the_older_hashes(world):
    flip_byte(world / "models/anomaly/model.keras")  # retrained / replaced ...
    with pytest.raises(ModelUnavailableError):
        ensure_verified([world / r for r in ARTIFACT_FILES["anomaly"]], artifact="anomaly")
    mr.log_model("anomaly_detector", metrics={}, data_source="s", artifact_path="models/anomaly")  # ... and logged
    ensure_verified([world / r for r in ARTIFACT_FILES["anomaly"]], artifact="anomaly")


# ----------------------------------------------------------------------------- ARTIFACT_VERIFY modes


def test_modes_enforce_warn_off(world, monkeypatch, caplog):
    files = [world / r for r in ARTIFACT_FILES["anomaly"]]
    flip_byte(world / "models/anomaly/model.keras")

    monkeypatch.setenv("ARTIFACT_VERIFY", "enforce")
    with pytest.raises(ModelUnavailableError):
        ensure_verified(files, artifact="anomaly")

    monkeypatch.setenv("ARTIFACT_VERIFY", "warn")
    with caplog.at_level(logging.WARNING, logger=mr.logger.name):
        ensure_verified(files, artifact="anomaly")  # proceeds
    assert "ARTIFACT_VERIFY=warn" in caplog.text and "sha256 differs" in caplog.text

    caplog.clear()
    monkeypatch.setenv("ARTIFACT_VERIFY", "off")
    with caplog.at_level(logging.DEBUG, logger=mr.logger.name):
        ensure_verified(files, artifact="anomaly")
    assert caplog.text == ""


def test_unset_and_unknown_values_mean_enforce(world, monkeypatch):
    flip_byte(world / "models/anomaly/model.keras")
    files = [world / r for r in ARTIFACT_FILES["anomaly"]]
    monkeypatch.delenv("ARTIFACT_VERIFY")
    assert mr.verify_mode() == "enforce"
    with pytest.raises(ModelUnavailableError):
        ensure_verified(files, artifact="anomaly")
    monkeypatch.setenv("ARTIFACT_VERIFY", "disabled-by-typo")
    assert mr.verify_mode() == "enforce"
    with pytest.raises(ModelUnavailableError):
        ensure_verified(files, artifact="anomaly")


def test_mode_is_read_on_every_call(world, monkeypatch):
    files = [world / r for r in ARTIFACT_FILES["anomaly"]]
    flip_byte(world / "models/anomaly/model.keras")
    monkeypatch.setenv("ARTIFACT_VERIFY", "warn")
    ensure_verified(files, artifact="anomaly")
    monkeypatch.setenv("ARTIFACT_VERIFY", "enforce")
    with pytest.raises(ModelUnavailableError):
        ensure_verified(files, artifact="anomaly")


# ----------------------------------------------------------------------------- loaders refuse tampered artifacts


def test_anomaly_detector_load_refuses_every_tampered_file(world):
    from src.anomaly_detector import AnomalyDetector

    for rel in ARTIFACT_FILES["anomaly"]:
        target = world / rel
        original = target.read_bytes()
        flip_byte(target)
        with pytest.raises(ModelUnavailableError):
            AnomalyDetector.load(world / "models/anomaly")
        target.write_bytes(original)


def test_joint_optimizer_load_refuses_every_tampered_file(world):
    pytest.importorskip("gymnasium")
    from src.optimizer import JointOptimizer

    for rel in ARTIFACT_FILES["optimizer"]:
        target = world / rel
        original = target.read_bytes()
        flip_byte(target)
        with pytest.raises(ModelUnavailableError):
            JointOptimizer.load(world / "models/optimizer")
        target.write_bytes(original)


def test_thermal_forecaster_load_refuses_a_tampered_model(world):
    from src.lstm_model import ThermalForecaster

    flip_byte(world / "models/forecaster/thermal.keras")
    with pytest.raises(ModelUnavailableError):
        ThermalForecaster.load(world / "models/forecaster/thermal.keras")


def test_load_scaler_accepts_a_verified_scaler_and_refuses_a_tampered_one(world):
    from src.lstm_model import DataPipeline

    scaler_path = world / "models/forecaster/scaler.joblib"
    ok = DataPipeline()
    ok.load_scaler(scaler_path)
    assert ok._scaler is not None

    flip_byte(scaler_path)
    bad = DataPipeline()
    with pytest.raises(ModelUnavailableError):
        bad.load_scaler(scaler_path)
    assert bad._scaler is None  # nothing was unpickled


def test_warn_mode_loads_a_modified_scaler_after_logging(world, monkeypatch, caplog):
    from src.lstm_model import DataPipeline

    scaler_path = world / "models/forecaster/scaler.joblib"
    _scaler_bytes(scaler_path, offset=5.0)  # a different, still-loadable scaler
    monkeypatch.setenv("ARTIFACT_VERIFY", "warn")
    pipe = DataPipeline()
    with caplog.at_level(logging.WARNING, logger=mr.logger.name):
        pipe.load_scaler(scaler_path)
    assert pipe._scaler is not None and "failed verification" in caplog.text


def test_anomaly_endpoint_reports_unavailable_when_the_artifact_is_tampered(world, monkeypatch):
    anomaly_service = pytest.importorskip("api.services.anomaly_service")
    flip_byte(world / "models/anomaly/model.keras")
    monkeypatch.setattr(anomaly_service, "ANOMALY_DETECTOR_PATH", world / "models/anomaly")
    monkeypatch.setattr(anomaly_service, "_anomaly_detector", None)
    assert anomaly_service.get_anomaly_detector() is None
    result = anomaly_service.score_recent_data(json.dumps([[0.0] * 5] * 12))
    assert result["message"] == "Anomaly detector not available"
    assert result["alert"] is False


# ----------------------------------------------------------------------------- manifest script


def _load_script():
    script_path = ROOT / "scripts" / "artifact_manifest.py"
    spec = importlib.util.spec_from_file_location("artifact_manifest_script", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def legacy_world(world):
    """Same artifacts, but a pre-T6 registry: absolute Windows paths, no manifest."""
    win = "C:\\Users\\someone\\Desktop\\DigitalTwin-main\\"
    legacy = [
        {
            "name": "anomaly_detector",
            "version": "legacy1",
            "data_source": win + "data\\raw\\sensor_data.csv (rows 0:10 train)",
            "artifact_path": win + "models\\anomaly",
            "python": "3.12.10",
        },
        {
            "name": "forecaster",
            "version": "legacy1",
            "data_source": win + "data\\raw\\sensor_data.csv",
            "artifact_path": win + "models\\forecaster\\thermal.keras",
        },
        {
            "name": "ppo_optimizer",
            "version": "legacy1",
            "data_source": "live DigitalTwin simulation (no historical dataset)",
            "artifact_path": win + "models\\optimizer",
        },
    ]
    (world / "models" / "registry.json").write_text(json.dumps(legacy, indent=2))
    return world


def test_adopt_converts_a_legacy_registry(legacy_world):
    script = _load_script()
    assert script.main(["adopt", "--dataset-sha256", f"sensor_data.csv={DATASET_SHA}"]) == 0
    text = (legacy_world / "models" / "registry.json").read_text()
    assert "C:\\\\" not in text and "Users" not in text
    entries = {e["name"]: e for e in mr.read_registry()}
    assert entries["anomaly_detector"]["relative_path"] == "models/anomaly"
    assert entries["anomaly_detector"]["data_source"] == "data/raw/sensor_data.csv (rows 0:10 train)"
    assert entries["anomaly_detector"]["dataset_id"] == "sensor_data.csv"
    assert entries["anomaly_detector"]["dataset_sha256"] == DATASET_SHA
    assert entries["forecaster"]["dataset_sha256"] == DATASET_SHA
    assert entries["ppo_optimizer"]["dataset_id"] is None and entries["ppo_optimizer"]["dataset_sha256"] is None
    for entry in entries.values():
        assert entry["physics_version"] == "legacy-0" and entry["git_sha"] == "unknown"
        assert entry["key_package_versions"] is None
    assert script.main(["verify"]) == 0
    for files in ARTIFACT_FILES.values():  # and the loaders' check now passes
        ensure_verified([legacy_world / r for r in files], artifact="x")


def test_adopt_without_a_known_dataset_hash_leaves_it_unknown(legacy_world):
    _load_script().main(["adopt"])
    entry = next(e for e in mr.read_registry() if e["name"] == "anomaly_detector")
    assert entry["dataset_id"] == "sensor_data.csv" and entry["dataset_sha256"] is None


def test_adopt_dry_run_writes_nothing_and_is_idempotent(legacy_world):
    script = _load_script()
    path = legacy_world / "models" / "registry.json"
    before = path.read_bytes()
    assert script.main(["adopt", "--dry-run"]) == 0
    assert path.read_bytes() == before
    assert script.main(["adopt"]) == 0
    after_first = path.read_bytes()
    assert script.main(["adopt"]) == 0
    assert path.read_bytes() == after_first


def test_adopt_force_rerecords_hashes_after_an_intentional_change(legacy_world):
    script = _load_script()
    script.main(["adopt"])
    flip_byte(legacy_world / "models/anomaly/model.keras")
    assert script.main(["verify"]) == 1
    assert script.main(["adopt"]) == 0  # no --force: nothing re-trusted
    assert script.main(["verify"]) == 1
    assert script.main(["adopt", "--force"]) == 0
    assert script.main(["verify"]) == 0


def test_verify_command_fails_on_tampering_and_on_missing_manifest(legacy_world):
    script = _load_script()
    assert script.main(["verify"]) == 1  # legacy entries have no manifest yet
    script.main(["adopt"])
    assert script.main(["verify"]) == 0
    flip_byte(legacy_world / "models/optimizer/ppo_model.zip")
    assert script.main(["verify"]) == 1


def test_adopt_rejects_a_malformed_dataset_hash(legacy_world):
    with pytest.raises(SystemExit):
        _load_script().main(["adopt", "--dataset-sha256", "sensor_data.csv=notahash"])


# ----------------------------------------------------------------------------- job responses


def test_scrub_paths_removes_absolute_paths_but_keeps_ordinary_text():
    task_queue = pytest.importorskip("src.task_queue")
    scrub = task_queue.scrub_paths
    assert scrub("cannot open /app/models/optimizer_candidates/x/ppo_model.zip") == "cannot open <path>"
    assert scrub("failed C:\\Users\\a\\Desktop\\models\\x.zip now") == "failed <path> now"
    assert scrub("ratio 3/4 at http://host/a/b") == "ratio 3/4 at http://host/a/b"


def _fake_job(**kw):
    defaults = {"is_finished": False, "is_failed": False, "result": None, "exc_info": None}
    return SimpleNamespace(get_status=lambda: kw.pop("status", "queued"), **{**defaults, **kw})


def _patch_job(monkeypatch, task_queue, job):
    monkeypatch.setattr(task_queue, "_get_queue", lambda: SimpleNamespace(connection=object(), serializer=None))
    monkeypatch.setattr(task_queue.Job, "fetch", staticmethod(lambda job_id, connection=None, serializer=None: job))


def test_failed_job_status_has_no_traceback_and_no_paths(monkeypatch):
    task_queue = pytest.importorskip("src.task_queue")
    trace = (
        "Traceback (most recent call last):\n"
        '  File "/app/src/task_jobs.py", line 40, in train_optimizer_job\n'
        "    optimizer.save(candidate_path)\n"
        "OSError: [Errno 28] No space left on device: '/app/models/optimizer_candidates/20260101_ab12'\n"
    )
    _patch_job(monkeypatch, task_queue, _fake_job(is_failed=True, exc_info=trace, status="failed"))
    status = task_queue.get_status("job-1")
    assert status["error"].startswith("OSError: [Errno 28] No space left on device")
    assert "/app" not in status["error"] and "Traceback" not in status["error"] and "\n" not in status["error"]


def test_finished_job_result_is_scrubbed_recursively(monkeypatch):
    task_queue = pytest.importorskip("src.task_queue")
    result = {"saved_to": "/app/models/optimizer_candidates/x", "nested": [{"p": "C:\\data\\models\\y"}], "n": 3}
    _patch_job(monkeypatch, task_queue, _fake_job(is_finished=True, result=result, status="finished"))
    status = task_queue.get_status("job-2")["result"]
    assert status == {"saved_to": "<path>", "nested": [{"p": "<path>"}], "n": 3}


def test_train_job_result_carries_an_id_not_a_path(tmp_path, monkeypatch):
    import src.optimizer as optimizer_module
    from src import task_jobs

    class FakeOptimizer:
        def __init__(self, **kwargs):
            pass

        def train(self, **kwargs):
            pass

        def save(self, path):
            Path(path).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(optimizer_module, "JointOptimizer", FakeOptimizer)
    monkeypatch.setenv("OPTIMIZER_CANDIDATE_DIR", str(tmp_path / "candidates"))
    result = task_jobs.train_optimizer_job(0.5, 0.3, 0.2, 0.0)
    assert "saved_to" not in result
    assert (tmp_path / "candidates" / result["candidate_id"]).is_dir()
    assert str(tmp_path) not in json.dumps(result)


# ----------------------------------------------------------------------------- docker-compose lint


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _mounts(service):
    return [v for v in service.get("volumes", []) if str(v).split(":")[0].rstrip("/") == "./models"]


def test_compose_api_mounts_models_read_only(compose):
    assert _mounts(compose["backend"]) == ["./models:/app/models:ro"]


def test_compose_worker_keeps_a_writable_models_mount(compose):
    mounts = _mounts(compose["worker"])
    assert len(mounts) == 1 and not mounts[0].endswith(":ro")


def test_compose_redis_is_not_published_and_requires_a_password(compose):
    assert "ports" not in compose["redis"]
    for name, service in compose.items():
        assert not any("6379" in str(p) for p in service.get("ports", [])), name
    assert "--requirepass" in compose["redis"]["command"]
    for name in ("backend", "worker"):
        url = compose[name]["environment"]["REDIS_URL"]
        assert "REDIS_PASSWORD" in url and url.startswith("redis://:")
    worker_cmd = " ".join(map(str, compose["worker"]["command"]))
    assert "REDIS_PASSWORD" in worker_cmd and "--serializer" in worker_cmd


def test_compose_enforces_artifact_verification_by_default(compose):
    for name in ("backend", "worker"):
        assert compose[name]["environment"]["ARTIFACT_VERIFY"] == "${ARTIFACT_VERIFY:-enforce}"
