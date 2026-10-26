"""R3 Task 1: the what-if routes hold the chilled-water set-point to the RUNNING physics' range.

The What-if Lab takes its range from the server's actuator range (physics 1: 16..25 C). Both routes used to cap the
set-point at 5..15 C, so the lab got a 422 for any value above 15 C. They now follow the same rule as the optimizer
proposals (Task 3): the union of the registry bounds and the actuator range, read per request. legacy-0 keeps exactly
5..15 C.
"""

import pytest

from api.services import scenario_registry as SR
from src.rl.env import CHILLED_WATER_ACTION_RANGE_C
from src.versions import LEGACY_PHYSICS_VERSION, PHYSICS_V1

WHATIF = "/api/whatif"
SWEEP = "/api/whatif/sensitivity"


# ----------------------------------------------------------------------------- the range itself (no server)
def test_physics_1_accepts_the_whole_actuator_range_and_keeps_the_old_low_end():
    assert SR.accepted_chilled_water_range(PHYSICS_V1) == (5.0, 25.0)


def test_legacy_0_keeps_exactly_the_old_bounds():
    assert SR.accepted_chilled_water_range(LEGACY_PHYSICS_VERSION) == (5.0, 15.0)


def test_a_physics_the_rl_environment_cannot_run_falls_back_to_the_registry_bounds():
    assert SR.accepted_chilled_water_range("2") == SR.CHILLED_WATER_TEMP_BOUNDS


def test_the_query_schema_limit_covers_every_supported_actuator_range():
    lo, hi = SR.CHILLED_WATER_TEMP_QUERY_BOUNDS
    for version, (a, b) in CHILLED_WATER_ACTION_RANGE_C.items():
        assert lo <= a < b <= hi, version
        assert lo <= SR.accepted_chilled_water_range(version)[0] and SR.accepted_chilled_water_range(version)[1] <= hi


def test_the_error_message_names_the_range_and_the_value():
    msg = SR.chilled_water_range_error(30.0, PHYSICS_V1)
    assert msg is not None and "5" in msg and "25" in msg and "30" in msg
    assert SR.chilled_water_range_error(20.0, PHYSICS_V1) is None


# ----------------------------------------------------------------------------- the routes
@pytest.fixture
def physics_1(monkeypatch):
    monkeypatch.setenv("PHYSICS_VERSION", PHYSICS_V1)


@pytest.fixture
def legacy_0(monkeypatch):
    monkeypatch.setenv("PHYSICS_VERSION", LEGACY_PHYSICS_VERSION)


@pytest.mark.parametrize("chw", [5.0, 15.0, 16.0, 20.5, 25.0])
async def test_whatif_accepts_the_lab_range_under_physics_1(client, viewer_headers, physics_1, chw):
    r = await client.get(WHATIF, params={"chilled_water_temp": chw}, headers=viewer_headers)
    assert r.status_code == 200, r.text
    assert r.json()["inputs"]["chilled_water_temp_C"] == chw


@pytest.mark.parametrize("chw", [4.9, 25.1, 99])
async def test_whatif_still_rejects_values_outside_every_range(client, viewer_headers, physics_1, chw):
    assert (await client.get(WHATIF, params={"chilled_water_temp": chw}, headers=viewer_headers)).status_code == 422


@pytest.mark.parametrize("chw", [15.1, 20.0, 25.0])
async def test_legacy_0_whatif_keeps_exactly_the_old_bounds(client, viewer_headers, legacy_0, chw):
    r = await client.get(WHATIF, params={"chilled_water_temp": chw}, headers=viewer_headers)
    assert r.status_code == 422
    assert "5" in r.json()["detail"] and "15" in r.json()["detail"]


async def test_legacy_0_whatif_still_accepts_its_own_range(client, viewer_headers, legacy_0):
    for chw in (5.0, 12.0, 15.0):
        r = await client.get(WHATIF, params={"chilled_water_temp": chw}, headers=viewer_headers)
        assert r.status_code == 200, (chw, r.text)


async def test_a_scenario_preset_is_still_accepted_under_physics_1(client, viewer_headers, physics_1):
    """The registry's own default set-point (7 C) is below physics 1's actuator range but inside the accepted range."""
    r = await client.get(WHATIF, params={"scenario_id": "whatif-baseline"}, headers=viewer_headers)
    assert r.status_code == 200, r.text


async def test_sensitivity_accepts_a_physics_1_set_point_as_its_base(client, viewer_headers, physics_1):
    r = await client.get(SWEEP, params={"chilled_water_temp": 20.0}, headers=viewer_headers)
    assert r.status_code == 200, r.text
    chw = next(p for p in r.json()["parameters"] if p["parameter"] == "chilled_water_temp")
    assert {v["direction"] for v in chw["variants"]} == {"low", "high"}


@pytest.mark.parametrize("chw", [4.9, 25.1])
async def test_sensitivity_rejects_values_outside_the_range(client, viewer_headers, physics_1, chw):
    assert (await client.get(SWEEP, params={"chilled_water_temp": chw}, headers=viewer_headers)).status_code == 422


async def test_legacy_0_sensitivity_keeps_exactly_the_old_bounds(client, viewer_headers, legacy_0):
    assert (await client.get(SWEEP, params={"chilled_water_temp": 20.0}, headers=viewer_headers)).status_code == 422
