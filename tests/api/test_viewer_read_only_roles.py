"""Viewer is read-only; operator keeps full access; admin has everything an operator has.

Role x route matrix for every state-changing route that is guarded by ``require_operator`` (``User.can_operate``) plus
``GET /api/simulate/{hours}?persist=true``. Viewer -> 403 (audited as ``permission_denied``); operator and admin -> past the
role check (any status except 401/403: a probe body of ``[]`` is never a valid request model, so FastAPI answers 422
only AFTER authentication and the role check ran, and no business logic runs).

Decision recorded here (see the task report): ``GET /api/simulate`` and ``GET /api/whatif`` stay open to viewers on the
server because they write nothing; the UI locks them for viewers.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from api.routes import shadow_mode_routes
from models.db_models import AuditLog, SimulationRun, User


@pytest.fixture(autouse=True)
def _access_env(monkeypatch):
    # GET /api/admin/access-requests is feature-gated; the same setup tests/api/test_access_requests.py uses.
    monkeypatch.setenv("ACCESS_TOKEN_PEPPER", "test-pepper-0123456789abcdef-0123456789abcdef")
    monkeypatch.setenv("ACCESS_NOTIFY_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("ACCESS_PUBLIC_BASE_URL", "https://twingrid.example")
    monkeypatch.delenv("ACCESS_REQUESTS_ENABLED", raising=False)


@pytest.fixture
async def admin_headers(make_user):
    _, headers = await make_user("admin1", "admin")
    return headers


@pytest.fixture(autouse=True)
def _no_real_shadow_model(monkeypatch):
    """The shadow-sample handler would try to load a model once the role check passes; make it answer 503 instead."""

    async def none_optimizer(*a, **k):
        return None

    monkeypatch.setattr(shadow_mode_routes, "_ensure_optimizer", none_optimizer)


# (method, path) for every route that requires an operating role. Bodies are the invalid probe ``[]`` (see docstring).
OPERATOR_WRITES = [
    ("POST", "/api/optimize"),
    ("POST", "/api/optimize/train_async"),
    ("POST", "/api/shadow_mode/sample"),
    ("POST", "/api/webhooks"),
    ("DELETE", "/api/webhooks"),
    ("POST", "/api/alerts/1/acknowledge"),
    ("PATCH", "/api/alerts/1"),
    ("POST", "/api/assets/1/move"),
    ("POST", "/api/assets/1/edges"),
    ("POST", "/api/edges/1/close"),
    # already operator-or-admin before this change; pinned here so the three roles stay consistent
    ("POST", "/api/maintenance/work-orders"),
    ("PATCH", "/api/maintenance/work-orders/1"),
    ("POST", "/api/maintenance/work-orders/1/status"),
    ("POST", "/api/optimizer/proposals"),
]


def _call(client, method, path, headers):
    return client.request(method, path, headers=headers, json=[])


@pytest.mark.parametrize(("method", "path"), OPERATOR_WRITES)
async def test_viewer_is_refused_every_operator_write(client, viewer_headers, method, path):
    assert (await _call(client, method, path, viewer_headers)).status_code == 403


@pytest.mark.parametrize(("method", "path"), OPERATOR_WRITES)
async def test_operator_passes_the_role_check(client, operator_headers, method, path):
    assert (await _call(client, method, path, operator_headers)).status_code not in (401, 403)


@pytest.mark.parametrize(("method", "path"), OPERATOR_WRITES)
async def test_admin_passes_every_operator_check(client, admin_headers, method, path):
    assert (await _call(client, method, path, admin_headers)).status_code not in (401, 403)


@pytest.mark.parametrize(("method", "path"), OPERATOR_WRITES)
async def test_anonymous_is_still_refused(client, method, path):
    assert (await client.request(method, path, json=[])).status_code in (401, 403)


async def test_viewer_refusal_is_audited_as_permission_denied(client, viewer_headers, session_maker):
    assert (await client.post("/api/optimize", json={}, headers=viewer_headers)).status_code == 403
    async with session_maker() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "permission_denied"))).scalars().all()
    assert rows, "a refused viewer write must leave a permission_denied audit row"


# ----------------------------------------------------------------------------- persisted simulation
async def test_viewer_cannot_persist_a_simulation_and_nothing_is_written(client, viewer_headers, session_maker):
    assert (await client.get("/api/simulate/2?persist=true", headers=viewer_headers)).status_code == 403
    async with session_maker() as s:
        assert (await s.execute(select(SimulationRun))).scalars().all() == []


@pytest.mark.parametrize("role", ["operator", "admin"])
async def test_operator_and_admin_can_persist_a_simulation(client, session_maker, make_user, role):
    _, headers = await make_user(f"persist-{role}", role)
    assert (await client.get("/api/simulate/2?persist=true", headers=headers)).status_code == 200
    async with session_maker() as s:
        assert len((await s.execute(select(SimulationRun))).scalars().all()) == 1


# ----------------------------------------------------------------------------- viewer reads stay open
@pytest.mark.parametrize("path", ["/api/alerts", "/api/simulate/24", "/api/whatif"])
async def test_viewer_can_still_read_and_run_the_side_effect_free_gets(client, viewer_headers, path):
    assert (await client.get(path, headers=viewer_headers)).status_code == 200


async def test_viewer_simulate_without_persist_writes_nothing(client, viewer_headers, session_maker):
    assert (await client.get("/api/simulate/2", headers=viewer_headers)).status_code == 200
    async with session_maker() as s:
        assert (await s.execute(select(SimulationRun))).scalars().all() == []


# ----------------------------------------------------------------------------- admin console stays admin-only
async def test_viewer_and_operator_cannot_read_the_access_request_queue_but_admin_can(
    client, viewer_headers, operator_headers, admin_headers
):
    url = "/api/admin/access-requests"
    assert (await client.get(url, headers=viewer_headers)).status_code == 403
    assert (await client.get(url, headers=operator_headers)).status_code == 403
    assert (await client.get(url, headers=admin_headers)).status_code == 200


# ----------------------------------------------------------------------------- the one definition
@pytest.mark.parametrize(
    ("role", "expected"), [("viewer", False), ("operator", True), ("admin", True), ("", False), ("root", False)]
)
def test_can_operate_is_the_single_definition(role, expected):
    user = User(id=1, username="u", hashed_password="x", role=role)
    assert user.can_operate() is expected
    assert user.is_operator() is expected  # the legacy name is an alias, never a second definition
