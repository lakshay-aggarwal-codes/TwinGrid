"""T29: POST /api/optimize serves a promoted policy, reports its lineage, and answers 503 for everything else."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from api.services import optimization_service as svc
from models.db_models import OptimizationResult
from src import model_registry as mr
from src import versions
from src.artifacts import loaders
from tests.test_optimization_service import _register

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mr, "REGISTRY_PATH", tmp_path / "models" / "registry.json")
    for var in ("ARTIFACT_VERIFY", "ARTIFACT_COMPAT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_SHA", "a" * 40)
    loaders.reset_for_tests()
    monkeypatch.setattr(svc, "_optimizer", None)
    monkeypatch.setattr(svc, "_train_lock", asyncio.Lock())
    monkeypatch.setattr(svc, "_last_unavailable_at", None)
    (tmp_path / "models").mkdir()
    yield tmp_path
    loaders.reset_for_tests()


async def test_optimize_carries_model_id_versions_and_carbon_flag(client, operator_headers, world, session_maker):
    entry = _register(world, "promoted")
    r = await client.post("/api/optimize", json={"hours": 1}, headers=operator_headers)
    assert r.status_code == 200, r.text
    summary = r.json()["summary"]
    assert summary["model_id"] == entry["model_id"]
    assert summary["physics_version"] == versions.active_physics_version()
    assert summary["environment_version"] == versions.ENV_VERSION
    assert isinstance(summary["carbon_is_fallback"], bool)
    assert len(r.json()["results"]) == svc.STEPS_PER_HOUR
    async with session_maker() as s:
        assert len((await s.execute(select(OptimizationResult))).scalars().all()) == 1


@pytest.mark.parametrize("status", ["candidate", "rejected", "quarantined"])
async def test_optimize_is_503_for_a_policy_that_is_not_promoted(
    client, operator_headers, world, session_maker, status
):
    _register(world, status)
    r = await client.post("/api/optimize", json={"hours": 1}, headers=operator_headers)
    assert r.status_code == 503 and r.json()["type"] == "urn:twingrid:error:model_unavailable"
    async with session_maker() as s:
        assert (await s.execute(select(OptimizationResult))).scalars().all() == []


async def test_optimize_is_503_when_the_promoted_policy_was_tampered_with(client, operator_headers, world):
    entry = _register(world, "promoted")
    target = world / entry["relative_path"] / "policy.npz"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    r = await client.post("/api/optimize", json={"hours": 1}, headers=operator_headers)
    assert r.status_code == 503


async def test_a_real_trained_candidate_serves_once_it_is_promoted(client, operator_headers, world):
    """The shipped baseline candidates are NOT promoted. Copy one into a throw-away root, promote the COPY, serve it."""
    shipped = json.loads((ROOT / "models" / "registry.json").read_text())["artifacts"]
    entry = next(
        e for e in shipped if e["kind"] == "ppo" and e["model_id"].endswith("-s0") and "ppo-p1-e2-c" in e["model_id"]
    )
    rel = entry["relative_path"]
    shutil.copytree(ROOT / rel, world / rel)
    # The sandbox that trained the shipped candidates had no git, so their code_revision is null and the gate (T19) would
    # refuse to serve them even if promoted -- correct, and why they must be retrained on a git checkout before T30.
    # The COPY below gets a revision, as a clean-tree run would.
    assert entry["code_revision"] is None or len(entry["code_revision"]) >= 40
    copy = {**entry, "status": "promoted", "code_revision": "c" * 40}
    mr.write_registry([copy])
    r = await client.post("/api/optimize", json={"hours": 2, "water_stress": 0.0}, headers=operator_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["model_id"] == entry["model_id"]
    assert len(body["results"]) == 2 * svc.STEPS_PER_HOUR
    assert all(0 <= row["pue"] < 10 for row in body["results"])
    # and the shipped registry itself still has it as a candidate (promotion is T30's job)
    assert next(e for e in shipped if e["model_id"] == entry["model_id"])["status"] == "candidate"
