"""Tests for Phase 12's auth/security hardening."""

import importlib
import os

import pytest
from fastapi import HTTPException


class TestJWTSecretEnforcement:
    def test_missing_secret_raises_at_import(self, monkeypatch):
        """Regression test: pre-Phase-12, a missing JWT_SECRET_KEY silently
        fell back to a hardcoded placeholder string. Post-fix, it must
        refuse to import at all."""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        import api.auth as auth_module

        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            importlib.reload(auth_module)

        # Restore a valid state for any tests that import api.auth after this one.
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        importlib.reload(auth_module)

    def test_present_secret_allows_import(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        import api.auth as auth_module
        importlib.reload(auth_module)
        assert auth_module.SECRET_KEY == "test-secret-for-suite-only"


class TestTokenValidation:
    def test_invalid_token_raises_401(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        import api.auth as auth_module
        importlib.reload(auth_module)

        with pytest.raises(HTTPException) as exc_info:
            auth_module.decode_token("not-a-real-token")
        assert exc_info.value.status_code == 401

    def test_valid_token_round_trips(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        import api.auth as auth_module
        importlib.reload(auth_module)

        token = auth_module.create_access_token(subject=1, role="viewer")
        payload = auth_module.decode_token(token)
        assert payload["sub"] == "1"
        assert payload["role"] == "viewer"


class TestRoleEnforcement:
    def test_require_operator_rejects_viewer(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        import api.auth as auth_module
        importlib.reload(auth_module)

        from models.db_models import User, USER_ROLE_VIEWER

        viewer = User(id=1, username="v", hashed_password="x", role=USER_ROLE_VIEWER)
        with pytest.raises(HTTPException) as exc_info:
            auth_module.require_operator(viewer)
        assert exc_info.value.status_code == 403

    def test_require_operator_accepts_operator(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        import api.auth as auth_module
        importlib.reload(auth_module)

        from models.db_models import User, USER_ROLE_OPERATOR

        operator = User(id=2, username="o", hashed_password="x", role=USER_ROLE_OPERATOR)
        result = auth_module.require_operator(operator)
        assert result is operator