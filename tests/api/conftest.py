"""Shared fixtures for HTTP-level API tests.

Design:
* The real FastAPI app (api.main.app) is exercised through httpx's ASGITransport.
* The DB dependency is overridden with an in-memory SQLite engine, so no Postgres is needed.
* The app lifespan is NOT run (ASGITransport doesn't), so the broadcast loop, init_db and
  PPO warm-up never start.
* slowapi rate limiting is disabled by default; tests that check it switch it on.
"""

import os

# Must be set BEFORE api.* is imported (api/auth.py refuses to import without it).
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")
os.environ["ENVIRONMENT"] = "development"  # production requires CORS_ALLOWED_ORIGINS

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from api.main import app  # noqa: E402
from api.rate_limit import limiter  # noqa: E402
from api.services import audit_service  # noqa: E402
from database import get_db  # noqa: E402
from models.db_models import Base, User  # noqa: E402


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


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

    previous_enabled = limiter.enabled
    limiter.enabled = False
    app.dependency_overrides[get_db] = override_get_db
    # T15: best-effort audit rows use an INDEPENDENT session; point it at the test engine too.
    audit_service.set_session_factory(session_maker)
    # raise_app_exceptions=False -> an unhandled server error comes back as HTTP 500
    # instead of being re-raised inside the test.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    audit_service.set_session_factory(None)
    limiter.enabled = previous_enabled


@pytest.fixture
def make_user(session_maker):
    """Factory: create a user row directly and return (user, auth_headers)."""

    async def _make(username: str = "user1", role: str = "viewer"):
        import api.auth as auth_module  # looked up at call time (other tests reload it)

        async with session_maker() as s:
            user = User(username=username, hashed_password="not-a-real-hash", role=role)
            s.add(user)
            await s.commit()
            await s.refresh(user)
        token = auth_module.create_access_token(user.id, role)
        return user, {"Authorization": f"Bearer {token}"}

    return _make


@pytest_asyncio.fixture
async def viewer_headers(make_user):
    _, headers = await make_user("viewer1", "viewer")
    return headers


@pytest_asyncio.fixture
async def operator_headers(make_user):
    _, headers = await make_user("operator1", "operator")
    return headers


@pytest.fixture
def count_rows(session_maker):
    """await count_rows(Model[, where_clause]) -> int"""

    async def _count(model, *where):
        async with session_maker() as s:
            stmt = select(func.count()).select_from(model)
            for clause in where:
                stmt = stmt.where(clause)
            return (await s.execute(stmt)).scalar_one()

    return _count
