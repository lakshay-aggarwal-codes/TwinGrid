"""/api/state, /api/whatif, /api/simulate/{hours}, /api/benchmark."""

import pytest

from models.db_models import SensorReading, SimulationRun

STATE_KEYS = {"timestamp", "pue", "wue", "cooling_mode", "it_power_kw", "cooling_power_kw", "carbon_data_is_real"}


# ----------------------------------------------------------------------------- /api/state
async def test_state_returns_expected_shape_and_persists_one_row(client, viewer_headers, count_rows):
    r = await client.get("/api/state", params={"utilisation": 0.6, "outside_temp": 22}, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert STATE_KEYS <= body.keys()
    assert body["pue"] >= 1.0
    assert isinstance(body["timestamp"], str)  # serialised, not a pandas Timestamp
    assert await count_rows(SensorReading, SensorReading.source == "api") == 1


@pytest.mark.parametrize(
    "params",
    [{"utilisation": 1.5}, {"utilisation": -0.1}, {"outside_temp": 80}, {"water_stress": 2}],
)
async def test_state_validates_ranges(client, viewer_headers, params):
    assert (await client.get("/api/state", params=params, headers=viewer_headers)).status_code == 422


async def test_state_drought_forces_closed_loop(client, viewer_headers):
    r = await client.get("/api/state", params={"water_stress": 0.9, "outside_temp": 5}, headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["cooling_mode"] == "closed_loop"


@pytest.mark.xfail(strict=True, reason="Stage 1: /api/state silently maps unknown modes to closed_loop; should be 422")
async def test_state_rejects_unknown_mode(client, viewer_headers):
    r = await client.get("/api/state", params={"mode": "banana"}, headers=viewer_headers)
    assert r.status_code == 422


# ----------------------------------------------------------------------------- /api/whatif
async def test_whatif_shape_and_no_persistence(client, viewer_headers, count_rows):
    r = await client.get("/api/whatif", headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    for key in ("mean_pue", "wue", "total_water_L", "total_energy_kwh", "total_co2_kg", "max_outlet_temp_C", "inputs"):
        assert key in body
    assert body["hours"] == 24
    assert body["mean_pue"] >= 1.0
    assert await count_rows(SensorReading) == 0  # docstring promise: nothing persisted


async def test_whatif_is_deterministic_for_same_inputs(client, viewer_headers):
    params = {"utilisation": 0.7, "outside_temp": 30, "mode": "hybrid"}
    a = (await client.get("/api/whatif", params=params, headers=viewer_headers)).json()
    b = (await client.get("/api/whatif", params=params, headers=viewer_headers)).json()
    for key in ("mean_pue", "total_water_L", "total_energy_kwh"):
        assert a[key] == pytest.approx(b[key])


async def test_whatif_closed_loop_uses_less_water_than_evaporative(client, viewer_headers):
    base = {"utilisation": 0.65, "outside_temp": 22}
    closed = (await client.get("/api/whatif", params={**base, "mode": "closed_loop"}, headers=viewer_headers)).json()
    evap = (await client.get("/api/whatif", params={**base, "mode": "evaporative"}, headers=viewer_headers)).json()
    assert closed["total_water_L"] < evap["total_water_L"]


async def test_whatif_drought_override_flag(client, viewer_headers):
    r = await client.get("/api/whatif", params={"water_stress": 0.9, "mode": "auto"}, headers=viewer_headers)
    body = r.json()
    assert body["drought_override_active"] is True
    assert body["final_cooling_mode"] == "closed_loop"


@pytest.mark.parametrize(
    "params",
    [{"mode": "banana"}, {"chilled_water_temp": 3}, {"chilled_water_temp": 20}, {"utilisation": 2}],
)
async def test_whatif_validation(client, viewer_headers, params):
    assert (await client.get("/api/whatif", params=params, headers=viewer_headers)).status_code == 422


# ----------------------------------------------------------------------------- /api/simulate
async def test_simulate_24h_returns_hourly_rows_and_persists(client, viewer_headers, count_rows):
    r = await client.get("/api/simulate/24", params={"utilisation": 0.7}, headers=viewer_headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 24
    assert all(row["pue"] >= 1.0 for row in rows)
    assert await count_rows(SimulationRun) == 1
    assert await count_rows(SensorReading, SensorReading.source == "simulation") == 24


async def test_simulate_168h(client, viewer_headers):
    r = await client.get("/api/simulate/168", headers=viewer_headers)
    assert r.status_code == 200 and len(r.json()) == 168


@pytest.mark.parametrize("hours", [0, 169, -5])
async def test_simulate_rejects_out_of_range_hours(client, viewer_headers, hours):
    assert (await client.get(f"/api/simulate/{hours}", headers=viewer_headers)).status_code == 422


async def test_simulate_non_integer_hours_is_422(client, viewer_headers):
    assert (await client.get("/api/simulate/abc", headers=viewer_headers)).status_code == 422


async def test_simulate_does_not_disturb_live_twin(client, viewer_headers):
    from api.services import twin_service

    before = twin_service.get_twin().state.timestamp
    await client.get("/api/simulate/24", headers=viewer_headers)
    assert twin_service.get_twin().state.timestamp == before


# ----------------------------------------------------------------------------- /api/benchmark
@pytest.mark.parametrize(
    "utilisation,expected_bands",
    [
        (0.2, {"elite", "efficient", "average", "below_average"}),
        (0.9, {"elite", "efficient", "average", "below_average"}),
    ],
)
async def test_benchmark_returns_band_and_references(client, viewer_headers, utilisation, expected_bands):
    r = await client.get("/api/benchmark", params={"utilisation": utilisation}, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["band"] in expected_bands
    assert body["industry_average_2024"] == 1.56
    assert "Uptime Institute" in body["source"]
