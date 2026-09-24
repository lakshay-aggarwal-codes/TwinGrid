"""Tests for Phase 12's auth/security hardening."""

import importlib

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

        from models.db_models import USER_ROLE_VIEWER, User

        viewer = User(id=1, username="v", hashed_password="x", role=USER_ROLE_VIEWER)
        with pytest.raises(HTTPException) as exc_info:
            auth_module.require_operator(viewer)
        assert exc_info.value.status_code == 403

    def test_require_operator_accepts_operator(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        import api.auth as auth_module
        importlib.reload(auth_module)

        from models.db_models import USER_ROLE_OPERATOR, User

        operator = User(id=2, username="o", hashed_password="x", role=USER_ROLE_OPERATOR)
        result = auth_module.require_operator(operator)
        assert result is operator


class TestPasswordHashing:
    """passlib was replaced by direct bcrypt use."""

    @staticmethod
    def _auth(monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        import api.auth as auth_module

        importlib.reload(auth_module)
        return auth_module

    def test_hash_and_verify_round_trip(self, monkeypatch):
        auth = self._auth(monkeypatch)
        hashed = auth.hash_password("correct horse battery")
        assert isinstance(hashed, str) and hashed.startswith("$2")
        assert auth.verify_password("correct horse battery", hashed) is True
        assert auth.verify_password("wrong password", hashed) is False

    def test_passwords_longer_than_72_bytes_do_not_raise(self, monkeypatch):
        # bcrypt>=5 raises ValueError for >72 bytes; we truncate explicitly.
        auth = self._auth(monkeypatch)
        long_pw = "x" * 100
        hashed = auth.hash_password(long_pw)
        assert auth.verify_password(long_pw, hashed) is True

    def test_malformed_stored_hash_is_a_failed_login_not_an_error(self, monkeypatch):
        auth = self._auth(monkeypatch)
        assert auth.verify_password("whatever", "not-a-bcrypt-hash") is False


class TestOperatorRegistrationKey:
    @staticmethod
    def _allowed(monkeypatch, env_value, provided):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        if env_value is None:
            monkeypatch.delenv("OPERATOR_REGISTRATION_KEY", raising=False)
        else:
            monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", env_value)
        import api.auth as auth_module

        importlib.reload(auth_module)
        return auth_module.operator_registration_allowed(provided)

    def test_matching_key_is_allowed(self, monkeypatch):
        assert self._allowed(monkeypatch, "adminkey123", "adminkey123") is True

    def test_wrong_or_missing_key_is_rejected(self, monkeypatch):
        assert self._allowed(monkeypatch, "adminkey123", "nope") is False
        assert self._allowed(monkeypatch, "adminkey123", None) is False
        assert self._allowed(monkeypatch, "adminkey123", "") is False

    def test_disabled_when_env_var_unset_or_empty(self, monkeypatch):
        assert self._allowed(monkeypatch, None, "anything") is False
        assert self._allowed(monkeypatch, "", "") is False

    def test_non_ascii_key_does_not_crash(self, monkeypatch):
        assert self._allowed(monkeypatch, "adminkey123", "adminkéy") is False
