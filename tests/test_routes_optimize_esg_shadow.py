"""/api/optimize, /api/optimize/train_async, /api/optimize/jobs/{id}, /api/esg_report,
/api/shadow_mode/*, /api/equipment/health.

PPO / Redis / model files are stubbed - these tests cover the HTTP contract, auth rules,
validation and persistence, not model quality.
"""

import json
from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import select

from api.routes import optimization_routes, shadow_mode_routes
from api.services import equipment_health_service, optimization_service, shadow_mode_service
from models.db_models import AuditLog, OptimizationResult

UNAUTHENTICATED = (401, 403)
SUMMARY = {
    "mean_pue": 1.3,
    "mean_wue": 0.5,
    "mean_cooling_power_kw": 80.0,
    "total_water_consumed_L": 1200.0,
    "total_reward": -50.0,
    "safety_violations": 0,
}


@pytest.fixture
def fake_optimizer(monkeypatch):
    calls = []

    async def fake_run(alpha, beta, gamma, water_stress, hours):
        calls.append((alpha, beta, gamma, water_stress, hours))
        return [{"pue": 1.3, "timestamp": datetime(2026, 1, 1), "cooling_mode": "hybrid"}], dict(SUMMARY)

    monkeypatch.setattr(optimization_service, "run_optimization", fake_run)
    return calls


# ----------------------------------------------------------------------------- /api/optimize
async def test_optimize_requires_operator(client, viewer_headers, fake_optimizer):
    assert (await client.post("/api/optimize", json={}, headers=viewer_headers)).status_code == 403
    assert (await client.post("/api/optimize", json={})).status_code in UNAUTHENTICATED
    assert fake_optimizer == []  # the model was never invoked


async def test_optimize_defaults_persist_result_and_audit(client, operator_headers, fake_optimizer, session_maker):
    r = await client.post("/api/optimize", json={}, headers=operator_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["mean_pue"] == 1.3
    assert body["results"][0]["timestamp"] == "2026-01-01T00:00:00"  # serialised
    assert fake_optimizer == [(0.5, 0.3, 0.2, 0.0, 24)]  # schema defaults reach the service

    async with session_maker() as s:
        saved = (await s.execute(select(OptimizationResult))).scalars().all()
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "optimize_triggered"))).scalars().all()
    assert len(saved) == 1 and saved[0].hours == 24
    assert len(audit) == 1 and json.loads(json.dumps(audit[0].details))["hours"] == 24


@pytest.mark.parametrize(
    "payload",
    [{"alpha": 1.5}, {"beta": -0.1}, {"gamma": 2}, {"water_stress": 1.1}, {"hours": 0}, {"hours": 169}],
)
async def test_optimize_validation(client, operator_headers, fake_optimizer, payload):
    assert (await client.post("/api/optimize", json=payload, headers=operator_headers)).status_code == 422
    assert fake_optimizer == []


# ----------------------------------------------------------------------------- async training jobs
async def test_train_async_enqueues_job(client, operator_headers, monkeypatch):
    seen = {}

    def fake_enqueue(path, *args, **kwargs):
        seen["path"], seen["args"] = path, args
        return "job-123"

    monkeypatch.setattr(optimization_routes, "enqueue", fake_enqueue)
    r = await client.post("/api/optimize/train_async", json={"alpha": 0.6}, headers=operator_headers)
    assert r.status_code == 200 and r.json() == {"job_id": "job-123"}
    assert seen["path"] == "src.task_jobs.train_optimizer_job"
    assert seen["args"][0] == 0.6


async def test_train_async_requires_operator(client, viewer_headers):
    assert (await client.post("/api/optimize/train_async", json={}, headers=viewer_headers)).status_code == 403


async def test_job_status_operator_only_and_passthrough(client, viewer_headers, operator_headers, monkeypatch):
    monkeypatch.setattr(optimization_routes, "get_status", lambda job_id: {"job_id": job_id, "status": "queued"})
    assert (await client.get("/api/optimize/jobs/abc", headers=viewer_headers)).status_code == 403
    r = await client.get("/api/optimize/jobs/abc", headers=operator_headers)
    assert r.status_code == 200 and r.json() == {"job_id": "abc", "status": "queued"}


