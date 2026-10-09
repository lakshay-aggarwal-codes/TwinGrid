"""BC-09 scenario registry: GET /api/scenarios and GET /api/whatif?scenario_id=."""

from __future__ import annotations

import pytest

from api.services import scenario_registry as SR
from src.digital_twin import DROUGHT_THRESHOLD
from tests.test_api_routes_smoke import client, viewer  # noqa: F401  (pytest fixtures)

DESCRIPTOR_KEYS = {
    "id",
    "label",
    "kind",
    "description",
    "weather_source",
    "plant",
    "control",
    "endpoint",
    "parameters",
}


def test_registry_is_well_formed():
    reg = SR.list_scenarios()
    ids = [s["id"] for s in reg["scenarios"]]
    assert ids and len(ids) == len(set(ids))
    for s in reg["scenarios"]:
        assert set(s) == DESCRIPTOR_KEYS
        assert s["kind"] in SR.SCENARIO_KINDS
        assert (s["plant"], s["control"]) == ("simulated", "none")
        names = [p["name"] for p in s["parameters"]]
        assert names == ["utilisation", "outside_temp", "water_stress", "mode", "chilled_water_temp"]
        for p in s["parameters"]:
            if p["type"] == "number":
                assert p["min"] <= p["default"] <= p["max"]
            else:
                assert p["default"] in p["options"]


def test_registry_payload_is_a_copy():
    reg = SR.list_scenarios()
    reg["scenarios"][0]["label"] = "mutated"
    assert SR.list_scenarios()["scenarios"][0]["label"] != "mutated"


def test_drought_preset_exceeds_twin_threshold():
    assert SR.scenario_defaults("whatif-drought")["water_stress"] > DROUGHT_THRESHOLD


async def test_scenarios_requires_auth(client):  # noqa: F811
    assert (await client.get("/api/scenarios")).status_code in (401, 403)


async def test_scenarios_listing(client, viewer):  # noqa: F811
    r = await client.get("/api/scenarios", headers=viewer)
    assert r.status_code == 200
    assert r.json() == SR.list_scenarios()


async def test_schema_bounds_match_what_the_endpoint_enforces(client, viewer):  # noqa: F811
    spec = (await client.get("/openapi.json")).json()
    params = {p["name"]: p for p in spec["paths"]["/api/whatif"]["get"]["parameters"]}
    for p in SR.list_scenarios()["scenarios"][0]["parameters"]:
        if p["type"] != "number":
            continue
        js = next(x for x in params[p["name"]]["schema"]["anyOf"] if x.get("type") == "number")
        assert (js["minimum"], js["maximum"]) == (p["min"], p["max"]), p["name"]


async def test_whatif_without_scenario_keeps_old_defaults(client, viewer):  # noqa: F811
    body = (await client.get("/api/whatif", headers=viewer)).json()
    assert body["scenario_id"] is None
    assert body["inputs"] == {
        "utilisation": 0.65,
        "outside_temp_C": 22.0,
        "water_stress": 0.0,
        "mode": "auto",
        "chilled_water_temp_C": 7.0,
    }


async def test_whatif_applies_scenario_and_echoes_id(client, viewer):  # noqa: F811
    body = (await client.get("/api/whatif", headers=viewer, params={"scenario_id": "whatif-heat-wave"})).json()
    assert body["scenario_id"] == "whatif-heat-wave"
    assert body["inputs"]["outside_temp_C"] == 38.0
    assert body["inputs"]["utilisation"] == 0.65


async def test_explicit_parameter_overrides_scenario(client, viewer):  # noqa: F811
    params = {"scenario_id": "whatif-heat-wave", "outside_temp": 30, "mode": "free_air"}
    body = (await client.get("/api/whatif", headers=viewer, params=params)).json()
    assert body["inputs"]["outside_temp_C"] == 30.0
    assert body["inputs"]["mode"] == "free_air"


async def test_scenario_matches_equivalent_raw_whatif(client, viewer):  # noqa: F811
    a = (await client.get("/api/whatif", headers=viewer, params={"scenario_id": "whatif-peak-workload"})).json()
    b = (await client.get("/api/whatif", headers=viewer, params={"utilisation": 0.95})).json()
    a.pop("scenario_id")
    b.pop("scenario_id")
    assert a == b


@pytest.mark.parametrize("sid", ["nope", "", "WHATIF-BASELINE"])
async def test_unknown_scenario_is_404_not_ignored(client, viewer, sid):  # noqa: F811
    r = await client.get("/api/whatif", headers=viewer, params={"scenario_id": sid})
    assert r.status_code == 404


async def test_out_of_range_override_still_rejected(client, viewer):  # noqa: F811
    r = await client.get("/api/whatif", headers=viewer, params={"scenario_id": "whatif-baseline", "utilisation": 2})
    assert r.status_code == 422
