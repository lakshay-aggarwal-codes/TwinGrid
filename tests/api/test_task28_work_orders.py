"""Task 28: asset health and the maintenance work-order flow (api/plugins/maintenance.py), through the real app."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from models.db_models import Alert, Asset, AuditLog, Facility, Sensor, TelemetrySample, WorkOrder, WorkOrderEvent
from src.timeutil import utc_now

UNAUTH = (401, 403)
URL = "/api/maintenance/work-orders"
HEALTH = "/api/maintenance/health"


async def audit_rows(session_maker, action: str) -> list[AuditLog]:
    async with session_maker() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all())


async def orders(session_maker) -> list[WorkOrder]:
    async with session_maker() as s:
        return list((await s.execute(select(WorkOrder).order_by(WorkOrder.id))).scalars().all())


@pytest.fixture
async def admin_headers(make_user):
    _, headers = await make_user("admin1", "admin")
    return headers


@pytest.fixture
async def seeded(session_maker):
    """A facility with a sensor-bearing asset and a bare rack, an alert, and 40 rising samples on the sensor."""
    async with session_maker() as s:
        fac = Facility(name="test-site")
        s.add(fac)
        await s.flush()
        plant = Asset(facility_id=fac.id, asset_type="facility", external_id="facility-level", name="Facility level")
        rack = Asset(facility_id=fac.id, asset_type="rack", external_id="rack-1", name="rack-1")
        s.add_all([plant, rack])
        await s.flush()
        sensor = Sensor(
            asset_id=plant.id,
            measurand="it_power_kw",
            unit="kW",
            sampling_interval_s=300.0,
            external_id="fac1.it_power_kw",
            min_valid=0.0,
            max_valid=100.0,
        )
        alert = Alert(score=0.9, alert=True, type="anomaly", message="Outlet temperature high", severity="WARNING")
        s.add_all([sensor, alert])
        await s.flush()
        now = utc_now()
        batch = uuid.uuid4()
        for i in range(40):
            ts = now - timedelta(minutes=5 * (40 - i))
            s.add(
                TelemetrySample(
                    sensor_id=sensor.id,
                    stream_id="live",
                    ts_event=ts,
                    ts_ingest=ts,
                    value=10.0 + i,  # 10 -> 49: 39 % of the 0..100 range
                    quality="ok",
                    origin="simulated",
                    sim_time=ts,
                    batch_id=batch,
                )
            )
        await s.commit()
        return {"alert_id": alert.id}


# ----------------------------------------------------------------------------- authentication and reads


async def test_every_route_needs_a_token(client):
    for method, path in (
        ("get", HEALTH),
        ("get", URL),
        ("get", f"{URL}/1"),
        ("post", URL),
        ("patch", f"{URL}/1"),
        ("post", f"{URL}/1/status"),
    ):
        assert (await getattr(client, method)(path)).status_code in UNAUTH


async def test_a_viewer_reads_an_empty_list(client, viewer_headers):
    r = await client.get(URL, headers=viewer_headers)
    assert r.status_code == 200 and r.json() == []


# ----------------------------------------------------------------------------- permissions


async def test_a_viewer_cannot_write_and_the_refusal_is_audited(client, viewer_headers, session_maker):
    body = {"title": "Check pump"}
    assert (await client.post(URL, json=body, headers=viewer_headers)).status_code == 403
    assert await orders(session_maker) == []
    denied = await audit_rows(session_maker, "permission_denied")
    assert len(denied) == 1 and denied[0].details["required_role"] == "operator"
    assert denied[0].outcome == "denied"


async def test_a_viewer_cannot_edit_or_change_the_status(client, viewer_headers, operator_headers, session_maker):
    made = (await client.post(URL, json={"title": "x"}, headers=operator_headers)).json()
    assert (
        await client.patch(f"{URL}/{made['id']}", json={"priority": "high"}, headers=viewer_headers)
    ).status_code == 403
    r = await client.post(f"{URL}/{made['id']}/status", json={"status": "in_progress"}, headers=viewer_headers)
    assert r.status_code == 403
    assert (await orders(session_maker))[0].status == "open" and (await orders(session_maker))[0].priority == "medium"


async def test_operator_and_admin_may_write(client, operator_headers, admin_headers):
    assert (await client.post(URL, json={"title": "a"}, headers=operator_headers)).status_code == 201
    assert (await client.post(URL, json={"title": "b"}, headers=admin_headers)).status_code == 201


# ----------------------------------------------------------------------------- create


async def test_manual_order_is_recorded_with_history_and_an_audit_row(client, operator_headers, session_maker):
    r = await client.post(
        URL,
        json={"title": "  Replace filter  ", "description": "Noisy fan", "priority": "high", "assignee": "sam"},
        headers=operator_headers,
    )
    assert r.status_code == 201
    o = r.json()
    assert (o["title"], o["status"], o["priority"], o["assignee"]) == ("Replace filter", "open", "high", "sam")
    assert o["created_by"] == "operator1" and o["origin"] == "manual" and o["source_kind"] == "manual"
    assert o["next_statuses"] == ["in_progress", "cancelled"] and "dispatches nothing" in o["record_label"]
    async with session_maker() as s:
        events = list((await s.execute(select(WorkOrderEvent))).scalars().all())
    assert [(e.kind, e.to_status, e.actor) for e in events] == [("created", "open", "operator1")]
    audit = await audit_rows(session_maker, "work_order_created")
    assert len(audit) == 1 and audit[0].resource_id == str(o["id"]) and audit[0].details["source_kind"] == "manual"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": "   "},
        {"title": "x" * 161},
        {"title": "x", "priority": "urgent"},
        {"title": "x", "source": {"kind": "alert"}},
        {"title": "x", "source": {"kind": "health"}},
        {"title": "x", "source": {"kind": "manual", "alert_id": 3}},
        {"title": "x", "source": {"kind": "bogus"}},
        {"title": "x", "surprise": 1},
    ],
)
async def test_invalid_bodies_are_422_and_record_nothing(client, operator_headers, session_maker, body):
    assert (await client.post(URL, json=body, headers=operator_headers)).status_code == 422
    assert await orders(session_maker) == []
    assert await audit_rows(session_maker, "work_order_created") == []


async def test_order_from_an_alert_uses_it_and_is_marked_simulated(client, operator_headers, seeded, session_maker):
    body = {"source": {"kind": "alert", "alert_id": seeded["alert_id"]}, "asset_external_id": "facility-level"}
    r = await client.post(URL, json=body, headers=operator_headers)
    assert r.status_code == 201
    o = r.json()
    assert o["title"] == "Investigate: Outlet temperature high"
    assert (o["source_kind"], o["source_ref"], o["origin"]) == ("alert", str(seeded["alert_id"]), "simulated")
    assert o["asset_external_id"] == "facility-level"


async def test_an_unknown_alert_or_asset_is_404_and_records_nothing(client, operator_headers, seeded, session_maker):
    r = await client.post(URL, json={"source": {"kind": "alert", "alert_id": 9999}}, headers=operator_headers)
    assert r.status_code == 404
    r = await client.post(URL, json={"title": "x", "asset_external_id": "nope"}, headers=operator_headers)
    assert r.status_code == 404
    assert await orders(session_maker) == []


async def test_order_from_a_health_row(client, operator_headers, seeded):
    body = {"asset_external_id": "facility-level", "source": {"kind": "health", "measurand": "it_power_kw"}}
    r = await client.post(URL, json=body, headers=operator_headers)
    assert r.status_code == 201
    o = r.json()
    assert o["source_ref"] == "facility-level:it_power_kw" and o["origin"] == "simulated"
    assert o["title"] == "Check Facility level (it_power_kw): health warning"
    whole = await client.post(
        URL, json={"asset_external_id": "rack-1", "source": {"kind": "health"}}, headers=operator_headers
    )
    assert whole.status_code == 201 and whole.json()["source_ref"] == "rack-1"


async def test_a_health_order_for_a_sensor_the_asset_does_not_have_is_404(
    client, operator_headers, seeded, session_maker
):
    body = {"asset_external_id": "rack-1", "source": {"kind": "health", "measurand": "it_power_kw"}}
    assert (await client.post(URL, json=body, headers=operator_headers)).status_code == 404
    assert await orders(session_maker) == []


# ----------------------------------------------------------------------------- status flow


async def _make(client, headers, **extra):
    return (await client.post(URL, json={"title": "t", **extra}, headers=headers)).json()


async def test_the_status_flow_open_in_progress_done_with_history_and_audit(client, operator_headers, session_maker):
    o = await _make(client, operator_headers)
    r1 = await client.post(
        f"{URL}/{o['id']}/status", json={"status": "in_progress", "note": "on site"}, headers=operator_headers
    )
    assert r1.status_code == 200 and r1.json()["status"] == "in_progress"
    assert r1.json()["next_statuses"] == ["open", "done", "cancelled"]
    r2 = await client.post(f"{URL}/{o['id']}/status", json={"status": "done"}, headers=operator_headers)
    assert r2.json()["status"] == "done" and r2.json()["next_statuses"] == []
    detail = (await client.get(f"{URL}/{o['id']}", headers=operator_headers)).json()
    assert [(e["kind"], e["from_status"], e["to_status"]) for e in detail["events"]] == [
        ("created", None, "open"),
        ("status", "open", "in_progress"),
        ("status", "in_progress", "done"),
    ]
    assert detail["events"][1]["note"] == "on site"
    changes = await audit_rows(session_maker, "work_order_status_changed")
    assert [(a.details["from"], a.details["to"]) for a in changes] == [("open", "in_progress"), ("in_progress", "done")]


async def test_a_refused_move_changes_nothing_and_writes_no_audit_row(client, operator_headers, session_maker):
    o = await _make(client, operator_headers)
    r = await client.post(f"{URL}/{o['id']}/status", json={"status": "done"}, headers=operator_headers)
    assert r.status_code == 409 and r.json()["type"] == "urn:twingrid:error:not_allowed"
    assert (await orders(session_maker))[0].status == "open"
    assert await audit_rows(session_maker, "work_order_status_changed") == []


async def test_done_and_cancelled_are_final(client, operator_headers):
    done = await _make(client, operator_headers)
    for st in ("in_progress", "done"):
        await client.post(f"{URL}/{done['id']}/status", json={"status": st}, headers=operator_headers)
    r = await client.post(f"{URL}/{done['id']}/status", json={"status": "open"}, headers=operator_headers)
    assert r.status_code == 409 and r.json()["type"] == "urn:twingrid:error:final"
    cancelled = await _make(client, operator_headers)
    assert (
        await client.post(f"{URL}/{cancelled['id']}/status", json={"status": "cancelled"}, headers=operator_headers)
    ).status_code == 200
    assert (
        await client.patch(f"{URL}/{cancelled['id']}", json={"title": "x"}, headers=operator_headers)
    ).status_code == 409


async def test_unknown_order_and_bad_status_value(client, operator_headers):
    assert (
        await client.post(f"{URL}/999/status", json={"status": "in_progress"}, headers=operator_headers)
    ).status_code == 404
    assert (await client.get(f"{URL}/999", headers=operator_headers)).status_code == 404
    o = await _make(client, operator_headers)
    assert (
        await client.post(f"{URL}/{o['id']}/status", json={"status": "closed"}, headers=operator_headers)
    ).status_code == 422


# ----------------------------------------------------------------------------- update


async def test_patch_changes_only_what_is_sent_and_audits_the_fields(client, operator_headers, session_maker):
    o = await _make(client, operator_headers, assignee="sam", description="d")
    r = await client.patch(
        f"{URL}/{o['id']}", json={"priority": "low", "assignee": None, "title": " New "}, headers=operator_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["title"], body["priority"], body["assignee"], body["description"]) == ("New", "low", None, "d")
    audit = await audit_rows(session_maker, "work_order_updated")
    assert len(audit) == 1 and sorted(audit[0].details["changed"]) == ["assignee", "priority", "title"]


async def test_an_unchanged_patch_writes_no_history_and_no_audit_row(client, operator_headers, session_maker):
    o = await _make(client, operator_headers)
    r = await client.patch(f"{URL}/{o['id']}", json={"priority": "medium"}, headers=operator_headers)
    assert r.status_code == 200
    assert await audit_rows(session_maker, "work_order_updated") == []
    async with session_maker() as s:
        assert len(list((await s.execute(select(WorkOrderEvent))).scalars().all())) == 1  # just "created"


@pytest.mark.parametrize("body", [{}, {"title": "  "}, {"priority": None}, {"priority": "urgent"}, {"status": "done"}])
async def test_bad_patches_are_422(client, operator_headers, body):
    o = await _make(client, operator_headers)
    assert (await client.patch(f"{URL}/{o['id']}", json=body, headers=operator_headers)).status_code == 422


# ----------------------------------------------------------------------------- list and filters


async def test_list_filters_and_validates(client, operator_headers, viewer_headers, seeded):
    a = await _make(client, operator_headers, asset_external_id="rack-1")
    b = await _make(client, operator_headers)
    await client.post(f"{URL}/{b['id']}/status", json={"status": "in_progress"}, headers=operator_headers)
    ids = lambda r: [o["id"] for o in r.json()]  # noqa: E731
    assert ids(await client.get(URL, headers=viewer_headers)) == [b["id"], a["id"]]  # newest first
    assert ids(await client.get(URL, params={"status": "open"}, headers=viewer_headers)) == [a["id"]]
    assert ids(await client.get(URL, params={"asset": "rack-1"}, headers=viewer_headers)) == [a["id"]]
    assert ids(await client.get(URL, params={"limit": 1}, headers=viewer_headers)) == [b["id"]]
    for bad in ({"status": "closed"}, {"limit": 0}, {"limit": 201}):
        assert (await client.get(URL, params=bad, headers=viewer_headers)).status_code == 422


async def test_errors_carry_no_traceback_or_sql(client, operator_headers):
    for r in (
        await client.get(f"{URL}/999", headers=operator_headers),
        await client.post(URL, json={"title": "x", "asset_external_id": "nope"}, headers=operator_headers),
        await client.post(f"{URL}/999/status", json={"status": "done"}, headers=operator_headers),
    ):
        text = r.text.lower()
        assert "traceback" not in text and "select " not in text and ".py" not in text


# ----------------------------------------------------------------------------- health


async def test_health_reports_per_asset_status_trend_and_no_remaining_life(client, viewer_headers, seeded):
    r = await client.get(HEALTH, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["origin"] == "simulated" and "not a failure prediction" in body["label"]
    assert body["remaining_life"]["available"] is False and "C-MAPSS" in body["remaining_life"]["reason"]
    assert body["window_hours"] == 24
    by_id = {a["external_id"]: a for a in body["assets"]}
    plant, rack = by_id["facility-level"], by_id["rack-1"]
    assert plant["status"] == "warning" and plant["sensor_count"] == 1
    sensor = plant["sensors"][0]
    assert sensor["measurand"] == "it_power_kw" and sensor["valid_samples"] == 40
    assert sensor["trend"]["direction"] == "up" and sensor["trend"]["drift_pct_of_range"] == pytest.approx(
        39.0, abs=0.5
    )
    assert sensor["latest"]["value"] == 49.0 and len(sensor["series"]) > 1
    assert plant["remaining_life"]["available"] is False
    assert rack["status"] == "no_data" and "NOT MEASURED" in rack["note"] and rack["sensors"] == []
    assert body["counts"] == {"ok": 0, "watch": 0, "warning": 1, "no_data": 1}


async def test_health_window_is_validated_and_old_samples_are_ignored(client, viewer_headers, seeded):
    for bad in (0, 169, "x"):
        assert (await client.get(HEALTH, params={"hours": bad}, headers=viewer_headers)).status_code == 422
    short = await client.get(HEALTH, params={"hours": 1}, headers=viewer_headers)
    plant = next(a for a in short.json()["assets"] if a["external_id"] == "facility-level")
    assert plant["sensors"][0]["valid_samples"] < 40  # only the last hour of the 200 minutes


async def test_health_with_no_assets_is_an_empty_list_not_an_error(client, viewer_headers):
    r = await client.get(HEALTH, headers=viewer_headers)
    assert r.status_code == 200 and r.json()["assets"] == [] and r.json()["counts"]["ok"] == 0
