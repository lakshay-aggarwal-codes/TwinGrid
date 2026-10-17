"""Task 30: fleet site definitions and ranking. Pure; no FastAPI, database or network."""

from __future__ import annotations

import pytest

from api.services import scenario_registry
from src.digital_twin import INLET_TEMP_MAX, INLET_TEMP_MIN, OUTLET_TEMP_MAX, DigitalTwin
from src.fleet.ranking import alert_conditions, competition_ranks, rank_fleet
from src.fleet.sites import BY_ID, LABEL, SITES


def test_ties_share_the_lowest_rank_and_the_next_rank_skips():
    assert competition_ranks([3.0, 1.0, 2.0]) == [3, 1, 2]
    assert competition_ranks([1.0, 1.0, 2.0, 2.0, 3.0]) == [1, 1, 3, 3, 5]
    assert competition_ranks([0, 0, 0]) == [1, 1, 1]
    assert competition_ranks([]) == []


def _row(i, pue, carbon, alerts):
    return {"id": i, "pue": pue, "carbon_gco2_per_step": carbon, "alert_conditions": alerts}


def test_overall_order_is_the_sum_of_ranks_and_lower_is_better():
    rows = [_row("a", 1.3, 100, 0), _row("b", 1.1, 90, 0), _row("c", 1.2, 120, 2)]
    out = rank_fleet(rows)
    assert [r["id"] for r in out] == ["b", "a", "c"]
    assert [r["overall_rank"] for r in out] == [1, 2, 3]
    assert out[0]["rank"] == {"pue": 1, "carbon_gco2_per_step": 1, "alert_conditions": 1}
    assert out[2]["rank"]["alert_conditions"] == 3


def test_equal_totals_tie_on_overall_rank_but_the_order_is_by_id():
    rows = [_row("z", 1.0, 1, 0), _row("a", 1.0, 1, 0)]
    out = rank_fleet(rows)
    assert [r["id"] for r in out] == ["a", "z"] and [r["overall_rank"] for r in out] == [1, 1]


def test_ranking_is_deterministic_and_does_not_mutate_its_input():
    rows = [_row("a", 1.3, 100, 1), _row("b", 1.1, 90, 0), _row("c", 1.2, 120, 2)]
    snapshot = [dict(r) for r in rows]
    assert rank_fleet(rows) == rank_fleet(list(reversed(rows)))
    assert rows == snapshot
    assert rank_fleet([]) == []


STATE = {"server_outlet_temp_C": 30.0, "server_inlet_temp_C": 20.0, "drought_override_active": False}
LIMITS = {"outlet_max": OUTLET_TEMP_MAX, "inlet_min": INLET_TEMP_MIN, "inlet_max": INLET_TEMP_MAX}


@pytest.mark.parametrize(
    "patch,expected",
    [
        ({}, []),
        ({"server_outlet_temp_C": OUTLET_TEMP_MAX + 0.1}, ["outlet_over_limit"]),
        ({"server_inlet_temp_C": INLET_TEMP_MAX + 0.1}, ["inlet_over_max"]),
        ({"server_inlet_temp_C": INLET_TEMP_MIN - 0.1}, ["inlet_under_min"]),
        ({"drought_override_active": True}, ["drought_override"]),
        ({"server_outlet_temp_C": OUTLET_TEMP_MAX}, []),  # exactly at the limit is not over it
    ],
)
def test_alert_conditions_are_the_documented_rule_checks(patch, expected):
    assert alert_conditions({**STATE, **patch}, **LIMITS) == expected


def test_sites_are_five_labelled_simulated_and_within_the_scenario_parameter_bounds():
    assert len(SITES) == 5 and len({s.id for s in SITES}) == 5 and set(BY_ID) == {s.id for s in SITES}
    assert "Simulated" in LABEL and "Not real facilities" in LABEL
    bounds = {p["name"]: p for p in scenario_registry.list_scenarios()["scenarios"][0]["parameters"]}
    for s in SITES:
        assert s.name.startswith("Simulated site")
        for key, value in (
            ("utilisation", s.utilisation),
            ("outside_temp", s.outside_temp_c),
            ("water_stress", s.water_stress),
        ):
            assert bounds[key]["min"] <= value <= bounds[key]["max"], (s.id, key)


def test_sites_really_differ_in_climate_and_load():
    assert len({s.outside_temp_c for s in SITES}) == 5 and len({s.utilisation for s in SITES}) == 5
    assert max(s.outside_temp_c for s in SITES) - min(s.outside_temp_c for s in SITES) >= 30


def test_the_hot_dry_site_trips_the_drought_override_and_the_others_do_not():
    flags = {}
    for s in SITES:
        twin = DigitalTwin()
        mode = twin.select_cooling_mode(s.outside_temp_c, s.water_stress)
        state = twin.step(
            {
                "utilisation": s.utilisation,
                "outside_temp_C": s.outside_temp_c,
                "water_stress": s.water_stress,
                "cooling_mode": mode,
            }
        ).to_dict()
        flags[s.id] = alert_conditions(state, **LIMITS)
    assert flags["sim-b"] == ["drought_override"]
    assert all(v == [] for k, v in flags.items() if k != "sim-b")
