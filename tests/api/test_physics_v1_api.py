"""T7 at the API boundary: 422 for invalid twin input, unchanged response shapes, one carbon number,
and legacy-0 still selectable end to end."""

import json
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.services import twin_service
from src.digital_twin import InvalidInputError

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "golden" / "legacy_0_goldens.json").read_text())
FLAT = np.full(24, 475.0)


@pytest.fixture(autouse=True)
def flat_carbon():
    with mock.patch("src.digital_twin.load_diurnal_carbon_intensity", return_value=(FLAT, False)):
        yield


# ------------------------------------------------------------------------- typed error -> HTTP 422
@pytest.fixture
def mini_app():
    app = FastAPI()

    @app.get("/state")
    def state(u: float, t: float = 25.0):
        return twin_service.compute_state(u, t, 0.0, "auto", live=False)

    @app.get("/whatif")
    def whatif(cw: float):
        return twin_service.compute_whatif(0.5, 25.0, 0.0, "auto", cw)

    return TestClient(app)


def test_invalid_state_input_is_a_422_with_the_field_named(mini_app):
    r = mini_app.get("/state", params={"u": 1.5})
    assert r.status_code == 422
    assert "utilisation" in r.json()["detail"]


def test_non_finite_state_input_is_a_422(mini_app):
    r = mini_app.get("/state", params={"u": 0.5, "t": "nan"})
    assert r.status_code == 422 and "outside_temp_C" in r.json()["detail"]


def test_invalid_whatif_setpoint_is_a_422(mini_app):
    r = mini_app.get("/whatif", params={"cw": 99})
    assert r.status_code == 422 and "chilled_water_temp_C" in r.json()["detail"]


def test_the_422_error_is_still_a_valueerror_for_non_http_callers():
    with pytest.raises(ValueError) as exc:
        twin_service.compute_state(1.5, 25.0, 0.0, "auto", live=False)
    assert isinstance(exc.value, InvalidInputError) and exc.value.status_code == 422


def test_unknown_mode_is_still_a_plain_valueerror():
    with pytest.raises(ValueError, match="Unknown cooling mode"):
        twin_service.compute_state(0.5, 25.0, 0.0, "turbo", live=False)


async def test_real_routes_still_reject_nan_with_422(client, viewer_headers):
    for path in ("/api/state", "/api/whatif", "/api/benchmark"):
        r = await client.get(path, params={"outside_temp": "nan"}, headers=viewer_headers)
        assert r.status_code == 422, path


# ------------------------------------------------------------------------- shapes unchanged
async def test_state_and_whatif_response_shapes_are_unchanged(client, viewer_headers):
    legacy_state_keys = set(GOLDEN["grid_states"][0]["state"]) | {"carbon_data_is_real"}
    legacy_whatif_keys = set(GOLDEN["whatif"][0]["result"])

    state = (await client.get("/api/state", headers=viewer_headers)).json()
    whatif = (await client.get("/api/whatif", headers=viewer_headers)).json()
    assert set(state) == legacy_state_keys
    assert set(whatif) == legacy_whatif_keys
    assert state["pue"] >= 1.0 and whatif["total_water_L"] >= 0


# ------------------------------------------------------------------------- one carbon number
async def test_state_and_whatif_report_the_same_carbon(client, viewer_headers):
    params = {"utilisation": 0.5, "outside_temp": 25.0, "water_stress": 0.0, "mode": "hybrid"}
    state = (await client.get("/api/state", params=params, headers=viewer_headers)).json()
    whatif = (
        await client.get("/api/whatif", params={**params, "chilled_water_temp": 12.0}, headers=viewer_headers)
    ).json()
    assert whatif["total_co2_kg"] == pytest.approx(288 * state["carbon_gco2"] / 1000.0, rel=1e-9)


# ------------------------------------------------------------------------- version selection end to end
async def test_default_is_v1_and_legacy_is_selectable_by_environment(client, viewer_headers, monkeypatch):
    params = {"utilisation": 0.5, "outside_temp": 25.0, "mode": "closed_loop"}
    monkeypatch.delenv("PHYSICS_VERSION", raising=False)
    v1 = (await client.get("/api/state", params=params, headers=viewer_headers)).json()
    monkeypatch.setenv("PHYSICS_VERSION", "legacy-0")
    legacy = (await client.get("/api/state", params=params, headers=viewer_headers)).json()
    assert v1["server_inlet_temp_C"] == pytest.approx(18.0)
    assert legacy["server_inlet_temp_C"] == pytest.approx(14.0)


async def test_water_in_the_api_respects_the_latent_heat_bound(client, viewer_headers):
    from src.digital_twin import LATENT_WATER_BOUND_L_PER_KWH

    for t in (15, 30, 45):
        s = (
            await client.get(
                "/api/state",
                params={"utilisation": 0.9, "outside_temp": t, "mode": "evaporative"},
                headers=viewer_headers,
            )
        ).json()
        heat_kwh = (s["it_power_kw"] + s["cooling_power_kw"]) * 5 / 60
        assert s["water_flow_lpm"] * 5 <= heat_kwh * LATENT_WATER_BOUND_L_PER_KWH * (1 + 1e-9)


async def test_esg_report_still_renders_under_v1(client, viewer_headers):
    r = await client.get("/api/esg_report", headers=viewer_headers)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
