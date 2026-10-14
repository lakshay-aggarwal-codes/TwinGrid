"""Task 15: the one-at-a-time what-if sweep (``src/whatif_sweep.py``) -- determinism, caps, bounds, delta arithmetic.

Pure tests use a fake ``run`` (a fixed formula) so they prove the sweep's own logic; the last tests run the real
isolated twin through ``twin_service.compute_whatif`` to prove the sweep adds nothing of its own to the numbers.
"""

from __future__ import annotations

import pytest

from src import whatif_sweep as W

BOUNDS = {
    "utilisation": (0.0, 1.0),
    "outside_temp": (-10.0, 50.0),
    "water_stress": (0.0, 1.0),
    "chilled_water_temp": (5.0, 15.0),
}
BASE = {"utilisation": 0.65, "outside_temp": 22.0, "water_stress": 0.0, "mode": "auto", "chilled_water_temp": 7.0}
LIMIT = 45.0


def fake_run(util, outside, stress, mode, chw):
    """SYNTHETIC deterministic stand-in with the what-if response's keys."""
    bump = {"auto": 0.0, "free_air": 0.1, "closed_loop": -0.1, "evaporative": 0.2, "hybrid": 0.05}[mode]
    return {
        "mean_pue": 1.2 + 0.3 * util + 0.001 * outside - 0.002 * chw + bump,
        "total_energy_kwh": 1000.0 * util + 10.0 * outside + bump,
        "total_co2_kg": 400.0 * util + 4.0 * outside,
        "max_outlet_temp_C": 30.0 + 10.0 * util + 0.1 * outside,
        "carbon_data_is_real": False,
    }


def sweep(base=BASE, run=fake_run):
    return W.run_sweep(base, run, BOUNDS, LIMIT)


def test_plan_is_fixed_order_and_within_the_cap():
    cases = W.plan_sweep(BASE, BOUNDS)
    assert [(c.parameter, c.direction) for c in cases] == [
        ("utilisation", "low"),
        ("utilisation", "high"),
        ("outside_temp", "low"),
        ("outside_temp", "high"),
        ("chilled_water_temp", "low"),
        ("chilled_water_temp", "high"),
        ("mode", "alternative"),
        ("mode", "alternative"),
        ("mode", "alternative"),
        ("mode", "alternative"),
    ]
    assert [c.value for c in cases if c.parameter == "mode"] == ["free_air", "closed_loop", "evaporative", "hybrid"]
    assert len(cases) + 1 <= W.MAX_SWEEP_RUNS


def test_run_count_never_exceeds_the_cap_for_any_base():
    calls = []

    def counting(*args):
        calls.append(args)
        return fake_run(*args)

    for util in (0.0, 0.05, 0.65, 0.95, 1.0):
        for outside in (-10.0, 22.0, 50.0):
            for chw in (5.0, 7.0, 15.0):
                for mode in W.MODES:
                    calls.clear()
                    out = W.run_sweep(
                        {**BASE, "utilisation": util, "outside_temp": outside, "chilled_water_temp": chw, "mode": mode},
                        counting,
                        BOUNDS,
                        LIMIT,
                    )
                    assert len(calls) == out["runs"] <= W.MAX_SWEEP_RUNS == out["max_runs"]


def test_sweep_is_deterministic():
    assert sweep() == sweep()
    assert list(sweep()["baseline"]) == list(W.METRICS)


def test_every_variant_stays_inside_the_allowed_range():
    for base in (
        {**BASE, "utilisation": 0.02},
        {**BASE, "utilisation": 0.98},
        {**BASE, "outside_temp": 48.0},
        {**BASE, "chilled_water_temp": 14.5},
    ):
        for case in W.plan_sweep(base, BOUNDS):
            if case.parameter == "mode":
                continue
            lo, hi = BOUNDS[case.parameter]
            assert lo <= case.value <= hi


