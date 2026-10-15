"""Task 17: the inbox, timeline and PATCH routes of api/plugins/alerts_workflow.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from models.db_models import Alert, AlertEvent, AuditLog

BASE = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
UNAUTH = (401, 403)


async def seed(session_maker, n: int = 2, severity: str = "WARNING") -> None:
    async with session_maker() as s:
        for i in range(n):
            s.add(
                Alert(
                    score=1.0 + i,
                    alert=True,
                    type="thermal_spike",
                    message=f"m{i}",
                    severity=severity,
                    origin="simulated",
                    created_at=BASE + timedelta(minutes=i),
                )
            )
        await s.commit()


async def audit(session_maker) -> list[AuditLog]:
    async with session_maker() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.action == "alert_updated"))).scalars().all())


async def events(session_maker) -> list[AlertEvent]:
    async with session_maker() as s:
        return list((await s.execute(select(AlertEvent).order_by(AlertEvent.id))).scalars().all())


# ----------------------------------------------------------------------------- permissions


async def test_endpoints_need_a_token(client, session_maker):
    await seed(session_maker, 1)
    assert (await client.get("/api/alerts/inbox")).status_code in UNAUTH
    assert (await client.get("/api/alerts/1/events")).status_code in UNAUTH
    assert (await client.patch("/api/alerts/1", json={"status": "acknowledged"})).status_code in UNAUTH


async def test_viewer_can_read_but_not_change(client, viewer_headers, session_maker):
    await seed(session_maker, 1)
    assert (await client.get("/api/alerts/inbox", headers=viewer_headers)).status_code == 200
    assert (await client.get("/api/alerts/1/events", headers=viewer_headers)).status_code == 200
    r = await client.patch("/api/alerts/1", json={"status": "acknowledged"}, headers=viewer_headers)
    assert r.status_code == 403
    assert await events(session_maker) == []
    assert await audit(session_maker) == []  # nothing was changed, so no alert_updated row
    async with session_maker() as s:
        assert (await s.get(Alert, 1)).acknowledged is False


# ----------------------------------------------------------------------------- transitions


async def test_operator_acknowledges_with_event_and_audit_row(client, operator_headers, session_maker):
    await seed(session_maker, 1)
    r = await client.patch("/api/alerts/1", json={"status": "acknowledged"}, headers=operator_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "acknowledged" and body["acknowledged"] is True and body["acknowledged_by"] == "operator1"
    (ev,) = await events(session_maker)
    assert (ev.kind, ev.from_status, ev.to_status, ev.actor) == ("status", "open", "acknowledged", "operator1")
    (row,) = await audit(session_maker)
    assert row.resource_id == "1" and row.outcome == "success" and row.details["to_status"] == "acknowledged"


async def test_full_lifecycle_and_reopen(client, operator_headers, session_maker):
    await seed(session_maker, 1)
    p = lambda **b: client.patch("/api/alerts/1", json=b, headers=operator_headers)  # noqa: E731
    assert (await p(status="acknowledged")).json()["status"] == "acknowledged"
    resolved = (await p(status="resolved")).json()
    assert resolved["status"] == "resolved" and resolved["resolved_by"] == "operator1" and resolved["resolved_at"]
    reopened = (await p(status="open")).json()
    assert reopened["status"] == "open" and reopened["acknowledged"] is False
    assert reopened["acknowledged_by"] is None and reopened["resolved_by"] is None and reopened["resolved_at"] is None
    assert len(await events(session_maker)) == 3 and len(await audit(session_maker)) == 3


async def test_open_can_be_resolved_directly(client, operator_headers, session_maker):
    await seed(session_maker, 1)
    r = await client.patch("/api/alerts/1", json={"status": "resolved"}, headers=operator_headers)
    assert r.status_code == 200 and r.json()["status"] == "resolved"


@pytest.mark.parametrize(
    "setup,target",
    [([], "open"), (["acknowledged"], "acknowledged"), (["resolved"], "acknowledged"), (["resolved"], "resolved")],
)
async def test_invalid_transitions_are_409_and_change_nothing(client, operator_headers, session_maker, setup, target):
    await seed(session_maker, 1)
    for step in setup:
        assert (await client.patch("/api/alerts/1", json={"status": step}, headers=operator_headers)).status_code == 200
    before_events, before_audit = len(await events(session_maker)), len(await audit(session_maker))
    body = {"status": target, "note": "should not be stored"}
    r = await client.patch("/api/alerts/1", json=body, headers=operator_headers)
    assert r.status_code == 409
    assert r.json()["type"] == "urn:twingrid:error:invalid_transition"
    assert (len(await events(session_maker)), len(await audit(session_maker))) == (before_events, before_audit)


async def test_unknown_alert_is_404(client, operator_headers):
    r = await client.patch("/api/alerts/424242", json={"status": "acknowledged"}, headers=operator_headers)
    assert r.status_code == 404
    assert (await client.get("/api/alerts/424242/events", headers=operator_headers)).status_code == 404


# ----------------------------------------------------------------------------- assignee and notes


async def test_assign_unassign_and_noop(client, operator_headers, make_user, session_maker):
    await seed(session_maker, 1)
    await make_user("operator2", "operator")
    p = lambda b: client.patch("/api/alerts/1", json=b, headers=operator_headers)  # noqa: E731
    assert (await p({"assignee": "operator2"})).json()["assignee"] == "operator2"
    assert len(await audit(session_maker)) == 1
    assert (await p({"assignee": "operator2"})).status_code == 200  # same value: nothing changes ...
    assert len(await events(session_maker)) == 1 and len(await audit(session_maker)) == 1  # ... nothing recorded
    assert (await p({"assignee": None})).json()["assignee"] is None
    assert [e.assignee for e in await events(session_maker)] == ["operator2", None]


async def test_assignee_must_be_an_existing_operator(client, operator_headers, make_user, session_maker):
    await seed(session_maker, 1)
    await make_user("viewer2", "viewer")
    for name in ("viewer2", "nobody-here"):
        r = await client.patch("/api/alerts/1", json={"assignee": name}, headers=operator_headers)
        assert r.status_code == 422
    assert await events(session_maker) == []


async def test_note_is_stored_but_its_text_is_not_in_the_audit_row(client, operator_headers, session_maker):
    await seed(session_maker, 1)
    r = await client.patch("/api/alerts/1", json={"note": "  checked CRAC-02  "}, headers=operator_headers)
    assert r.status_code == 200
    (ev,) = await events(session_maker)
    assert ev.kind == "note" and ev.note == "checked CRAC-02"
    (row,) = await audit(session_maker)
    assert row.details["note_added"] is True and "CRAC" not in str(row.details)


@pytest.mark.parametrize(
    "body",
    [{}, {"note": "   "}, {"status": "closed"}, {"status": "open", "colour": "red"}, {"note": "x" * 1001}],
)
async def test_bad_bodies_are_422(client, operator_headers, session_maker, body):
    await seed(session_maker, 1)
    assert (await client.patch("/api/alerts/1", json=body, headers=operator_headers)).status_code == 422


# ----------------------------------------------------------------------------- inbox and timeline


async def test_inbox_filters_and_legacy_acknowledge(client, operator_headers, viewer_headers, session_maker):
    await seed(session_maker, 3)
    assert (await client.post("/api/alerts/1/acknowledge", headers=operator_headers)).status_code == 200  # legacy path
    await client.patch("/api/alerts/2", json={"status": "resolved"}, headers=operator_headers)

    def ids(r):
        return sorted(a["id"] for a in r.json())

    allr = await client.get("/api/alerts/inbox", headers=viewer_headers)
    assert {a["id"]: a["status"] for a in allr.json()} == {1: "acknowledged", 2: "resolved", 3: "open"}
    for status, want in (("open", [3]), ("acknowledged", [1]), ("resolved", [2])):
        assert ids(await client.get("/api/alerts/inbox", params={"status": status}, headers=viewer_headers)) == want
    for bad in ({"status": "bogus"}, {"limit": 0}):
        assert (await client.get("/api/alerts/inbox", params=bad, headers=viewer_headers)).status_code == 422


async def test_inbox_severity_filter_and_order(client, viewer_headers, session_maker):
    await seed(session_maker, 2, severity="WARNING")
    await seed(session_maker, 1, severity="CRITICAL")
    crit = (await client.get("/api/alerts/inbox", params={"severity": "CRITICAL"}, headers=viewer_headers)).json()
    assert [a["severity"] for a in crit] == ["CRITICAL"]
    allrows = (await client.get("/api/alerts/inbox", headers=viewer_headers)).json()
    assert [a["created_at"] for a in allrows] == sorted((a["created_at"] for a in allrows), reverse=True)
    assert all(a["created_at"].endswith("+00:00") for a in allrows)  # UTC, explicit offset


async def test_timeline_reads_oldest_first_and_includes_legacy_ack(client, operator_headers, session_maker):
    await seed(session_maker, 1)
    await client.post("/api/alerts/1/acknowledge", headers=operator_headers)
    await client.patch("/api/alerts/1", json={"note": "on it"}, headers=operator_headers)
    await client.patch("/api/alerts/1", json={"status": "resolved"}, headers=operator_headers)
    body = (await client.get("/api/alerts/1/events", headers=operator_headers)).json()
    assert body["alert_id"] == 1
    assert [e["summary"] for e in body["entries"]] == [
        "Alert raised by the detector",
        "Acknowledged",
        "Note added",
        "Status changed from acknowledged to resolved",
    ]
    assert body["entries"][2]["note"] == "on it"


async def test_error_bodies_carry_no_internals(client, operator_headers, session_maker):
    await seed(session_maker, 1)
    r = await client.patch("/api/alerts/1", json={"status": "open"}, headers=operator_headers)
    text = r.text
    assert "Traceback" not in text and ".py" not in text and "SELECT" not in text
