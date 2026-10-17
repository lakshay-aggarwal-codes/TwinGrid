"""Task 27: ``GET /api/carbon/schedule`` (api/plugins/carbon_schedule.py) -- auth, validation, flat vs varying, rate limit."""

import json

import pandas as pd
import pytest

from api.rate_limit import limiter
from models.db_models import SensorReading, SimulationRun
from src import carbon_provider as CP

URL = "/api/carbon/schedule"
HEADLINE = "No carbon variation in current data"


@pytest.fixture
def limits_on(client):
    """Enable limiting (the shared `client` fixture disables it) and reset all counters."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


@pytest.fixture
def flat_fallback(tmp_path, monkeypatch):
    """No carbon file: the labelled flat assumption."""
    monkeypatch.setattr(CP, "CLEANED_CARBON_PATH", tmp_path / "missing.csv")
    CP.clear_carbon_cache()
    yield
    CP.clear_carbon_cache()


@pytest.fixture
def varying_series(tmp_path, monkeypatch):
    """A documented average series, 300 + hour gCO2/kWh, with site-local hour == UTC hour."""
    monkeypatch.setenv("SITE_TIMEZONE", "UTC")
    rows = [
        {"timestamp_utc": f"2026-01-01T{h:02d}:00:00Z", "zone": "TEST", "carbon_intensity_gco2_per_kwh": 300 + h}
        for h in range(24)
    ]
    csv = tmp_path / "carbon_intensity.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    (tmp_path / CP.CARBON_META_FILENAME).write_text(json.dumps({"semantic": "average"}))
    monkeypatch.setattr(CP, "CLEANED_CARBON_PATH", csv)
    CP.clear_carbon_cache()
    yield
    CP.clear_carbon_cache()


async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code in (401, 403)  # same as every authenticated core route


async def test_flat_fallback_says_no_variation_and_claims_no_saving(client, viewer_headers, flat_fallback, count_rows):
    r = await client.get(URL, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_variation" and body["headline"] == HEADLINE
    assert body["best"] is None and body["savings"] is None and body["baseline"] is None
    assert body["carbon"]["is_fallback"] is True
    assert body["curve_gco2_per_kwh"] == [475.0] * 24
    assert await count_rows(SensorReading) == 0  # ADR 007: a read endpoint writes nothing
    assert await count_rows(SimulationRun) == 0


async def test_varying_series_returns_the_best_window_and_a_saving(client, viewer_headers, varying_series):
    r = await client.get(URL, params={"duration_h": 4, "load_kw": 100}, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["profile"] == "data"
    assert (body["best"]["start_hour"], body["best"]["end_hour"]) == (0, 4)
    assert body["best"]["emissions_kg"] == pytest.approx(120.6)
    assert body["savings"]["emissions_kg"] == pytest.approx(4.0)
    assert body["label"].endswith("not a forecast")
    assert body["site_timezone"] == "UTC"


async def test_synthetic_profile_is_explicitly_labelled(client, viewer_headers, flat_fallback):
    r = await client.get(URL, params={"profile": "synthetic_demo", "duration_h": 3}, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "synthetic_demo"
    assert body["synthetic_label"] == "SYNTHETIC DEMONSTRATION profile, not grid data"
    assert body["headline"].startswith("Demonstration only: ")
    assert body["carbon"]["is_fallback"] is True  # the real signal is still described as what it is


async def test_same_inputs_give_the_same_answer(client, viewer_headers, varying_series):
    params = {"duration_h": 3, "load_kw": 250, "window_start": 8, "window_hours": 12, "reference_start_hour": 10}
    a = (await client.get(URL, params=params, headers=viewer_headers)).json()
    b = (await client.get(URL, params=params, headers=viewer_headers)).json()
    assert a == b and a["baseline"]["kind"] == "reference_start"


@pytest.mark.parametrize(
    "params",
    [
        {"duration_h": 0},
        {"duration_h": 25},
        {"duration_h": "soon"},
        {"load_kw": 0},
        {"load_kw": -5},
        {"load_kw": 1e9},
        {"window_start": 24},
        {"window_hours": 0},
        {"window_hours": 25},
        {"reference_start_hour": 24},
        {"profile": "banana"},
        {"duration_h": 6, "window_hours": 5},  # window shorter than the run: refused by the planner, still a 422
        {"window_start": 8, "window_hours": 12, "reference_start_hour": 17},
    ],
)
async def test_bad_inputs_are_422(client, viewer_headers, flat_fallback, params):
    assert (await client.get(URL, params=params, headers=viewer_headers)).status_code == 422


async def test_rate_limited_with_retry_after_and_env_override(
    client, viewer_headers, flat_fallback, limits_on, monkeypatch
):
    monkeypatch.setenv("RATE_LIMIT_CARBON_SCHEDULE", "2/minute")
    assert (await client.get(URL, headers=viewer_headers)).status_code == 200
    assert (await client.get(URL, headers=viewer_headers)).status_code == 200
    third = await client.get(URL, headers=viewer_headers)
    assert third.status_code == 429
    assert "retry-after" in {k.lower() for k in third.headers}


async def test_the_default_limit_is_thirty_per_minute(client, viewer_headers, flat_fallback, limits_on, monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_CARBON_SCHEDULE", raising=False)
    codes = [(await client.get(URL, headers=viewer_headers)).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429
