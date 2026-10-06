"""T6 integrity behaviours, carried forward onto the T19 registry (manifest v2, scaler.json).

Hash verification before load, ARTIFACT_VERIFY modes, relative paths, atomic registry writes,
loaders refusing tampered artifacts, the verify command and job-response scrubbing. Compatibility,
status, format and waiver behaviour are in tests/test_artifact_gate.py.

The T6 ``adopt`` command (manifest v1 from files on disk) is superseded by
``scripts/registry_cli.py migrate``; its tests are replaced by the migration tests there.
"""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from sklearn.preprocessing import StandardScaler

from src import model_registry as mr
from src.artifacts import loaders, scaler_io
from src.model_registry import ModelUnavailableError, ensure_verified

ROOT = Path(__file__).resolve().parent.parent

ARTIFACT_FILES = {
    "anomaly": ["models/anomaly/config.json", "models/anomaly/model.keras", "models/anomaly/scaler.json"],
    "forecaster": ["models/forecaster/thermal.keras", "models/forecaster/scaler.json"],
}


def _scaler_file(path: Path, offset: float = 0.0) -> None:
    scaler = StandardScaler().fit([[0.0 + offset, 1.0], [2.0 + offset, 3.0], [4.0 + offset, 9.0]])
    scaler_io.dump_scaler_json(scaler, path)


