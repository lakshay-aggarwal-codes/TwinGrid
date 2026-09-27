"""Tests for Phase 13's security hardening: secrets-from-file loading,
refresh-token rotation, audit logging, and the CORS production guard."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.secrets import read_secret
from models.db_models import USER_ROLE_OPERATOR, USER_ROLE_VIEWER, AuditLog, Base, RefreshToken, User


# -----------------------------------------------------------------------------
# api/secrets.py
# -----------------------------------------------------------------------------


class TestReadSecret:
    def test_plain_env_var(self, monkeypatch):
        monkeypatch.delenv("SOME_SECRET_FILE", raising=False)
        monkeypatch.setenv("SOME_SECRET", "plain-value")
        assert read_secret("SOME_SECRET") == "plain-value"

    def test_file_variant_wins_over_plain(self, monkeypatch, tmp_path):
        secret_file = tmp_path / "secret"
        secret_file.write_text("from-file-value\n")
        monkeypatch.setenv("SOME_SECRET", "plain-value")
        monkeypatch.setenv("SOME_SECRET_FILE", str(secret_file))
        assert read_secret("SOME_SECRET") == "from-file-value"

    def test_file_content_is_stripped(self, monkeypatch, tmp_path):
        secret_file = tmp_path / "secret"
        secret_file.write_text("  value-with-whitespace  \n")
        monkeypatch.setenv("SOME_SECRET_FILE", str(secret_file))
        assert read_secret("SOME_SECRET") == "value-with-whitespace"

    def test_missing_file_raises(self, monkeypatch):
        monkeypatch.setenv("SOME_SECRET_FILE", "/nonexistent/path/for/testing")
        with pytest.raises(RuntimeError, match="SOME_SECRET_FILE"):
            read_secret("SOME_SECRET")

    def test_neither_set_returns_none(self, monkeypatch):
        monkeypatch.delenv("SOME_SECRET", raising=False)
        monkeypatch.delenv("SOME_SECRET_FILE", raising=False)
        assert read_secret("SOME_SECRET") is None


# -----------------------------------------------------------------------------
# CORS production guard (api/config.py)
# -----------------------------------------------------------------------------


class TestCorsProductionGuard:
    def _reload_config(self, monkeypatch):
        import api.config as config_module

        return importlib.reload(config_module)

    def test_missing_origins_in_production_raises(self, monkeypatch):
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
            self._reload_config(monkeypatch)

    def test_missing_origins_outside_production_falls_back(self, monkeypatch):
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "development")
        config_module = self._reload_config(monkeypatch)
        assert config_module.settings.CORS_ALLOW_ORIGINS == [
            "https://digital-twin-dc-conservation.lovable.app"
        ]

    def test_explicit_origins_always_respected(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example.com, https://b.example.com")
        config_module = self._reload_config(monkeypatch)
        assert config_module.settings.CORS_ALLOW_ORIGINS == [
            "https://a.example.com",
            "https://b.example.com",
        ]
        # Restore a safe, importable state for any test that reloads api.config after this one.
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "development")
        self._reload_config(monkeypatch)


# -----------------------------------------------------------------------------
# Shared in-memory DB fixture for refresh-token / audit-log tests
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def viewer_user(db_session):
    user = User(username="viewer1", hashed_password="x", role=USER_ROLE_VIEWER)
    db_session.add(user)
    await db_session.flush()
    return user


# -----------------------------------------------------------------------------
# Refresh tokens (api/auth.py)
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")


class TestRefreshTokenLifecycle:
    @pytest.mark.asyncio
    async def test_issue_then_lookup_succeeds(self, db_session, viewer_user):
        import api.auth as auth_module

        plaintext = await auth_module.issue_refresh_token(db_session, viewer_user.id)
        token = await auth_module.get_active_refresh_token(db_session, plaintext)
        assert token is not None
        assert token.user_id == viewer_user.id

    @pytest.mark.asyncio
    async def test_plaintext_is_never_stored(self, db_session, viewer_user):
        import api.auth as auth_module

        plaintext = await auth_module.issue_refresh_token(db_session, viewer_user.id)
        token = await auth_module.get_active_refresh_token(db_session, plaintext)
        assert plaintext not in (token.token_hash,)
        assert token.token_hash != plaintext

    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self, db_session):
        import api.auth as auth_module

        assert await auth_module.get_active_refresh_token(db_session, "not-a-real-token") is None

    @pytest.mark.asyncio
    async def test_expired_token_is_rejected(self, db_session, viewer_user):
        import api.auth as auth_module

        plaintext = "already-expired-token"
        db_session.add(
            RefreshToken(
                user_id=viewer_user.id,
                token_hash=auth_module._hash_refresh_token(plaintext),
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        await db_session.flush()
        assert await auth_module.get_active_refresh_token(db_session, plaintext) is None

    @pytest.mark.asyncio
    async def test_rotation_revokes_old_and_issues_new(self, db_session, viewer_user):
        import api.auth as auth_module

        old_plaintext = await auth_module.issue_refresh_token(db_session, viewer_user.id)
        old_token = await auth_module.get_active_refresh_token(db_session, old_plaintext)
        new_plaintext = await auth_module.rotate_refresh_token(db_session, old_token)

        assert new_plaintext != old_plaintext
        # The old token is now revoked -- reusing it must fail.
        assert await auth_module.get_active_refresh_token(db_session, old_plaintext) is None
        # The new one works.
        new_token = await auth_module.get_active_refresh_token(db_session, new_plaintext)
        assert new_token is not None
        assert new_token.user_id == viewer_user.id

    @pytest.mark.asyncio
    async def test_revoke_makes_token_unusable(self, db_session, viewer_user):
        import api.auth as auth_module

        plaintext = await auth_module.issue_refresh_token(db_session, viewer_user.id)
        assert await auth_module.revoke_refresh_token(db_session, plaintext) is True
        assert await auth_module.get_active_refresh_token(db_session, plaintext) is None

    @pytest.mark.asyncio
    async def test_revoke_unknown_token_returns_false(self, db_session):
        import api.auth as auth_module

        assert await auth_module.revoke_refresh_token(db_session, "never-issued") is False


# -----------------------------------------------------------------------------
# Audit log (api/services/audit_service.py)
# -----------------------------------------------------------------------------


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_log_action_records_user_and_action(self, db_session, viewer_user):
        from api.services import audit_service

        entry = await audit_service.log_action(
            db_session,
            action="operator_registration",
            user=viewer_user,
            resource_type="user",
            resource_id=viewer_user.id,
        )
        assert entry.id is not None
        assert entry.action == "operator_registration"
        assert entry.user_id == viewer_user.id
        assert entry.username == viewer_user.username
        assert entry.resource_id == str(viewer_user.id)

    @pytest.mark.asyncio
    async def test_log_action_without_user_is_allowed(self, db_session):
        from api.services import audit_service

        entry = await audit_service.log_action(db_session, action="system_event")
        assert entry.user_id is None
        assert entry.username is None

    @pytest.mark.asyncio
    async def test_details_are_persisted(self, db_session, viewer_user):
        from api.services import audit_service

        entry = await audit_service.log_action(
            db_session,
            action="optimize_triggered",
            user=viewer_user,
            details={"alpha": 0.5, "hours": 24},
        )
        assert entry.details == {"alpha": 0.5, "hours": 24}
