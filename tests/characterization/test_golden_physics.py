"""Golden characterization of the legacy-0 (implicit) physics, as exposed through
api/services/twin_service.py. These tests freeze CURRENT numbers -- including numbers the
forensic review considers wrong. They are not endorsements; T7 re-baselines them deliberately."""

from __future__ import annotations

from tests.characterization import golden_support as gs


def _golden(name):
    g = gs.load_golden(name)
    assert g["metadata"]["physics_version"] == gs.PHYSICS_VERSION_LABEL
    assert g["metadata"]["tolerance"]["relative"] == gs.REL_TOL
    return g["data"]


def test_compute_state_grid_matches_golden():
    expected = _golden("compute_state_grid")
    assert len(expected) == (
        len(gs.STATE_UTILISATIONS) * len(gs.STATE_OUTSIDE_TEMPS) * len(gs.STATE_WATER_STRESSES) * len(gs.STATE_MODES)
    )
    gs.assert_matches(gs.run_state_grid(), expected)


def test_compute_whatif_grid_matches_golden():
    expected = _golden("compute_whatif_grid")
    assert len(expected) == len(gs.whatif_cases())
    gs.assert_matches(gs.run_whatif_grid(), expected)


def test_compute_simulation_matches_golden():
    gs.assert_matches(gs.run_simulate_cases(), _golden("compute_simulation_cases"))


def test_live_twin_sequence_and_accumulators_match_golden():
    expected = _golden("live_twin_sequence")
    assert len(expected["steps"]) == 20
    gs.assert_matches(gs.run_live_sequence(), expected)


def test_live_twin_water_accumulator_is_monotonic_non_decreasing():
    steps = _golden("live_twin_sequence")["steps"]
    water = [s["accumulators"]["water_consumed_cumulative_L"] for s in steps]
    assert all(b >= a for a, b in zip(water, water[1:]))


def test_benchmark_pue_matches_golden():
    gs.assert_matches(gs.run_benchmark_pue(), _golden("benchmark_pue"))


def test_golden_state_grid_records_fallback_carbon():
    """Pins the provenance caveat: every grid row carries the flat 475 g/kWh fallback."""
    rows = _golden("compute_state_grid")
    assert {r["carbon_data_is_real"] for r in rows.values()} == {False}
    assert {r["carbon_intensity_gco2_per_kwh"] for r in rows.values()} == {475.0}


def test_shared_live_twin_is_not_touched_by_non_live_state_calls():
    """compute_state(live=False) must not advance the shared twin (relied on by /api/benchmark, ESG)."""
    import api.services.twin_service as ts

    with gs.frozen_environment(), gs.fresh_shared_twin():
        twin = ts.get_twin()
        t0, w0 = twin._time, twin._water_consumed_cumulative_L
        ts.compute_state(0.9, 35.0, 0.2, "evaporative", live=False)
        ts.compute_whatif(0.9, 35.0, 0.2, "evaporative", 7.0)
        ts.compute_simulation(1, 0.7, 25.0, 0.3)
        assert (twin._time, twin._water_consumed_cumulative_L) == (t0, w0)
