"""/healthz, /api/health, /metrics and request-id middleware."""

import pytest

from api.main import app
from database import get_db

UNAUTHENTICATED = (401, 403)  # FastAPI changed HTTPBearer's missing-credentials code across versions


async def test_healthz_ok_without_auth(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"


async def test_healthz_returns_503_when_db_down(client, caplog):
    secret = "postgresql://user:hunter2@internal-db.example:5432/twingrid refused"

    class BrokenSession:
        async def execute(self, *a, **k):
            raise RuntimeError(secret)

    async def broken_db():
        yield BrokenSession()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = broken_db
    try:
        with caplog.at_level("ERROR"):
            r = await client.get("/healthz")
    finally:
        app.dependency_overrides[get_db] = previous
    assert r.status_code == 503
    assert r.json() == {"detail": "Service unavailable"}
    assert "hunter2" not in r.text and "internal-db" not in r.text and "RuntimeError" not in r.text
    # The raw exception is still recorded server-side.
    assert any("hunter2" in (rec.exc_text or "") or rec.exc_info for rec in caplog.records)


async def test_api_health_requires_token(client):
    assert (await client.get("/api/health")).status_code in UNAUTHENTICATED


async def test_api_health_with_token(client, viewer_headers):
    r = await client.get("/api/health", headers=viewer_headers)
    assert r.status_code == 200 and r.json()["status"] == "healthy"


async def test_bad_token_is_401(client):
    r = await client.get("/api/health", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


async def test_expired_token_is_401(client):
    from datetime import datetime, timedelta, timezone

    from jose import jwt

    import api.auth as auth_module

    token = jwt.encode(
        {"sub": "1", "role": "viewer", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        auth_module.SECRET_KEY,
        algorithm=auth_module.ALGORITHM,
    )
    r = await client.get("/api/health", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_token_for_deleted_user_is_401(client):
    import api.auth as auth_module

    token = auth_module.create_access_token(999999, "viewer")
    r = await client.get("/api/health", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_request_id_generated_and_echoed(client):
    generated = await client.get("/healthz")
    assert generated.headers.get("X-Request-ID")

    echoed = await client.get("/healthz", headers={"X-Request-ID": "abc-12345.x_y"})
    assert echoed.headers["X-Request-ID"] == "abc-12345.x_y"


async def test_metrics_endpoint_exposes_request_counters(client):
    await client.get("/healthz")
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text
    assert 'path="/healthz"' in r.text  # route template, not raw URL (cardinality guard)


@pytest.mark.parametrize("path", ["/api/state", "/api/whatif", "/api/simulate/24", "/api/benchmark", "/api/alerts"])
async def test_protected_routes_reject_anonymous(client, path):
    assert (await client.get(path)).status_code in UNAUTHENTICATED
