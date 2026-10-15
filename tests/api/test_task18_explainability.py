"""Task 18: GET /api/models/passport and GET /api/alerts/{id}/explanation (api/plugins/explainability.py)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from api.plugins import explainability
from models.db_models import Alert, SensorReading

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
COLS = ["water_flow_lpm", "water_pressure_bar", "server_outlet_temp_C", "it_power_kw", "humidity_pct"]


@pytest.fixture
def detector_dir(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({"threshold": 0.01, "feature_columns": COLS, "percentile": 99.5}))
    arrays = {
        "data_min_": {"dtype": "float32", "values": [0.0, 2.0, 30.0, 200.0, 20.0]},
        "data_max_": {"dtype": "float32", "values": [100.0, 4.0, 50.0, 500.0, 100.0]},
    }
    (tmp_path / "scaler.json").write_text(json.dumps({"arrays": arrays}))
    monkeypatch.setattr(explainability, "detector_dir", lambda: tmp_path)
    return tmp_path


async def seed(session_maker, *, with_reading=True, score=0.03, **reading):
    async with session_maker() as s:
        rid = None
        if with_reading:
            r = SensorReading(
                source="simulation", timestamp=NOW, server_utilisation=0.5, outside_temp_C=20, server_inlet_temp_C=22,
                server_outlet_temp_C=reading.get("server_outlet_temp_C", 52.0), it_power_kw=300, cooling_power_kw=50,
                total_power_kw=350, pue=1.2, water_flow_lpm=50, water_consumed_L=1, wue=0.1, humidity_pct=60,
                water_pressure_bar=reading.get("water_pressure_bar", 3.0), cooling_mode="hybrid", anomaly=0,
            )  # fmt: skip
            s.add(r)
            await s.flush()
            rid = r.id
        s.add(
            Alert(
                score=score,
                alert=True,
                type="thermal_spike",
                message="m",
                severity="CRITICAL",
                origin="simulated",
                created_at=NOW,
                sensor_reading_id=rid,
            )
        )
        await s.commit()


async def test_both_routes_need_a_token(client):
    assert (await client.get("/api/models/passport")).status_code in (401, 403)
    assert (await client.get("/api/alerts/1/explanation")).status_code in (401, 403)


async def test_passport_for_a_viewer_matches_the_registry(client, viewer_headers, detector_dir):
    r = await client.get("/api/models/passport", headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    registry = json.loads((explainability.model_registry.REGISTRY_PATH).read_text())["artifacts"]
    assert [m["model_id"] for m in body["models"]] == [a["model_id"] for a in registry]
    assert body["metrics_label"] == "synthetic-data result"
    anomaly = next(m for m in body["models"] if m["kind"] == "anomaly")
    assert anomaly["detector"]["threshold"] == pytest.approx(0.01) and anomaly["data_origin"] == "synthetic"
    assert all(m["evaluation"] is not None for m in body["models"] if m["kind"] == "ppo")


async def test_passport_uses_the_latest_stored_decision(client, viewer_headers, detector_dir, monkeypatch):
    monkeypatch.setattr(
        explainability,
        "latest_decision",
        lambda: {"outcome": "NOT_EVALUATED", "claim_allowed": "none", "reason": "r", "evaluation_id": "e1"},
    )
    body = (await client.get("/api/models/passport", headers=viewer_headers)).json()
    ppo = [m for m in body["models"] if m["kind"] == "ppo"]
    assert ppo and all(m["evaluation"]["evaluation_id"] == "e1" for m in ppo)


async def test_passport_503_when_the_registry_is_unreadable_without_leaking_a_path(client, viewer_headers, monkeypatch):
    def boom():
        raise FileNotFoundError("/secret/place/registry.json")

    monkeypatch.setattr(explainability.model_registry, "read_registry", boom)
    r = await client.get("/api/models/passport", headers=viewer_headers)
    assert r.status_code == 503
    assert "/secret" not in r.text and "Traceback" not in r.text


async def test_explanation_numbers_for_a_linked_reading(client, viewer_headers, session_maker, detector_dir):
    await seed(session_maker, server_outlet_temp_C=55.0, score=0.03)
    r = await client.get("/api/alerts/1/explanation", headers=viewer_headers)
    assert r.status_code == 200
    b = r.json()
    assert b["method"] == "range-deviation"
    assert b["score_vs_threshold"]["ratio"] == pytest.approx(3.0)
    assert b["score_vs_threshold"]["severity_by_rule"] == "CRITICAL"
    top = b["features"][0]
    assert top["feature"] == "server_outlet_temp_C" and top["outside_range"] is True
    assert top["position"] == pytest.approx(1.25) and top["outside_range_by"] == pytest.approx(0.25)
    assert b["reading_origin"] == "simulated"
    assert any("reconstruction-error" in u for u in b["unavailable"])  # it says what it cannot show


async def test_explanation_without_a_linked_reading_says_so_and_keeps_the_score(
    client, viewer_headers, session_maker, detector_dir
):
    await seed(session_maker, with_reading=False, score=0.02)
    b = (await client.get("/api/alerts/1/explanation", headers=viewer_headers)).json()
    assert b["features"] is None
    assert b["score_vs_threshold"]["ratio"] == pytest.approx(2.0)
    assert any("not linked to a stored sensor reading" in u for u in b["unavailable"])


async def test_explanation_unknown_alert_is_404(client, viewer_headers, detector_dir):
    assert (await client.get("/api/alerts/999/explanation", headers=viewer_headers)).status_code == 404


async def test_explanation_with_an_unreadable_detector_config(
    client, viewer_headers, session_maker, tmp_path, monkeypatch
):
    monkeypatch.setattr(explainability, "detector_dir", lambda: tmp_path / "missing")
    await seed(session_maker)
    b = (await client.get("/api/alerts/1/explanation", headers=viewer_headers)).json()
    assert b["score_vs_threshold"] is None and b["features"] is None
    assert "not readable" in b["unavailable"][0]
    assert str(tmp_path) not in json.dumps(b)