def test_a_side_clamped_onto_the_baseline_is_not_run():
    cases = W.plan_sweep({**BASE, "utilisation": 1.0}, BOUNDS)
    assert [(c.parameter, c.direction) for c in cases if c.parameter == "utilisation"] == [("utilisation", "low")]
    cases = W.plan_sweep({**BASE, "chilled_water_temp": 5.0}, BOUNDS)
    assert [c.direction for c in cases if c.parameter == "chilled_water_temp"] == ["high"]


def test_only_one_input_changes_per_run():
    base_inputs = (0.65, 22.0, 0.0, "auto", 7.0)
    names = ("utilisation", "outside_temp", "water_stress", "mode", "chilled_water_temp")
    for case in W.plan_sweep(BASE, BOUNDS):
        changed = [n for n, a, b in zip(names, base_inputs, case.inputs) if a != b]
        assert changed == [case.parameter]


def test_deltas_are_variant_minus_baseline_and_margin_is_limit_minus_max_outlet():
    out = sweep()
    base = out["baseline"]
    assert base["thermal_margin_C"] == pytest.approx(LIMIT - base["max_outlet_temp_C"])
    for p in out["parameters"]:
        for v in p["variants"]:
            for k in W.METRICS:
                assert v["deltas"][k] == pytest.approx(v["metrics"][k] - base[k])
    util = next(p for p in out["parameters"] if p["parameter"] == "utilisation")
    high = next(v for v in util["variants"] if v["direction"] == "high")
    assert high["deltas"]["total_energy_kwh"] == pytest.approx(1000.0 * 0.10)
    assert high["deltas"]["thermal_margin_C"] == pytest.approx(-1.0)  # more load, less margin


def test_result_is_labelled_a_model_estimate_and_carries_the_carbon_flag():
    out = sweep()
    assert out["label"] == "model estimate on simulated data"
    assert out["carbon_data_is_real"] is False
    assert out["outlet_limit_C"] == LIMIT
    assert out["runs"] == 11


def test_bad_base_is_refused_before_any_run():
    calls = []

    def run(*a):
        calls.append(a)
        return fake_run(*a)

    for bad in (
        {**BASE, "utilisation": 1.5},
        {**BASE, "mode": "banana"},
        {**BASE, "outside_temp": float("nan")},
        {**BASE, "chilled_water_temp": 99},
        {**BASE, "utilisation": True},
    ):
        with pytest.raises(ValueError):
            W.run_sweep(bad, run, BOUNDS, LIMIT)
    assert calls == []


def test_the_hard_stop_trips_if_the_constants_are_ever_edited(monkeypatch):
    monkeypatch.setattr(W, "MAX_SWEEP_RUNS", 5)
    with pytest.raises(ValueError):
        W.plan_sweep(BASE, BOUNDS)


# ----------------------------------------------------------------------------- against the real isolated twin
def test_baseline_equals_the_plain_whatif_computation_and_the_sweep_is_deterministic():
    from api.services import scenario_registry as SR
    from api.services import twin_service
    from src.digital_twin import OUTLET_TEMP_MAX

    bounds = {
        "utilisation": SR.UTILISATION_BOUNDS,
        "outside_temp": SR.OUTSIDE_TEMP_BOUNDS,
        "water_stress": SR.WATER_STRESS_BOUNDS,
        "chilled_water_temp": SR.CHILLED_WATER_TEMP_BOUNDS,
    }
    first = W.run_sweep(BASE, twin_service.compute_whatif, bounds, OUTLET_TEMP_MAX)
    second = W.run_sweep(BASE, twin_service.compute_whatif, bounds, OUTLET_TEMP_MAX)
    assert first == second
    plain = twin_service.compute_whatif(0.65, 22.0, 0.0, "auto", 7.0)
    assert first["baseline"]["mean_pue"] == plain["mean_pue"]
    assert first["baseline"]["total_energy_kwh"] == plain["total_energy_kwh"]
    assert first["baseline"]["total_co2_kg"] == plain["total_co2_kg"]
    assert first["carbon_data_is_real"] == plain["carbon_data_is_real"]
    assert first["runs"] <= W.MAX_SWEEP_RUNS
