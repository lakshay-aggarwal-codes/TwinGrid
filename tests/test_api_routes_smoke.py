"""HTTP-level smoke tests: every router is hit once through the real FastAPI
app, on in-memory SQLite.

Not covered here on purpose: the lifespan (background broadcast loop, PPO
warm-up) never runs, since httpx's ASGITransport doesn't trigger it, and the
PPO-backed endpoints (/api/optimize, /api/shadow_mode/sample) are only tested
for their auth gate -- they need trained models.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.db_models import Base

OPERATOR_KEY = "test-operator-key"
PASSWORD = "password123"


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
    monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", OPERATOR_KEY)

    # Imported lazily so the env vars above exist before api.auth is first imported.
    from api.main import app
    from api.rate_limit import limiter
    from database import get_db

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(limiter, "enabled", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    await engine.dispose()


async def _register_and_login(client: AsyncClient, username: str, role: str = "viewer") -> dict:
    headers = {"X-Admin-Key": OPERATOR_KEY} if role == "operator" else {}
    r = await client.post(
        "/auth/register",
        json={"username": username, "password": PASSWORD, "role": role},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    r = await client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()


@pytest_asyncio.fixture
async def viewer(client):
    tokens = await _register_and_login(client, "viewer1")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest_asyncio.fixture
async def operator(client):
    tokens = await _register_and_login(client, "op1", role="operator")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# -----------------------------------------------------------------------------
# Unauthenticated endpoints
# -----------------------------------------------------------------------------


async def test_healthz_reports_database_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


async def test_metrics_exposes_prometheus_text(client):
    await client.get("/healthz")
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/state",
        "/api/whatif",
        "/api/benchmark",
        "/api/simulate/1",
        "/api/alerts",
        "/api/equipment/health",
        "/api/esg_report",
        "/api/shadow_mode/summary",
    ],
)
async def test_protected_routes_reject_missing_token(client, path):
    r = await client.get(path)
    assert r.status_code in (401, 403)


async def test_protected_route_rejects_garbage_token(client):
    r = await client.get("/api/state", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


# -----------------------------------------------------------------------------
# Auth flow
# -----------------------------------------------------------------------------


async def test_register_login_refresh_logout(client):
    tokens = await _register_and_login(client, "flow_user")
    assert tokens["role"] == "viewer"

    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    rotated = r.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    # The old refresh token was rotated out and must no longer work.
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401

    r = await client.post("/auth/logout", json={"refresh_token": rotated["refresh_token"]})
    assert r.status_code == 204
    r = await client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert r.status_code == 401


async def test_login_wrong_password_is_401(client):
    await _register_and_login(client, "wrongpw")
    r = await client.post("/auth/login", json={"username": "wrongpw", "password": "not-the-password"})
    assert r.status_code == 401


async def test_duplicate_username_rejected(client):
    await _register_and_login(client, "dupe")
    r = await client.post("/auth/register", json={"username": "dupe", "password": PASSWORD})
    assert r.status_code in (400, 409)


async def test_operator_registration_needs_valid_key(client):
    body = {"username": "sneaky", "password": PASSWORD, "role": "operator"}
    assert (await client.post("/auth/register", json=body)).status_code == 403
    r = await client.post("/auth/register", json=body, headers={"X-Admin-Key": "wrong-key"})
    assert r.status_code == 403


async def test_short_password_rejected(client):
    r = await client.post("/auth/register", json={"username": "shortpw", "password": "short"})
    assert r.status_code == 422


# -----------------------------------------------------------------------------
# Digital-twin routes
# -----------------------------------------------------------------------------


async def test_authenticated_health(client, viewer):
    r = await client.get("/api/health", headers=viewer)
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


async def test_state_returns_twin_snapshot(client, viewer):
    r = await client.get("/api/state", headers=viewer, params={"utilisation": 0.6, "outside_temp": 22})
    assert r.status_code == 200
    body = r.json()
    assert "pue" in body
    assert body["pue"] >= 1.0


async def test_state_rejects_out_of_range_utilisation(client, viewer):
    r = await client.get("/api/state", headers=viewer, params={"utilisation": 1.5})
    assert r.status_code == 422


async def test_simulate_returns_hourly_rows(client, viewer):
    r = await client.get("/api/simulate/24", headers=viewer)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 24
    assert all("pue" in row for row in rows)


@pytest.mark.parametrize("hours", [0, 169])
async def test_simulate_rejects_out_of_range_hours(client, viewer, hours):
    r = await client.get(f"/api/simulate/{hours}", headers=viewer)
    assert r.status_code == 422


async def test_whatif_returns_aggregates(client, viewer):
    r = await client.get("/api/whatif", headers=viewer, params={"mode": "free_air"})
    assert r.status_code == 200
    body = r.json()
    assert body["hours"] == 24
    assert body["mean_pue"] >= 1.0
    assert body["inputs"]["mode"] == "free_air"


async def test_whatif_rejects_unknown_mode(client, viewer):
    r = await client.get("/api/whatif", headers=viewer, params={"mode": "liquid_nitrogen"})
    assert r.status_code == 422


async def test_benchmark_classifies_current_pue(client, viewer):
    r = await client.get("/api/benchmark", headers=viewer)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


# -----------------------------------------------------------------------------
# Alerts / anomaly
# -----------------------------------------------------------------------------


async def test_alerts_empty_on_fresh_db(client, viewer):
    r = await client.get("/api/alerts", headers=viewer)
    assert r.status_code == 200
    assert r.json() == []


async def test_acknowledge_requires_operator(client, viewer):
    r = await client.post("/api/alerts/1/acknowledge", headers=viewer)
    assert r.status_code == 403


async def test_acknowledge_unknown_alert_is_404(client, operator):
    r = await client.post("/api/alerts/999/acknowledge", headers=operator)
    assert r.status_code == 404


async def test_anomaly_score_returns_score_shape(client, viewer):
    recent = json.dumps([[0.5, 2.8, 30.0, 25.0, 0.5]] * 12)
    r = await client.get("/api/anomaly_score", headers=viewer, params={"recent_data": recent})
    assert r.status_code == 200
    body = r.json()
    assert {"score", "threshold", "alert", "type", "message"} <= set(body)


# -----------------------------------------------------------------------------
# Optimization / shadow mode / equipment / ESG
# -----------------------------------------------------------------------------


async def test_optimize_requires_operator(client, viewer):
    r = await client.post("/api/optimize", headers=viewer, json={})
    assert r.status_code == 403


async def test_optimize_job_lookup_requires_operator(client, viewer):
    r = await client.get("/api/optimize/jobs/does-not-exist", headers=viewer)
    assert r.status_code == 403


async def test_shadow_mode_summary_is_a_dict(client, viewer):
    r = await client.get("/api/shadow_mode/summary", headers=viewer)
    assert r.status_code == 200
    assert "n_samples" in r.json()


async def test_equipment_health_reports_availability(client, viewer):
    r = await client.get("/api/equipment/health", headers=viewer)
    assert r.status_code == 200
    assert "available" in r.json()


async def test_esg_report_returns_pdf(client, viewer, tmp_path, monkeypatch):
    pytest.importorskip("reportlab")
    monkeypatch.chdir(tmp_path)  # the route writes to a relative data/reports/ path
    r = await client.get("/api/esg_report", headers=viewer)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


# -----------------------------------------------------------------------------
# WebSocket (sync test: needs no DB, only token decoding)
# -----------------------------------------------------------------------------


def test_websocket_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from api.main import app

    # No `with` block: TestClient then skips the lifespan (no background tasks).
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/live?token=garbage"):
            pass
    assert exc.value.code == 4001


def test_websocket_accepts_valid_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
    from starlette.testclient import TestClient

    import api.auth as auth
    from api.main import app

    token = auth.create_access_token(subject=1, role="viewer")
    client = TestClient(app)
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        ws.close()
