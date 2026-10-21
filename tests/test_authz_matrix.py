"""Route x role authorization matrix (QA-001, Task 3).

Proves, over HTTP against the real app, that every route answers each role the way ``tests/authz_matrix.d/*.yaml``
says, and that nobody can add a route without declaring who may call it. See ``tests/authz_matrix.py`` for the file
format and the meaning of each status class.

Probes avoid running business logic: write requests carry the body ``[]`` (always a 422, but only after the auth
checks), path ids are made up, and the two handlers with side effects are stubbed below.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")  # api/auth.py refuses to import without it
os.environ["ENVIRONMENT"] = "development"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from api.main import app  # noqa: E402
from api.rate_limit import limiter  # noqa: E402
from api.services import audit_service  # noqa: E402
from database import get_db  # noqa: E402
from models.db_models import Base, User  # noqa: E402
from tests import authz_matrix as am  # noqa: E402

DECLARED_HTTP, DECLARED_WS = am.load_fragments()
DISCOVERED, UNKNOWN_ROUTES = am.discover(app)
HTTP_ROUTES = [r for r in DISCOVERED if r.method != "WEBSOCKET"]
BY_KEY = {r.key: r for r in HTTP_ROUTES}
# Only routes that are both served and declared are probed; the completeness tests report any difference.
PROBED = [r for r in HTTP_ROUTES if r.key in DECLARED_HTTP]


# ------------------------------------------------------------------------------------------------ fixtures


@pytest.fixture(autouse=True)
def _probe_environment(monkeypatch):
    """Probes must not depend on the developer's shell: no metrics token, no client-error key, no side effects."""
    for name in ("METRICS_TOKEN", "METRICS_TOKEN_FILE", "CLIENT_ERRORS_REPORT_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")

    from api.errors import ApiError
    from src.task_queue import JobNotFoundError

    async def _no_optimizer(*_a, **_k):
        raise ApiError(503, "model_unavailable", "authz probe: no optimizer is loaded")

    def _no_job(_job_id):
        raise JobNotFoundError("authz probe")

    # POST /api/shadow_mode/sample has no request body, so a granted caller would otherwise load the PPO policy;
    # GET /api/optimize/jobs/{id} would otherwise open a Redis connection.
    monkeypatch.setattr("api.routes.shadow_mode_routes._ensure_optimizer", _no_optimizer)
    monkeypatch.setattr("api.routes.optimization_routes.get_status", _no_job)


@pytest_asyncio.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def tokens(session_maker):
    """One real user row and access token per signed-in role (the guard loads the user from the database)."""
    import api.auth as auth_module  # looked up at call time: other tests reload it

    out = {}
    async with session_maker() as s:
        for role in ("viewer", "operator", "admin"):
            user = User(username=f"authz-{role}", hashed_password="not-a-real-hash", role=role)
            s.add(user)
            await s.commit()
            await s.refresh(user)
            out[role] = auth_module.create_access_token(user.id, role)
    return out


@pytest_asyncio.fixture
async def client(session_maker):
    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    previous = limiter.enabled
    limiter.enabled = False
    app.dependency_overrides[get_db] = override_get_db
    audit_service.set_session_factory(session_maker)
    transport = ASGITransport(app=app, raise_app_exceptions=False)  # an unhandled error comes back as a 500
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    audit_service.set_session_factory(None)
    limiter.enabled = previous


# ------------------------------------------------------------------------------------------------ the matrix


async def _probe(client, route, role, tokens):
    headers = {}
    if role != "anonymous":
        headers["Authorization"] = f"Bearer {tokens[role]}"
    kwargs = {}
    if route.method in am.WRITE_METHODS and route.has_body:
        kwargs["content"] = b"[]"
        headers["Content-Type"] = "application/json"
    return await client.request(route.method, am.sample_path(route.path_template), headers=headers, **kwargs)


@pytest.mark.parametrize("route", PROBED, ids=lambda r: f"{r.method} {r.path_template}")
async def test_every_role_gets_the_declared_outcome(client, tokens, route):
    cells = DECLARED_HTTP[route.key]
    wrong = []
    for role in am.ROLES:
        expected = cells[role]
        response = await _probe(client, route, role, tokens)
        if role == "anonymous" and expected == "401" and response.status_code != am.MISSING_CREDENTIALS_STATUS:
            wrong.append(f"anonymous: expected 401, got {response.status_code}")
        elif not am.status_matches(expected, response.status_code):
            wrong.append(f"{role}: expected {expected}, got {response.status_code}")
    assert not wrong, f"{route.method} {route.path_template}: " + "; ".join(wrong)


def test_a_route_with_an_open_anonymous_cell_is_open_for_everyone():
    for key, cells in DECLARED_HTTP.items():
        if cells["anonymous"] == "public":
            assert set(cells[r] for r in am.ROLES) <= {"public", "2xx"}, f"{key}: public route refuses a signed-in role"


# ------------------------------------------------------------------------------------------------ completeness