def flip_byte(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def _promote_all():
    entries = mr.read_registry()
    for entry in entries:
        entry["status"] = "promoted"
    mr.write_registry(entries)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A project root with the anomaly + forecaster artifacts, logged through log_model() and promoted."""
    monkeypatch.setattr(mr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mr, "REGISTRY_PATH", tmp_path / "models" / "registry.json")
    for var in ("ARTIFACT_COMPAT", "ARTIFACT_PROFILE", "ENVIRONMENT", "PHYSICS_VERSION"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ARTIFACT_VERIFY", "enforce")
    monkeypatch.setenv("GIT_SHA", "b" * 40)
    loaders.reset_for_tests()

    for rel in [f for files in ARTIFACT_FILES.values() for f in files]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "models/anomaly/config.json").write_text(json.dumps({"threshold": 0.1, "seq_len": 12}))
    (tmp_path / "models/anomaly/model.keras").write_bytes(b"keras-anomaly-" + bytes(range(200)))
    _scaler_file(tmp_path / "models/anomaly/scaler.json")
    (tmp_path / "models/forecaster/thermal.keras").write_bytes(b"keras-forecaster-" + bytes(range(200)))
    _scaler_file(tmp_path / "models/forecaster/scaler.json")

    mr.log_model("anomaly_detector", metrics={}, data_source="synthetic", artifact_path="models/anomaly")
    mr.log_model("forecaster", metrics={}, data_source="synthetic", artifact_path="models/forecaster/thermal.keras")
    _promote_all()
    yield tmp_path
    loaders.reset_for_tests()


# ----------------------------------------------------------------------------- registry: manifest, paths, round trip


def test_log_model_records_manifest_with_relative_paths(world):
    anomaly = next(e for e in mr.read_registry() if e["name"] == "anomaly_detector")
    assert anomaly["relative_path"] == anomaly["artifact_path"] == "models/anomaly"
    assert set(anomaly["files"]) == set(ARTIFACT_FILES["anomaly"])
    for rel, info in anomaly["files"].items():
        assert info["sha256"] == mr.sha256_file(world / rel)
        assert info["size"] == (world / rel).stat().st_size
    assert anomaly["sha256"] == mr.aggregate_sha256(anomaly["files"])
    assert anomaly["size"] == sum(i["size"] for i in anomaly["files"].values())
    assert anomaly["manifest_version"] == 2 and anomaly["physics_version"] == mr.versions.active_physics_version()
    for key in ("git_sha", "dataset_id", "dataset_sha256", "python", "trained_at", "version", "package_versions"):
        assert key in anomaly


def test_forecaster_manifest_also_covers_the_sibling_scaler_json(world):
    assert set(mr.latest("forecaster")["files"]) == set(ARTIFACT_FILES["forecaster"])


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
        mr.log_model("anomaly_detector", metrics={}, data_source="x", artifact_path=str(outside / "m.keras"))
    with pytest.raises(ValueError):
        mr.log_model("anomaly_detector", metrics={}, data_source="x", artifact_path="../escape")


def test_missing_artifact_cannot_be_logged(world):
    with pytest.raises(FileNotFoundError):
        mr.log_model("anomaly_detector", metrics={}, data_source="x", artifact_path="models/nope")


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


def test_registry_round_trip_and_log_is_append_only(world):
    before = mr.read_registry()
    new = mr.log_model("anomaly_detector", metrics={"f1": 1.0}, data_source="s", artifact_path="models/anomaly")
    after = mr.read_registry()
    assert after[:-1] == before and after[-1] == new
    assert mr.latest("anomaly_detector") == new and new["status"] == "candidate"
    assert mr.latest("never-logged") is None


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


def test_symlink_pointing_out_of_the_root_is_refused(world, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "evil.keras"
    outside.write_bytes(b"x")
    link = world / "models" / "forecaster" / "thermal.keras"
    link.unlink()
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(ModelUnavailableError):
        ensure_verified([world / r for r in ARTIFACT_FILES["forecaster"]], artifact="forecaster")


def test_a_newer_entry_supersedes_the_older_hashes(world):
    flip_byte(world / "models/anomaly/model.keras")  # retrained / replaced ...
    with pytest.raises(ModelUnavailableError):
        ensure_verified([world / r for r in ARTIFACT_FILES["anomaly"]], artifact="anomaly")
    mr.log_model("anomaly_detector", metrics={}, data_source="s", artifact_path="models/anomaly")  # ... and logged
    _promote_all()
    ensure_verified([world / r for r in ARTIFACT_FILES["anomaly"]], artifact="anomaly")


# ----------------------------------------------------------------------------- ARTIFACT_VERIFY modes


def test_modes_enforce_warn_off(world, monkeypatch, caplog):
    files = [world / r for r in ARTIFACT_FILES["anomaly"]]
    flip_byte(world / "models/anomaly/model.keras")

    monkeypatch.setenv("ARTIFACT_VERIFY", "enforce")
    with pytest.raises(ModelUnavailableError):
        ensure_verified(files, artifact="anomaly")

    monkeypatch.setenv("ARTIFACT_VERIFY", "warn")
    ensure_verified(files, artifact="anomaly")  # proceeds
    assert "ARTIFACT_VERIFY=warn" in caplog.text and "sha256 differs" in caplog.text

    caplog.clear()
    monkeypatch.setenv("ARTIFACT_VERIFY", "off")
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


def test_anomaly_detector_load_refuses_a_non_promoted_artifact(world):
    from src.anomaly_detector import AnomalyDetector

    entries = mr.read_registry()
    next(e for e in entries if e["name"] == "anomaly_detector")["status"] = "quarantined"
    mr.write_registry(entries)
    with pytest.raises(mr.ArtifactNotPromoted):
        AnomalyDetector.load(world / "models/anomaly")


def test_thermal_forecaster_load_refuses_a_tampered_model(world):
    from src.lstm_model import ThermalForecaster

    flip_byte(world / "models/forecaster/thermal.keras")
    with pytest.raises(ModelUnavailableError):
        ThermalForecaster.load(world / "models/forecaster/thermal.keras")


def test_load_scaler_accepts_a_verified_scaler_and_refuses_a_tampered_one(world):
    from src.lstm_model import DataPipeline

    scaler_path = world / "models/forecaster/scaler.json"
    ok = DataPipeline()
    ok.load_scaler(scaler_path)
    assert ok._scaler is not None

    flip_byte(scaler_path)
    bad = DataPipeline()
    with pytest.raises(ModelUnavailableError):
        bad.load_scaler(scaler_path)
    assert bad._scaler is None  # nothing was parsed


def test_save_scaler_writes_json_even_for_a_legacy_joblib_name(tmp_path):
    from src.lstm_model import DataPipeline

    pipe = DataPipeline()
    pipe._scaler = StandardScaler().fit(np.arange(30.0).reshape(10, 3))
    pipe.save_scaler(tmp_path / "scaler.joblib")
    assert (tmp_path / "scaler.json").is_file() and not (tmp_path / "scaler.joblib").exists()


def test_warn_mode_loads_a_modified_scaler_after_logging(world, monkeypatch, caplog):
    from src.lstm_model import DataPipeline

    scaler_path = world / "models/forecaster/scaler.json"
    _scaler_file(scaler_path, offset=5.0)  # a different, still-loadable scaler
    monkeypatch.setenv("ARTIFACT_VERIFY", "warn")
    pipe = DataPipeline()
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
    assert loaders.health_snapshot()["status"] == "degraded"


# ----------------------------------------------------------------------------- manifest script (verify)


def _load_script():
    spec = importlib.util.spec_from_file_location("artifact_manifest_script", ROOT / "scripts" / "artifact_manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_command_passes_and_fails_on_tampering(world):
    script = _load_script()
    assert script.main(["verify"]) == 0
    flip_byte(world / "models/forecaster/scaler.json")
    assert script.main(["verify"]) == 1


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
