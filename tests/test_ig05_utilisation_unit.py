"""IG-05 / UQ-1 (ADR 004): ``server_utilisation`` is a fraction of capacity in [0, 1] at the API boundary."""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")
os.environ.setdefault("ENVIRONMENT", "development")

import pytest

from api.services import twin_service


@pytest.mark.parametrize("u", [0.0, 0.25, 0.8, 1.0])
def test_state_reports_the_requested_fraction_unchanged(u):
    state = twin_service.compute_state(u, 25.0, 0.2, "auto", live=False)
    assert state["server_utilisation"] == pytest.approx(u)


@pytest.mark.parametrize("mean", [0.0, 0.5, 1.0])
def test_every_simulated_step_stays_within_zero_and_one(mean):
    steps = twin_service.compute_simulation(48, mean, 25.0, 0.3)
    values = [s["server_utilisation"] for s in steps]
    assert len(values) > 0 and all(0.0 <= v <= 1.0 for v in values)


def test_the_openapi_contract_says_fraction_and_bounds_every_request_parameter():
    from api.main import app

    spec = app.openapi()
    checked = 0
    for path in ("/api/state", "/api/benchmark", "/api/simulate/{hours}", "/api/whatif"):
        params = {p["name"]: p for p in spec["paths"][path]["get"]["parameters"]}
        schema = params["utilisation"]["schema"]
        assert schema.get("maximum") == 1 or any(s.get("maximum") == 1 for s in schema.get("anyOf", [])), path
        checked += 1
    assert checked == 4
    state_get = spec["paths"]["/api/state"]["get"]
    text = (
        state_get["description"] + next(p for p in state_get["parameters"] if p["name"] == "utilisation")["description"]
    )
    assert "fraction" in text and "not a percentage" in text


def test_the_sensor_ingestion_range_is_the_same_unit():
    from src.sensor_ingestion import RANGES

    assert RANGES["server_utilisation"] == (0.0, 1.0)
