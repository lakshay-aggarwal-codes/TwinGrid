"""R3 Task 2: ``/api/whatif`` names the physics version and the provenance of its answer.

The vocabulary is the one a run result already uses (``GET /api/runs/{id}/result`` -> ``provenance``).
"""

import pytest

from api import config
from api.services import scenario_registry as SR
from src.versions import LEGACY_PHYSICS_VERSION, PHYSICS_V1, active_physics_version

WHATIF = "/api/whatif"
PROVENANCE_KEYS = {
    "origin",
    "scenario_kind",
    "weather_source",
    "plant",
    "control",
    "model_version",
    "registry_version",
    "api_version",
}


# ----------------------------------------------------------------------------- the helper (no server)
def test_a_raw_whatif_has_no_scenario_kind_and_constant_input_weather():
    p = SR.whatif_provenance(None, "9.9.9")
    assert set(p) == PROVENANCE_KEYS
    assert p["scenario_kind"] is None
    assert (p["origin"], p["weather_source"], p["plant"], p["control"]) == (
        "simulated",
        "constant_input",
        "simulated",
        "none",
    )
    assert p["model_version"] is None
    assert (p["registry_version"], p["api_version"]) == (SR.REGISTRY_VERSION, "9.9.9")


@pytest.mark.parametrize("scenario", SR.list_scenarios()["scenarios"], ids=lambda s: s["id"])
def test_a_preset_reports_its_own_descriptor(scenario):
    p = SR.whatif_provenance(scenario["id"], "1")
    assert p["scenario_kind"] == scenario["kind"]
    assert (p["weather_source"], p["plant"], p["control"]) == (
        scenario["weather_source"],
        scenario["plant"],
        scenario["control"],
    )


# ----------------------------------------------------------------------------- the route
async def test_whatif_names_its_physics_and_provenance(client, viewer_headers):
    body = (await client.get(WHATIF, headers=viewer_headers)).json()
    assert body["physics_version"] == active_physics_version()
    assert body["provenance"] == SR.whatif_provenance(None, config.settings.APP_VERSION)
    assert body["scenario_id"] is None


async def test_a_preset_run_reports_the_presets_kind(client, viewer_headers):
    body = (await client.get(WHATIF, params={"scenario_id": "whatif-heat-wave"}, headers=viewer_headers)).json()
    assert body["provenance"]["scenario_kind"] == (SR.get_scenario("whatif-heat-wave") or {})["kind"]


@pytest.mark.parametrize("version", [LEGACY_PHYSICS_VERSION, PHYSICS_V1])
async def test_the_reported_physics_follows_the_running_physics(client, viewer_headers, monkeypatch, version):
    monkeypatch.setenv("PHYSICS_VERSION", version)
    body = (await client.get(WHATIF, headers=viewer_headers)).json()
    assert body["physics_version"] == version


async def test_the_existing_keys_are_unchanged(client, viewer_headers):
    body = (await client.get(WHATIF, headers=viewer_headers)).json()
    assert {
        "hours",
        "basis",
        "inputs",
        "mean_pue",
        "wue",
        "total_water_L",
        "total_energy_kwh",
        "total_co2_kg",
        "max_outlet_temp_C",
        "final_cooling_mode",
        "drought_override_active",
        "carbon_data_is_real",
        "scenario_id",
    } <= body.keys()
