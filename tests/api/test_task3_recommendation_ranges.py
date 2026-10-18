"""Task 3: the API shows and accepts chilled-water degrees C on the scale of the physics its twin runs.

Real twin (no fake): the what-if computation runs, so these also prove the recommended value is simulable.
"""

from __future__ import annotations

import pytest

from src import optimizer_proposals as rules
from src.versions import LEGACY_PHYSICS_VERSION, PHYSICS_V1, active_physics_version

CTX = {"utilisation": 0.7, "outside_temp": 24.0, "water_stress": 0.0}
SANDBOX = "/api/optimizer/sandbox"
REC = "/api/optimizer/baseline-recommendation"
PROPOSALS = "/api/optimizer/proposals"

physics_1 = pytest.mark.skipif(active_physics_version() != PHYSICS_V1, reason="needs physics 1 as the running physics")


def _sandbox(temp: float) -> dict:
    return {**CTX, "proposed_chilled_water_temp": temp, "proposed_mode": "closed_loop"}


@physics_1
async def test_recommendation_reports_celsius_inside_the_physics_1_range_with_its_physics(client, viewer_headers):
    r = await client.get(REC, params=CTX, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    sel = body["recommendation"]["selected"]
    assert sel["physics_version"] == PHYSICS_V1 and sel["actuator_range_C"] == [16.0, 25.0]
    assert 16.0 <= sel["chilled_water_temp_C"] <= 25.0
    check = body["predicted"]["setpoint_check"]
    assert check["proposed_within_actuator_range"] is True and check["physics_version"] == PHYSICS_V1


@physics_1
async def test_the_recommendation_can_be_proposed_unchanged_and_keeps_its_baseline_source(
    client, viewer_headers, operator_headers
):
    sel = (await client.get(REC, params=CTX, headers=viewer_headers)).json()["recommendation"]["selected"]
    body = {**CTX, "chilled_water_temp_c": sel["chilled_water_temp_C"], "cooling_mode": sel["cooling_mode"]}
    r = await client.post(PROPOSALS, json=body, headers=operator_headers)
    assert r.status_code == 201, r.text  # before Task 3 a 22.3 C recommendation could not be proposed (max 15 C)
    assert r.json()["source"] == f"baseline:{sel['name']}"
    assert r.json()["predicted"]["setpoint_check"]["proposed_within_actuator_range"] is True


@physics_1
async def test_sandbox_accepts_the_physics_1_range_and_flags_legacy_values(client, viewer_headers):
    inside = await client.get(SANDBOX, params=_sandbox(20.0), headers=viewer_headers)
    assert inside.status_code == 200
    assert inside.json()["predicted"]["setpoint_check"]["proposed_within_actuator_range"] is True
    legacy = await client.get(SANDBOX, params=_sandbox(12.0), headers=viewer_headers)  # accepted as before ...
    assert legacy.status_code == 200
    assert legacy.json()["predicted"]["setpoint_check"]["proposed_within_actuator_range"] is False  # ... but flagged


@physics_1
@pytest.mark.parametrize("temp", [4.9, 25.1, 99])
async def test_sandbox_rejects_values_outside_every_range(client, viewer_headers, temp):
    assert (await client.get(SANDBOX, params=_sandbox(temp), headers=viewer_headers)).status_code == 422


async def test_legacy_0_deployment_keeps_exactly_the_old_bounds(client, viewer_headers, monkeypatch):
    monkeypatch.setenv("PHYSICS_VERSION", LEGACY_PHYSICS_VERSION)
    ok = await client.get(SANDBOX, params=_sandbox(12.0), headers=viewer_headers)
    assert ok.status_code == 200
    chk = ok.json()["predicted"]["setpoint_check"]
    assert chk["physics_version"] == LEGACY_PHYSICS_VERSION and chk["actuator_range_C"] == [5.0, 15.0]
    assert chk["proposed_within_actuator_range"] is True
    for bad in (4.9, 15.1, 20.0):
        assert (await client.get(SANDBOX, params=_sandbox(bad), headers=viewer_headers)).status_code == 422


async def test_bad_proposal_bounds_follow_the_running_physics(client, operator_headers, monkeypatch):
    monkeypatch.setenv("PHYSICS_VERSION", LEGACY_PHYSICS_VERSION)
    body = {**CTX, "chilled_water_temp_c": 20.0, "cooling_mode": "hybrid"}
    assert (await client.post(PROPOSALS, json=body, headers=operator_headers)).status_code == 422


def test_the_registry_default_current_setpoint_is_outside_the_physics_1_range():
    """Documents the remaining legacy-scale value (scenario_registry, out of Task 3's scope): the reference run."""
    from api.services import scenario_registry as SR

    default = SR.WHATIF_DEFAULTS["chilled_water_temp"]
    assert rules.setpoint_check(20.0, default, PHYSICS_V1)["reference_within_actuator_range"] is False