@pytest.mark.xfail(strict=True, reason="Stage 1: unknown job id surfaces as HTTP 500; should be 404")
async def test_unknown_job_is_404(client, operator_headers, monkeypatch):
    def boom(job_id):
        raise KeyError(job_id)  # stands in for rq.exceptions.NoSuchJobError

    monkeypatch.setattr(optimization_routes, "get_status", boom)
    assert (await client.get("/api/optimize/jobs/nope", headers=operator_headers)).status_code == 404


# ----------------------------------------------------------------------------- ESG report
async def test_esg_report_returns_pdf(client, viewer_headers, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the route writes to a relative data/reports/ path
    r = await client.get("/api/esg_report", params={"utilisation": 0.6}, headers=viewer_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert "twingrid_esg_report.pdf" in r.headers["content-disposition"]


async def test_esg_report_validation_and_auth(client, viewer_headers):
    assert (await client.get("/api/esg_report", params={"utilisation": 5}, headers=viewer_headers)).status_code == 422
    assert (await client.get("/api/esg_report")).status_code in UNAUTHENTICATED


# ----------------------------------------------------------------------------- shadow mode
class _FakeModel:
    def predict(self, obs, deterministic=True):
        return np.array([0.5, 1.0], dtype=np.float32), None


class _FakeOptimizer:
    _model = _FakeModel()


@pytest.fixture
def shadow_env(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow_mode_service, "SHADOW_LOG_PATH", tmp_path / "shadow.jsonl")

    async def fake_ensure(*a, **k):
        return _FakeOptimizer()

    monkeypatch.setattr(shadow_mode_routes, "_ensure_optimizer", fake_ensure)
    return tmp_path / "shadow.jsonl"


async def test_shadow_summary_empty(client, viewer_headers, shadow_env):
    r = await client.get("/api/shadow_mode/summary", headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["n_samples"] == 0 and r.json()["agreement_rate"] is None


async def test_shadow_sample_logs_entry_and_summary_counts_it(client, viewer_headers, shadow_env):
    r = await client.post("/api/shadow_mode/sample", headers=viewer_headers)
    assert r.status_code == 200
    entry = r.json()
    assert {"ppo_action", "rule_based_action", "actions_agree", "state"} <= entry.keys()
    assert isinstance(entry["actions_agree"], bool)
    assert 5.0 <= entry["ppo_action"]["chilled_water_temp_C"] <= 15.0

    await client.post("/api/shadow_mode/sample", headers=viewer_headers)
    assert len(shadow_env.read_text().splitlines()) == 2

    summary = (await client.get("/api/shadow_mode/summary", headers=viewer_headers)).json()
    assert summary["n_samples"] == 2 and 0.0 <= summary["agreement_rate"] <= 1.0


async def test_shadow_sample_503_when_no_optimizer(client, viewer_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(shadow_mode_service, "SHADOW_LOG_PATH", tmp_path / "shadow.jsonl")

    async def none_optimizer(*a, **k):
        return None

    monkeypatch.setattr(shadow_mode_routes, "_ensure_optimizer", none_optimizer)
    assert (await client.post("/api/shadow_mode/sample", headers=viewer_headers)).status_code == 503


@pytest.mark.parametrize("limit", [0, 5001])
async def test_shadow_summary_limit_validation(client, viewer_headers, shadow_env, limit):
    assert (
        await client.get("/api/shadow_mode/summary", params={"limit": limit}, headers=viewer_headers)
    ).status_code == 422


# ----------------------------------------------------------------------------- equipment health
async def test_equipment_health_when_no_training_run(client, viewer_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(equipment_health_service, "METRICS_PATH", tmp_path / "missing.json")
    r = await client.get("/api/equipment/health", headers=viewer_headers)
    assert r.status_code == 200 and r.json()["available"] is False


async def test_equipment_health_serves_metrics_file(client, viewer_headers, tmp_path, monkeypatch):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"lstm_rmse": 12.3, "dataset_caveat": "NASA C-MAPSS proxy"}))
    monkeypatch.setattr(equipment_health_service, "METRICS_PATH", path)
    body = (await client.get("/api/equipment/health", headers=viewer_headers)).json()
    assert body["available"] is True and body["lstm_rmse"] == 12.3
