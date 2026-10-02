"""T3: HTTP surface, repository idempotence, and the M2 migration."""

from __future__ import annotations

import importlib.util
import json

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import api.services.anomaly_service as svc
import api.services.telemetry_window as tw
from api.repositories import data_repository
from models.db_models import Alert
from tests.characterization import golden_support as gs

WINDOW = json.dumps([[50.0, 3.0, 30.0, 300.0, 50.0]] * 12)


# --------------------------------------------------------------------------- HTTP
async def test_status_endpoint_requires_auth(client):
    assert (await client.get("/api/anomaly/status")).status_code in (401, 403)


async def test_status_endpoint_reports_warming_up_before_any_tick(client, viewer_headers, monkeypatch):
    monkeypatch.setattr(tw, "_provider", tw.InMemoryTelemetryWindow())
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline())
    r = await client.get("/api/anomaly/status", headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "warming_up" and body["window_filled"] == 0 and body["window_size"] == 12
    assert body["detector_id"] == "lstm_autoencoder" and body["trained_on"] == "synthetic"
    assert body["episode"]["open"] is False


async def test_status_endpoint_returns_the_latest_pipeline_object(client, viewer_headers, monkeypatch):
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline())
    svc.get_pipeline()._latest = {"status": "ok", "score": 0.001, "episode": {"open": False}}
    r = await client.get("/api/anomaly/status", headers=viewer_headers)
    assert r.json()["status"] == "ok" and r.json()["score"] == 0.001


async def test_score_route_is_pure_for_real_scoring_path(client, viewer_headers, count_rows, monkeypatch):
    """No detector in this process => type 'unavailable' (never 'normal'), and still no rows."""
    monkeypatch.setattr(svc, "get_anomaly_detector", lambda: None)
    r = await client.get("/api/anomaly_score", params={"recent_data": WINDOW}, headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["type"] == "unavailable" and r.json()["alert"] is False
    assert r.headers["deprecation"] == "true"
    assert await count_rows(Alert) == 0


async def test_score_route_bad_shape_is_error_not_normal(client, viewer_headers, monkeypatch):
    class D:
        threshold = 0.01

        def detect(self, a):  # pragma: no cover - must not be reached
            raise AssertionError

    monkeypatch.setattr(svc, "get_anomaly_detector", lambda: D())
    r = await client.get("/api/anomaly_score", params={"recent_data": "[[1,2,3]]"}, headers=viewer_headers)
    assert r.json()["type"] == "error" and r.json()["alert"] is False


async def test_alert_list_exposes_identity_and_provenance(client, viewer_headers, session_maker):
    async with session_maker() as s:
        await data_repository.save_alert(
            s,
            0.05,
            True,
            "thermal_spike",
            "m",
            "CRITICAL",
            dedupe_key="lstm_autoencoder:v:7",
            model_version="v",
            origin="simulated",
        )
        await data_repository.save_alert(s, 0.05, True, "unknown", "legacy", "WARNING")
        await s.commit()
    rows = (await client.get("/api/alerts", headers=viewer_headers)).json()
    by_key = {r["dedupe_key"]: r for r in rows}
    assert (
        by_key["lstm_autoencoder:v:7"]["origin"] == "simulated"
        and by_key["lstm_autoencoder:v:7"]["model_version"] == "v"
    )
    assert by_key[None]["origin"] is None  # unlabelled legacy row


# --------------------------------------------------------------------------- repository
async def test_save_alert_with_dedupe_key_is_idempotent(session_maker, count_rows):
    async with session_maker() as s:
        a = await data_repository.save_alert(s, 0.05, True, "x", "m", "WARNING", dedupe_key="k:1")
        b = await data_repository.save_alert(s, 0.09, True, "x", "m2", "CRITICAL", dedupe_key="k:1")
        await s.commit()
    assert a.id == b.id and await count_rows(Alert) == 1


async def test_many_legacy_alerts_without_key_are_allowed(session_maker, count_rows):
    async with session_maker() as s:
        for _ in range(3):
            await data_repository.save_alert(s, 0.05, True, "x", "m", "WARNING")
        await s.commit()
    assert await count_rows(Alert) == 3


async def test_database_enforces_dedupe_key_uniqueness(session_maker):
    from sqlalchemy.exc import IntegrityError

    async with session_maker() as s:
        s.add(Alert(score=1, alert=True, type="x", message="m", dedupe_key="dup"))
        await s.commit()
    async with session_maker() as s:
        s.add(Alert(score=1, alert=True, type="x", message="m", dedupe_key="dup"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_update_alert_severity_modifies_in_place(session_maker, count_rows):
    async with session_maker() as s:
        await data_repository.save_alert(s, 0.015, True, "x", "m", "WARNING", dedupe_key="k:2")
        await data_repository.update_alert_severity(s, "k:2", "CRITICAL", 0.05, "worse")
        await s.commit()
    assert await count_rows(Alert) == 1
    async with session_maker() as s:
        a = await data_repository.get_alert_by_dedupe_key(s, "k:2")
        assert (a.severity, a.score, a.message) == ("CRITICAL", 0.05, "worse")


# --------------------------------------------------------------------------- M2 migration
MIGRATION = gs.REPO_ROOT / "alembic" / "versions" / "20261001000000_add_alert_integrity_columns.py"


def _load():
    spec = importlib.util.spec_from_file_location("m2", MIGRATION)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_m2_revision_chain():
    m = _load()
    assert m.revision == "20261001000000" and m.down_revision == "20250223000000"
    previous = gs.REPO_ROOT / "alembic" / "versions" / "20250223000000_add_security_hardening.py"
    assert previous.exists()


def test_m2_upgrade_and_downgrade_on_a_populated_pre_m2_table():
    m = _load()
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(
            sa.text("CREATE TABLE alerts (id INTEGER PRIMARY KEY, score FLOAT, alert BOOLEAN, type TEXT, message TEXT)")
        )
        for i in range(3):  # legacy rows predate the columns
            conn.execute(sa.text("INSERT INTO alerts (score, alert, type, message) VALUES (1, 1, 'x', 'legacy')"))
        with Operations.context(MigrationContext.configure(conn)):
            m.upgrade()
        cols = {c["name"] for c in sa.inspect(conn).get_columns("alerts")}
        assert {"dedupe_key", "model_version", "origin"} <= cols
        # legacy rows: NULL in all three, and several NULL dedupe_keys coexist under the unique index
        row = conn.execute(sa.text("SELECT dedupe_key, model_version, origin FROM alerts")).fetchall()
        assert row == [(None, None, None)] * 3
        conn.execute(sa.text("INSERT INTO alerts (score, alert, type, message, dedupe_key) VALUES (1,1,'x','m','k')"))
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text("INSERT INTO alerts (score, alert, type, message, dedupe_key) VALUES (1,1,'x','m','k')")
            )
    with eng.begin() as conn:
        conn.execute(sa.text("DELETE FROM alerts WHERE dedupe_key = 'k'"))
        with Operations.context(MigrationContext.configure(conn)):
            m.downgrade()
        cols = {c["name"] for c in sa.inspect(conn).get_columns("alerts")}
        assert not ({"dedupe_key", "model_version", "origin"} & cols)
        assert conn.execute(sa.text("SELECT COUNT(*) FROM alerts")).scalar() == 3  # legacy data intact
