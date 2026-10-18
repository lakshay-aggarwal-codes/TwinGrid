"""Task 18 (security review) regression tests: one test group per defect fixed.

T18-01  api/auth.py applies the strict JWT-secret rules at import (not only via `python -m api.startup_checks`)
T18-02  access tokens must carry `exp` and `sub`
T18-03  /auth/login does one bcrypt verification whether or not the account exists
T18-04  webhook failures never log the URL path/query or the exception text (which embeds the path)
T18-05  every HTTP/WebSocket route is authenticated or on an explicit public list
"""

from __future__ import annotations

import ast
import importlib
import logging
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import jwt

import api.auth as auth_module

ROOT = Path(__file__).resolve().parents[1]
SUITE_SECRET = "test-secret-for-suite-only"


# ------------------------------------------------------------------------------------------------ T18-01
def _reload_auth():
    return importlib.reload(auth_module)


def test_auth_source_delegates_to_check_jwt_secret():
    tree = ast.parse((ROOT / "api" / "auth.py").read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "check_jwt_secret" in called


def test_short_secret_is_refused_at_import_in_production(monkeypatch):
    from api.startup_checks import MIN_SECRET_LENGTH, StartupConfigError

    short = "short-secret-123"
    assert len(short) < MIN_SECRET_LENGTH
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", short)
    monkeypatch.delenv("JWT_SECRET_KEY_FILE", raising=False)
    try:
        with pytest.raises(StartupConfigError) as info:
            _reload_auth()
        assert info.value.variables == ["JWT_SECRET_KEY"]
        assert short not in str(info.value)
    finally:
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET_KEY", SUITE_SECRET)
        _reload_auth()


# ------------------------------------------------------------------------------------------------ T18-02
@pytest.mark.parametrize("missing", ["exp", "sub"])
def test_token_without_exp_or_sub_is_rejected(missing):
    claims = {"sub": "1", "role": "viewer", "exp": int(time.time()) + 900}
    del claims[missing]
    token = jwt.encode(claims, auth_module.SECRET_KEY, algorithm=auth_module.ALGORITHM)
    with pytest.raises(HTTPException) as exc:
        auth_module.decode_token(token)
    assert exc.value.status_code == 401


def test_a_normal_access_token_still_decodes():
    payload = auth_module.decode_token(auth_module.create_access_token(7, "viewer"))
    assert payload["sub"] == "7" and payload["role"] == "viewer"


# ------------------------------------------------------------------------------------------------ T18-03
def test_login_check_does_one_bcrypt_verification_for_known_and_unknown_accounts(monkeypatch):
    seen: list[str] = []
    real = auth_module.verify_password

    def spy(plain: str, hashed: str) -> bool:
        seen.append(hashed)
        return real(plain, hashed)

    monkeypatch.setattr(auth_module, "verify_password", spy)
    user = SimpleNamespace(hashed_password=auth_module.hash_password("correct-horse-battery"))

    assert auth_module.check_login_password(user, "correct-horse-battery") is True
    assert auth_module.check_login_password(user, "wrong-password-xyz") is False
    assert auth_module.check_login_password(None, "correct-horse-battery") is False  # unknown account never succeeds
    assert len(seen) == 3  # the unknown account was NOT short-circuited
    assert seen[2].startswith("$2")  # ...and was verified against a real bcrypt hash
    assert seen[2] != user.hashed_password


# ------------------------------------------------------------------------------------------------ T18-04
SECRET_PATH = "T0KEN-in-path-abc123"
HOOK = f"https://hooks.example.com/services/{SECRET_PATH}?key={SECRET_PATH}"


def test_log_target_is_host_and_opaque_id_only():
    from api.services import webhook_service as ws

    target = ws.log_target(HOOK)
    assert target.startswith("hooks.example.com [") and re.search(r"\[[0-9a-f]{16}\]$", target)
    assert SECRET_PATH not in target


@pytest.mark.parametrize("failure", ["connection", "timeout", "http_500", "blocked"])
def test_webhook_failure_logs_never_contain_the_url_path_or_exception_text(monkeypatch, caplog, failure):
    import requests

    from api.services import webhook_service as ws
    from api.services.webhook_security import WebhookURLError

    monkeypatch.setattr(ws, "validate_webhook_url", lambda url: url)
    leaking = f"HTTPSConnectionPool(host='hooks.example.com'): Max retries exceeded with url: /services/{SECRET_PATH}"
    if failure == "connection":

        def post(*a, **k):
            raise requests.ConnectionError(leaking)
    elif failure == "timeout":

        def post(*a, **k):
            raise requests.Timeout(leaking)
    elif failure == "http_500":

        def post(*a, **k):
            return SimpleNamespace(status_code=500)
    else:

        def post(*a, **k):
            raise AssertionError("must not be reached")

        def blocked(url):
            raise WebhookURLError("Webhook target resolves to a non-public address")

        monkeypatch.setattr(ws, "validate_webhook_url", blocked)
    monkeypatch.setattr(ws.requests, "post", post)

    with caplog.at_level(logging.DEBUG):
        result = ws.deliver(HOOK, {"event": "test"})

    assert result.ok is False
    assert SECRET_PATH not in caplog.text
    assert "hooks.example.com" in caplog.text


# ------------------------------------------------------------------------------------------------ T18-05
# Routes that are public on purpose, each with its own control (rate limit, key, token, probe).
PUBLIC_ROUTES = {
    "/auth/register",  # public sign-up flag + X-Admin-Key for operators
    "/auth/login",  # rate limit + lockout
    "/auth/refresh",  # opaque refresh token
    "/auth/logout",  # opaque refresh token
    "/livez",
    "/readyz",
    "/healthz",  # probes
    "/metrics",  # bearer METRICS_TOKEN (required in production)
    "/api/client-errors",  # write-only report key, size cap, rate limit
    "/ws/live",  # ticket or access token checked in the handler
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
}


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    for sub in dependant.dependencies:
        if getattr(sub, "call", None) is not None:
            names.add(getattr(sub.call, "__name__", type(sub.call).__name__))
        names |= _dependency_names(sub)
    return names


def test_every_route_is_authenticated_or_explicitly_public():
    from api.main import app

    unauthenticated = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in PUBLIC_ROUTES or getattr(route, "dependant", None) is None:
            continue
        if "get_current_user" not in _dependency_names(route.dependant):
            unauthenticated.append(f"{sorted(getattr(route, 'methods', []) or [])} {path}")
    assert unauthenticated == [], "routes with no authentication and not on PUBLIC_ROUTES: " + "; ".join(
        unauthenticated
    )
