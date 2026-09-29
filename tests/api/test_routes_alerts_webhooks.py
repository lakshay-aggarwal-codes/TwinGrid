"""/api/anomaly_score (model stubbed), /api/alerts, /api/alerts/{id}/acknowledge, /api/webhooks."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from api.services import anomaly_service, webhook_service
from models.db_models import Alert, AuditLog

WINDOW = json.dumps([[30.0, 3.0, 35.0, 300.0, 50.0]] * 12)
UNAUTHENTICATED = (401, 403)


def _fake_score(**overrides):
    result = {
        "score": 0.01,
        "threshold": 1.0,
        "alert": False,
        "type": "normal",
        "message": "No anomalies detected",
        "explanation": None,
    }
    result.update(overrides)
    return lambda _raw: result


async def _seed_alerts(session_maker, n=5):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with session_maker() as s:
        for i in range(n):
            s.add(
                Alert(
                    score=float(i),
                    alert=True,
                    type="thermal_spike",
                    message=f"m{i}",
                    severity="WARNING",
                    created_at=base + timedelta(minutes=i),
                )
            )
        await s.commit()


# ----------------------------------------------------------------------------- anomaly_score
async def test_anomaly_score_requires_auth(client):
    assert (await client.get("/api/anomaly_score", params={"recent_data": WINDOW})).status_code in UNAUTHENTICATED


async def test_anomaly_score_requires_recent_data(client, viewer_headers):
    assert (await client.get("/api/anomaly_score", headers=viewer_headers)).status_code == 422


async def test_normal_score_is_not_persisted_and_no_webhook(client, viewer_headers, monkeypatch, count_rows):
    sent = []

    async def fake_dispatch(payload):
        sent.append(payload)

    monkeypatch.setattr(anomaly_service, "score_recent_data", _fake_score())
    monkeypatch.setattr(webhook_service, "dispatch_alert", fake_dispatch)

    r = await client.get("/api/anomaly_score", params={"recent_data": WINDOW}, headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["alert"] is False
    assert await count_rows(Alert) == 0
    assert sent == []


async def test_real_alert_is_persisted_with_severity_and_dispatched(client, viewer_headers, monkeypatch, count_rows):
    sent = []

    async def fake_dispatch(payload):
        sent.append(payload)

    monkeypatch.setattr(
        anomaly_service,
        "score_recent_data",
        _fake_score(
            score=3.0,
            threshold=1.0,
            alert=True,
            type="thermal_spike",
            message="Outlet temperature spike detected",
            explanation={"top_feature": "server_outlet_temp_C"},
        ),
    )
    monkeypatch.setattr(webhook_service, "dispatch_alert", fake_dispatch)

    r = await client.get("/api/anomaly_score", params={"recent_data": WINDOW}, headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["explanation"]["top_feature"] == "server_outlet_temp_C"
    assert await count_rows(Alert) == 1
    assert len(sent) == 1 and sent[0]["type"] == "thermal_spike"

    alerts = (await client.get("/api/alerts", headers=viewer_headers)).json()
    assert alerts[0]["severity"] == "CRITICAL"  # score 3.0 > 2 x threshold 1.0


def test_alert_severity_boundary():
    assert anomaly_service.alert_severity(2.0, 1.0) == "WARNING"  # exactly 2x is NOT critical
    assert anomaly_service.alert_severity(2.01, 1.0) == "CRITICAL"


# ----------------------------------------------------------------------------- /api/alerts
async def test_alerts_empty(client, viewer_headers):
    r = await client.get("/api/alerts", headers=viewer_headers)
    assert r.status_code == 200 and r.json() == []


async def test_alerts_newest_first_and_limit(client, viewer_headers, session_maker):
    await _seed_alerts(session_maker, 5)
    r = await client.get("/api/alerts", params={"limit": 3}, headers=viewer_headers)
    msgs = [a["message"] for a in r.json()]
    assert msgs == ["m4", "m3", "m2"]


@pytest.mark.parametrize("limit", [0, 201, -1])
async def test_alerts_limit_validation(client, viewer_headers, limit):
    assert (await client.get("/api/alerts", params={"limit": limit}, headers=viewer_headers)).status_code == 422


async def test_alert_payload_shape(client, viewer_headers, session_maker):
    await _seed_alerts(session_maker, 1)
    alert = (await client.get("/api/alerts", headers=viewer_headers)).json()[0]
    assert {
        "id",
        "created_at",
        "type",
        "message",
        "severity",
        "score",
        "acknowledged",
        "acknowledged_by",
    } <= alert.keys()
    assert alert["acknowledged"] is False


# ----------------------------------------------------------------------------- acknowledge
async def test_viewer_cannot_acknowledge(client, viewer_headers, session_maker):
    await _seed_alerts(session_maker, 1)
    assert (await client.post("/api/alerts/1/acknowledge", headers=viewer_headers)).status_code == 403


async def test_anonymous_cannot_acknowledge(client, session_maker):
    await _seed_alerts(session_maker, 1)
    assert (await client.post("/api/alerts/1/acknowledge")).status_code in UNAUTHENTICATED


async def test_operator_acknowledges_and_is_audited(client, operator_headers, session_maker):
    await _seed_alerts(session_maker, 1)
    r = await client.post("/api/alerts/1/acknowledge", headers=operator_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["acknowledged"] is True and body["acknowledged_by"] == "operator1" and body["acknowledged_at"]

    async with session_maker() as s:
        logs = (await s.execute(select(AuditLog).where(AuditLog.action == "alert_acknowledged"))).scalars().all()
    assert len(logs) == 1 and logs[0].resource_id == "1"


async def test_acknowledge_is_idempotent(client, operator_headers, session_maker):
    await _seed_alerts(session_maker, 1)
    assert (await client.post("/api/alerts/1/acknowledge", headers=operator_headers)).status_code == 200
    assert (await client.post("/api/alerts/1/acknowledge", headers=operator_headers)).status_code == 200


async def test_acknowledge_unknown_alert_404(client, operator_headers):
    assert (await client.post("/api/alerts/424242/acknowledge", headers=operator_headers)).status_code == 404


# ----------------------------------------------------------------------------- webhooks
@pytest.fixture
def webhook_file(tmp_path, monkeypatch):
    """Isolated registry file + stubbed DNS (tests must never touch the network)."""
    import src.webhook_registry as registry
    from api.services import webhook_security

    monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "webhooks.json")
    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["93.184.216.34"])
    monkeypatch.delenv("WEBHOOK_ALLOW_HTTP", raising=False)
    return registry.REGISTRY_PATH


async def test_webhook_register_list_unregister(client, operator_headers, webhook_file):
    url = "https://example.com/hook"
    r = await client.post("/api/webhooks", params={"url": url}, headers=operator_headers)
    assert r.status_code == 200 and r.json()["subscribers"] == [url]

    again = await client.post("/api/webhooks", params={"url": url}, headers=operator_headers)
    assert again.json()["subscribers"] == [url]  # idempotent, no duplicates

    r = await client.delete("/api/webhooks", params={"url": url}, headers=operator_headers)
    assert r.json()["subscribers"] == []


async def test_webhooks_are_operator_only(client, viewer_headers, webhook_file):
    url = "https://example.com/hook"
    assert (await client.post("/api/webhooks", params={"url": url}, headers=viewer_headers)).status_code == 403
    assert (await client.delete("/api/webhooks", params={"url": url}, headers=viewer_headers)).status_code == 403
    assert (await client.post("/api/webhooks", params={"url": url})).status_code in UNAUTHENTICATED


async def test_webhook_requires_url(client, operator_headers, webhook_file):
    assert (await client.post("/api/webhooks", headers=operator_headers)).status_code == 422


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata, and not https
        "https://169.254.169.254/latest/meta-data/",  # link-local
        "https://localhost:6379",
        "https://127.0.0.1/hook",
        "https://10.0.0.5/hook",
        "https://[::1]/hook",
        "https://[::ffff:127.0.0.1]/hook",  # IPv4-mapped loopback
        "file:///etc/passwd",
        "ftp://example.com/x",
        "https://user:pw@example.com/hook",
        "not a url",
    ],
)
async def test_webhook_rejects_internal_and_invalid_targets(client, operator_headers, webhook_file, bad_url):
    r = await client.post("/api/webhooks", params={"url": bad_url}, headers=operator_headers)
    assert r.status_code == 422
    assert not webhook_file.exists() or bad_url not in webhook_file.read_text()


async def test_webhook_rejects_hostname_resolving_to_private_ip(client, operator_headers, webhook_file, monkeypatch):
    from api.services import webhook_security

    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["93.184.216.34", "10.1.2.3"])
    r = await client.post("/api/webhooks", params={"url": "https://sneaky.example.com/x"}, headers=operator_headers)
    assert r.status_code == 422  # ANY private address in the answer set rejects it


async def test_webhook_http_allowed_only_when_opted_in(client, operator_headers, webhook_file, monkeypatch):
    url = "http://example.com/hook"
    assert (await client.post("/api/webhooks", params={"url": url}, headers=operator_headers)).status_code == 422
    monkeypatch.setenv("WEBHOOK_ALLOW_HTTP", "1")
    assert (await client.post("/api/webhooks", params={"url": url}, headers=operator_headers)).status_code == 200


async def test_webhook_subscriber_cap(client, operator_headers, webhook_file, monkeypatch):
    import src.webhook_registry as registry

    monkeypatch.setattr(registry, "MAX_SUBSCRIBERS", 2)
    for i in range(2):
        assert (
            await client.post("/api/webhooks", params={"url": f"https://example.com/{i}"}, headers=operator_headers)
        ).status_code == 200
    assert (
        await client.post("/api/webhooks", params={"url": "https://example.com/3"}, headers=operator_headers)
    ).status_code == 409


def test_registry_concurrent_registrations_are_lossless(webhook_file, monkeypatch):
    import threading

    import src.webhook_registry as registry

    monkeypatch.setattr(registry, "MAX_SUBSCRIBERS", 100)
    threads = [threading.Thread(target=registry.register, args=(f"https://h{i}.example.com",)) for i in range(60)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(registry.list_subscribers()) == 60


async def test_dispatch_skips_targets_that_became_internal(monkeypatch, webhook_file, caplog):
    """DNS can change after registration: dispatch re-validates and never POSTs to a private address."""
    import src.webhook_registry as registry
    from api.services import webhook_security, webhook_service

    registry.register("https://example.com/hook")
    monkeypatch.setattr(webhook_security, "_resolve_host", lambda host, port: ["127.0.0.1"])
    posted = []
    monkeypatch.setattr(webhook_service.requests, "post", lambda *a, **k: posted.append((a, k)))

    await webhook_service.dispatch_alert({"type": "thermal_spike"})
    assert posted == []
