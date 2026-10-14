"""Task 15: ``GET /api/whatif/sensitivity`` (api/plugins/whatif.py) -- auth, validation, caps, rate limit, ADR 007."""

import pytest

from api.rate_limit import limiter
from models.db_models import SensorReading, SimulationRun

URL = "/api/whatif/sensitivity"


@pytest.fixture
def limits_on(client):
    """Enable limiting (the shared `client` fixture disables it) and reset all counters."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code in (401, 403)  # same as every authenticated core route


async def test_returns_a_labelled_bounded_sweep_and_persists_nothing(client, viewer_headers, count_rows):
    r = await client.get(URL, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "model estimate on simulated data"
    assert body["runs"] <= body["max_runs"] == 12
    assert {"mean_pue", "total_energy_kwh", "total_co2_kg", "thermal_margin_C"} <= body["baseline"].keys()
    assert isinstance(body["carbon_data_is_real"], bool)
    assert body["outlet_limit_C"] > 0
    names = [p["parameter"] for p in body["parameters"]]
    assert names == ["utilisation", "outside_temp", "chilled_water_temp", "mode"]
    assert await count_rows(SensorReading) == 0  # ADR 007: a read endpoint writes nothing
    assert await count_rows(SimulationRun) == 0


async def test_same_inputs_give_the_same_answer(client, viewer_headers):
    params = {"utilisation": 0.7, "outside_temp": 30, "mode": "hybrid", "chilled_water_temp": 8}
    a = (await client.get(URL, params=params, headers=viewer_headers)).json()
    b = (await client.get(URL, params=params, headers=viewer_headers)).json()
    assert a == b


async def test_baseline_matches_the_plain_whatif_route(client, viewer_headers):
    params = {"utilisation": 0.5, "outside_temp": 18, "mode": "closed_loop"}
    sweep = (await client.get(URL, params=params, headers=viewer_headers)).json()
    plain = (await client.get("/api/whatif", params=params, headers=viewer_headers)).json()
    assert sweep["baseline"]["mean_pue"] == pytest.approx(plain["mean_pue"])
    assert sweep["baseline"]["total_energy_kwh"] == pytest.approx(plain["total_energy_kwh"])


@pytest.mark.parametrize(
    "params",
    [
        {"utilisation": 1.5},
        {"utilisation": -0.1},
        {"outside_temp": 80},
        {"water_stress": 2},
        {"chilled_water_temp": 99},
        {"mode": "banana"},
    ],
)
async def test_out_of_range_inputs_are_422(client, viewer_headers, params):
    assert (await client.get(URL, params=params, headers=viewer_headers)).status_code == 422


async def test_an_edge_input_still_respects_the_cap(client, viewer_headers):
    r = await client.get(URL, params={"utilisation": 1.0, "chilled_water_temp": 15}, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["runs"] <= 12
    util = next(p for p in body["parameters"] if p["parameter"] == "utilisation")
    assert [v["direction"] for v in util["variants"]] == ["low"]  # the high side would equal the baseline


async def test_rate_limited_with_retry_after_and_the_env_override(client, viewer_headers, limits_on, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_WHATIF_SWEEP", "2/minute")
    assert (await client.get(URL, headers=viewer_headers)).status_code == 200
    assert (await client.get(URL, headers=viewer_headers)).status_code == 200
    third = await client.get(URL, headers=viewer_headers)
    assert third.status_code == 429
    assert "retry-after" in {k.lower() for k in third.headers}
    # the core what-if route keeps its own, separate limit
    assert (await client.get("/api/whatif", headers=viewer_headers)).status_code == 200


async def test_the_default_limit_is_six_per_minute(client, viewer_headers, limits_on, monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_WHATIF_SWEEP", raising=False)
    codes = [(await client.get(URL, headers=viewer_headers)).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6
    assert codes[6] == 429
