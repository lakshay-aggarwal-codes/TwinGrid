"""T4a: /ws/live session controls -- token expiry, connection caps, inbound
size/rate limits, Origin allowlist, and query-string token redaction."""

import logging
import threading
import time

import pytest
from jose import jwt
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.auth as auth_module
from api.main import app
from api.routes import websocket_routes as ws_routes
from api.services.live_broadcast_service import ConnectionLimitExceeded, ConnectionManager, manager


def _token(user_id=1, role="viewer", exp_in=900, **overrides):
    claims = {"sub": str(user_id), "role": role, "exp": int(time.time()) + exp_in}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, auth_module.SECRET_KEY, algorithm=auth_module.ALGORITHM)


def _url(token):
    return f"/ws/live?token={token}"


def _wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture(autouse=True)
def clean_manager():
    def _reset():
        manager._connections.clear()
        manager._owners.clear()
        manager._per_user.clear()

    _reset()
    yield
    _reset()


@pytest.fixture
def client():
    return TestClient(app)  # no context manager -> lifespan (DB, broadcast loop) not started


def _expect_close(ws, code, timeout=6.0):
    """Assert the server closes the socket with ``code``. Fails (instead of hanging
    the suite) if the server never closes it."""
    outcome: dict = {}

    def _receive():
        try:
            outcome["message"] = ws.receive_text()
        except WebSocketDisconnect as exc:
            outcome["code"] = exc.code
        except Exception as exc:  # pragma: no cover - surfaced below
            outcome["error"] = exc

    worker = threading.Thread(target=_receive, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        ws.close()  # unblocks the reader
        worker.join(2)
        pytest.fail(f"server did not close the socket within {timeout}s (expected close code {code})")
    assert "error" not in outcome, outcome.get("error")
    assert outcome.get("code") == code, outcome


# ----------------------------------------------------------------------------- token expiry
def test_socket_is_closed_with_4002_when_the_access_token_expires(client):
    started = time.time()
    with client.websocket_connect(_url(_token(exp_in=2))) as ws:
        assert _wait_until(manager.has_connections)  # valid at connect time
        _expect_close(ws, ws_routes.WS_CLOSE_TOKEN_EXPIRED)
    assert time.time() - started < 6
    assert _wait_until(lambda: not manager.has_connections())
    assert manager._owners == {} and manager._per_user == {}


def test_already_expired_token_is_rejected_at_the_handshake(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(_url(_token(exp_in=-10))):
            pass
    assert exc.value.code == ws_routes.WS_CLOSE_INVALID_TOKEN


@pytest.mark.parametrize("missing", ["exp", "sub"])
def test_token_without_exp_or_sub_is_rejected(client, missing):
    # A token that never expires (or has no subject) must not be usable for a socket.
    claims = {"sub": "1", "role": "viewer", "exp": int(time.time()) + 900}
    del claims[missing]
    tok = jwt.encode(claims, auth_module.SECRET_KEY, algorithm=auth_module.ALGORITHM)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(_url(tok)):
            pass
    assert exc.value.code == ws_routes.WS_CLOSE_INVALID_TOKEN


# ----------------------------------------------------------------------------- connection caps
def test_per_user_cap_closes_the_extra_socket_and_frees_on_disconnect(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_USER", "2")
    tok = _token(user_id=7)
    with client.websocket_connect(_url(tok)) as a, client.websocket_connect(_url(tok)) as b:
        assert _wait_until(lambda: len(manager._owners) == 2)
        with client.websocket_connect(_url(tok)) as c:
            _expect_close(c, ws_routes.WS_CLOSE_CONNECTION_LIMIT)
        assert len(manager._owners) == 2  # the rejected socket was never registered

        # A different user is unaffected by user 7's cap.
        with client.websocket_connect(_url(_token(user_id=8))):
            assert _wait_until(lambda: len(manager._owners) == 3)
        assert _wait_until(lambda: len(manager._owners) == 2)
        del a, b
    assert _wait_until(lambda: len(manager._owners) == 0)
    assert manager._per_user == {}

    # Slots are reusable after everyone left.
    with client.websocket_connect(_url(tok)):
        assert _wait_until(lambda: len(manager._owners) == 1)


def test_global_cap_applies_across_users(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_CONNECTIONS_GLOBAL", "2")
    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_USER", "10")
    with client.websocket_connect(_url(_token(user_id=1))), client.websocket_connect(_url(_token(user_id=2))):
        assert _wait_until(lambda: len(manager._owners) == 2)
        with client.websocket_connect(_url(_token(user_id=3))) as c:
            _expect_close(c, ws_routes.WS_CLOSE_CONNECTION_LIMIT)


def test_manager_connect_is_atomic_and_disconnect_idempotent():
    m = ConnectionManager()
    a, b, c = object(), object(), object()
    m.connect(a, "u1", max_per_user=1, max_global=2)
    with pytest.raises(ConnectionLimitExceeded) as e1:
        m.connect(b, "u1", max_per_user=1, max_global=2)
    assert e1.value.scope == "user"
    m.connect(b, "u2", max_per_user=1, max_global=2)
    with pytest.raises(ConnectionLimitExceeded) as e2:
        m.connect(c, "u3", max_per_user=1, max_global=2)
    assert e2.value.scope == "global"
    assert len(m._owners) == 2
    m.disconnect(a)
    m.disconnect(a)  # idempotent
    m.disconnect(c)  # never registered
    assert m._per_user == {"u2": 1}


def test_manager_without_caps_behaves_as_before():
    m = ConnectionManager()
    socks = [object() for _ in range(50)]
    for s in socks:
        m.connect(s)  # old call signature, no caps
    assert m.has_connections() and len(m._connections) == 50


def test_cap_keeps_counting_a_socket_that_broadcast_dropped_until_disconnect():
    m = ConnectionManager()
    a = object()
    m.connect(a, "u1", max_per_user=1)
    m._connections.discard(a)  # what broadcast() does for a failed send
    with pytest.raises(ConnectionLimitExceeded):
        m.connect(object(), "u1", max_per_user=1)
    m.disconnect(a)
    m.connect(object(), "u1", max_per_user=1)


# ----------------------------------------------------------------------------- inbound limits
def test_oversized_inbound_message_closes_with_1009(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_MESSAGE_BYTES", "64")
    with client.websocket_connect(_url(_token())) as ws:
        ws.send_text("x" * 65)
        _expect_close(ws, ws_routes.WS_CLOSE_MESSAGE_TOO_BIG)
    assert _wait_until(lambda: not manager.has_connections())


def test_oversized_binary_message_also_closes_with_1009(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_MESSAGE_BYTES", "64")
    with client.websocket_connect(_url(_token())) as ws:
        ws.send_bytes(b"x" * 65)
        _expect_close(ws, ws_routes.WS_CLOSE_MESSAGE_TOO_BIG)


def test_multibyte_text_is_measured_in_bytes_not_characters(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_MESSAGE_BYTES", "10")
    with client.websocket_connect(_url(_token())) as ws:
        ws.send_text("é" * 6)  # 6 characters, 12 bytes
        _expect_close(ws, ws_routes.WS_CLOSE_MESSAGE_TOO_BIG)


def test_message_at_the_size_limit_is_allowed(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_MESSAGE_BYTES", "64")
    with client.websocket_connect(_url(_token())) as ws:
        ws.send_text("x" * 64)
        time.sleep(0.2)
        assert manager.has_connections()
        ws.close()


def test_inbound_rate_limit_closes_with_4005(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_MESSAGES_PER_MINUTE", "3")
    with client.websocket_connect(_url(_token())) as ws:
        for _ in range(4):
            ws.send_text("ping")
        _expect_close(ws, ws_routes.WS_CLOSE_RATE_LIMIT)
    assert _wait_until(lambda: not manager.has_connections())


def test_messages_within_the_rate_are_not_closed(client, monkeypatch):
    monkeypatch.setenv("WS_MAX_MESSAGES_PER_MINUTE", "3")
    with client.websocket_connect(_url(_token())) as ws:
        for _ in range(3):
            ws.send_text("ping")
        time.sleep(0.2)
        assert manager.has_connections()
        ws.close()


# ----------------------------------------------------------------------------- Origin allowlist
def test_origin_not_on_allowlist_is_rejected_at_the_handshake(client, monkeypatch):
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://app.example.com")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(_url(_token()), headers={"origin": "https://evil.example"}):
            pass
    assert exc.value.code == ws_routes.WS_CLOSE_ORIGIN_NOT_ALLOWED
    assert not manager.has_connections()


def test_origin_on_allowlist_is_accepted_normalised(client, monkeypatch):
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://app.example.com, https://other.example.com/")
    for origin in ("https://app.example.com", "HTTPS://App.Example.com/", "https://other.example.com"):
        with client.websocket_connect(_url(_token()), headers={"origin": origin}):
            assert _wait_until(manager.has_connections)
        assert _wait_until(lambda: not manager.has_connections())


def test_origin_is_not_enforced_when_no_allowlist_is_configured(client, monkeypatch):
    monkeypatch.delenv("WS_ALLOWED_ORIGINS", raising=False)
    with client.websocket_connect(_url(_token()), headers={"origin": "https://anything.example"}):
        assert _wait_until(manager.has_connections)


def test_missing_origin_header_is_allowed_even_with_an_allowlist(client, monkeypatch):
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://app.example.com")
    with client.websocket_connect(_url(_token())):  # TestClient sends no Origin
        assert _wait_until(manager.has_connections)


@pytest.mark.parametrize(
    "origin,allowed,expected",
    [
        (None, (), True),
        ("https://a", (), True),
        (None, ("https://a",), True),
        ("https://a", ("https://a",), True),
        ("https://b", ("https://a",), False),
        ("null", ("https://a",), False),
        ("https://a.evil", ("https://a",), False),
        ("http://a", ("https://a",), False),
    ],
)
def test_origin_allowed_matrix(origin, allowed, expected):
    assert ws_routes.origin_allowed(origin, allowed) is expected


def test_origin_is_checked_before_the_token(client, monkeypatch):
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://app.example.com")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(_url("not-a-token"), headers={"origin": "https://evil.example"}):
            pass
    assert exc.value.code == ws_routes.WS_CLOSE_ORIGIN_NOT_ALLOWED


# ----------------------------------------------------------------------------- limits config
def test_limits_fall_back_to_strict_defaults_on_bad_values(monkeypatch):
    from api.config import load_ws_limits

    for name in ("WS_MAX_CONNECTIONS_PER_USER", "WS_MAX_CONNECTIONS_GLOBAL", "WS_MAX_MESSAGE_BYTES"):
        monkeypatch.setenv(name, "0")  # "no limit" must not be expressible
    monkeypatch.setenv("WS_MAX_MESSAGES_PER_MINUTE", "lots")
    limits = load_ws_limits()
    assert (limits.max_connections_per_user, limits.max_connections_global) == (5, 200)
    assert (limits.max_message_bytes, limits.max_messages_per_minute) == (1024, 30)


def test_limits_are_overridable_from_env(monkeypatch):
    from api.config import load_ws_limits

    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_USER", "9")
    monkeypatch.setenv("WS_MAX_CONNECTIONS_GLOBAL", "11")
    monkeypatch.setenv("WS_MAX_MESSAGE_BYTES", "13")
    monkeypatch.setenv("WS_MAX_MESSAGES_PER_MINUTE", "17")
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://X.example/")
    limits = load_ws_limits()
    assert (limits.max_connections_per_user, limits.max_connections_global) == (9, 11)
    assert (limits.max_message_bytes, limits.max_messages_per_minute) == (13, 17)
    assert limits.allowed_origins == ("https://x.example",)


# ----------------------------------------------------------------------------- token redaction in logs
SECRET_TOKEN = "eyJhbGciOiJIUzI1NiJ9.SUPERSECRETPAYLOAD.signaturepart"


@pytest.mark.parametrize("logger_name", ["uvicorn", "uvicorn.error", "uvicorn.access", "websockets.server"])
def test_server_logs_do_not_contain_the_query_string_token(caplog, logger_name):
    caplog.set_level(logging.INFO, logger=logger_name)
    logging.getLogger(logger_name).info(
        '%s - "WebSocket %s" [accepted]', "10.0.0.1:5555", f"/ws/live?token={SECRET_TOKEN}"
    )
    assert "SUPERSECRETPAYLOAD" not in caplog.text
    assert "/ws/live?token=[REDACTED]" in caplog.text


def test_redaction_keeps_other_query_parameters():
    assert ws_routes.redact_token("/ws/live?a=1&token=abc.def&b=2") == "/ws/live?a=1&token=[REDACTED]&b=2"
    assert ws_routes.redact_token("/ws/live?TOKEN=abc") == "/ws/live?TOKEN=[REDACTED]"
    assert ws_routes.redact_token("nothing to see") == "nothing to see"


def test_redaction_handles_dict_args_and_non_string_args(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.access")
    logging.getLogger("uvicorn.access").info("%(path)s %(n)d", {"path": f"/ws/live?token={SECRET_TOKEN}", "n": 3})
    logging.getLogger("uvicorn.access").info("%s %d", f"/ws/live?token={SECRET_TOKEN}", 4)
    assert "SUPERSECRETPAYLOAD" not in caplog.text


def test_install_is_idempotent():
    ws_routes.install_token_redaction()
    ws_routes.install_token_redaction()
    for name in ws_routes._REDACTED_LOGGERS:
        filters = [f for f in logging.getLogger(name).filters if isinstance(f, ws_routes.TokenRedactionFilter)]
        assert len(filters) == 1


def test_endpoint_never_logs_the_token_across_connect_reject_and_close(client, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_USER", "1")
    tok = _token(user_id=3)
    with client.websocket_connect(_url(tok)):
        assert _wait_until(manager.has_connections)
        with client.websocket_connect(_url(tok)) as over_cap:
            _expect_close(over_cap, ws_routes.WS_CLOSE_CONNECTION_LIMIT)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(_url("bad." + SECRET_TOKEN)):
            pass
    assert tok not in caplog.text
    assert "SUPERSECRETPAYLOAD" not in caplog.text