def test_the_harness_understands_every_route_the_app_serves():
    assert UNKNOWN_ROUTES == [], f"routes of a kind the matrix cannot probe: {UNKNOWN_ROUTES}"
    assert HTTP_ROUTES, "no routes discovered: the walk of app.routes is broken"


def test_every_served_route_is_declared_and_nothing_stale_is_declared():
    undeclared, stale = am.diff_routes(DISCOVERED, DECLARED_HTTP, DECLARED_WS)
    assert not undeclared, (
        "Routes served but missing from tests/authz_matrix.d/ (add a row to your T<n>.yaml fragment): "
        + ", ".join(undeclared)
    )
    assert not stale, "Matrix rows for routes that no longer exist (delete them): " + ", ".join(stale)


def test_a_newly_added_route_is_flagged_until_it_is_declared():
    """Proves the completeness check bites: add a real route, rediscover, expect it reported, then remove it."""
    path = "/api/__authz_matrix_dummy__"
    app.add_api_route(path, lambda: {}, methods=["GET"])
    added = app.router.routes[-1]
    try:
        discovered, _ = am.discover(app)
        undeclared, _ = am.diff_routes(discovered, DECLARED_HTTP, DECLARED_WS)
        assert f"GET {path}" in undeclared
    finally:
        app.router.routes.remove(added)
    after, _ = am.discover(app)
    assert f"GET {path}" not in am.diff_routes(after, DECLARED_HTTP, DECLARED_WS)[0]


def test_openapi_documents_no_route_the_matrix_does_not_know():
    served = {r.key for r in HTTP_ROUTES}
    documented = set()
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                documented.add((method.upper(), path))
    assert documented <= served, f"documented but not discovered: {sorted(documented - served)}"


# ------------------------------------------------------------------------------------------------ policy rules


def test_only_documented_write_routes_are_open_to_anonymous_callers():
    """A write method that does not answer 401 to anonymous must be on the public allow-list."""
    bad = []
    for (method, path), cells in DECLARED_HTTP.items():
        if method in am.WRITE_METHODS and cells["anonymous"] != "401":
            if not am.path_allowed(path, am.PUBLIC_WRITE_ALLOW_LIST):
                bad.append(f"{method} {path}")
    assert not bad, f"write routes open to anonymous callers without an allow-list entry: {bad}"


def test_a_viewer_can_only_write_where_the_allow_list_says():
    bad = []
    for (method, path), cells in DECLARED_HTTP.items():
        if method in am.WRITE_METHODS and cells["viewer"] in {"2xx", "public"} and cells["anonymous"] == "401":
            if not am.path_allowed(path, am.VIEWER_WRITE_ALLOW_LIST):
                bad.append(f"{method} {path}")
    assert not bad, f"viewer-writable routes without an allow-list entry: {bad}"


DEMO_ROUTES = [r for r in PROBED if "demo" in DECLARED_HTTP[r.key]]


@pytest_asyncio.fixture
async def demo_token(session_maker, monkeypatch):
    """A token exactly as POST /auth/demo-session mints it, for a real ``demo_viewer`` row (Task 27)."""
    from api.plugins import demo_session

    monkeypatch.setenv("DEMO_PUBLIC_ENABLED", "true")
    async with session_maker() as s:
        user = User(username=demo_session.DEMO_USERNAME, hashed_password="not-a-real-hash", role="viewer")
        s.add(user)
        await s.commit()
        await s.refresh(user)
    return demo_session.mint_demo_token(user.id, 5)


def test_the_demo_column_covers_every_write_route_that_needs_a_viewer_or_more():
    """A write route with no ``demo`` cell would rely on nothing but the middleware; make that a visible decision."""
    missing = [
        f"{m} {p}"
        for (m, p), cells in sorted(DECLARED_HTTP.items())
        if m in am.WRITE_METHODS and cells["anonymous"] == "401" and "demo" not in cells
    ]
    assert not missing, f"write routes behind a sign-in without a demo cell in tests/authz_matrix.d/: {missing}"


@pytest.mark.parametrize("route", DEMO_ROUTES, ids=lambda r: f"{r.method} {r.path_template}")
async def test_a_demo_token_gets_the_declared_outcome(client, demo_token, route):
    expected = DECLARED_HTTP[route.key]["demo"]
    response = await _probe(client, route, "demo", {"demo": demo_token})
    assert am.status_matches(
        expected, response.status_code
    ), f"{route.method} {route.path_template}: demo token expected {expected}, got {response.status_code}"
    if expected == "403" and route.method in am.WRITE_METHODS:
        assert "demo_read_only" in response.text, "a denied demo write must be the read-only guard, not another 403"


# ------------------------------------------------------------------------------------------------ websockets


@pytest.mark.parametrize("template", sorted(DECLARED_WS))
def test_websocket_refuses_anonymous_and_bad_tokens(template):
    client = TestClient(app)  # not a context manager: the lifespan (database, broadcast loop) is not started
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(template):
            pass
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{template}?token=not-a-token"):
            pass
    assert exc.value.code == 4001
