"""Task 10 -- scripts/sensitivity.py: the perturbation mechanism and the invariants the model actually guarantees.

Nothing here asserts a PHYSICAL direction ("more airflow lowers the outlet temperature"): the model does not promise
those relationships under every perturbation, and the study exists to MEASURE them. What is asserted:

* the parameter registry is complete and its defaults ARE the documented ones (docs/PHYSICS_V2.md: "(v1) = the v1
  numbers verbatim");
* a perturbation is restored exactly (also when the block raises) and a factor of 1.0 changes nothing;
* determinism, finite outputs, PUE >= 1, the energy identity and the envelope's violation counting;
* the per-step energy closure of physics 2 holds for perturbed parameter sets (documented "by construction");
* an invalid physics-2 perturbation is REPORTED as rejected, never clipped or hidden;
* scenarios come from the validation split only.

Tests that need the RL environment need ``gymnasium`` and are skipped without it.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import math
import sys
from pathlib import Path

import pytest

from src import digital_twin as dt
from src.physics.params import PhysicsParams

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sensitivity.py"


def _load():
    spec = importlib.util.spec_from_file_location("sensitivity_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sensitivity_script"] = module  # dataclasses with postponed annotations need the module registered
    spec.loader.exec_module(module)
    return module


S = _load()


def _need_rl():
    pytest.importorskip("gymnasium")


# ----------------------------------------------------------------------------- registry


def test_every_physics_params_field_is_accounted_for_exactly_once():
    fields = {f.name for f in dataclasses.fields(PhysicsParams)}
    registry = [p.name for p in S.registry_v1()]
    covered = registry + list(S.V1_LITERALS) + list(S.V2_ONLY)
    assert len(covered) == len(set(covered)), "a parameter is listed twice"
    assert set(covered) == fields


def test_the_documented_defaults_equal_the_code_constants_of_physics_1():
    _need_rl()
    defaults = PhysicsParams()
    for p in S.registry_v1():
        want = getattr(defaults, p.name)
        assert p.documented_value() == pytest.approx(want, rel=1e-12), p.name


def test_the_mode_tables_hold_the_documented_values():
    defaults = PhysicsParams()
    assert dt._BASE_COP[dt.CoolingMode.CLOSED_LOOP] == defaults.cop_closed_loop
    assert dt._EVAPORATIVE_HEAT_FRACTION[dt.CoolingMode.EVAPORATIVE] == defaults.evap_fraction_evaporative


# ----------------------------------------------------------------------------- perturbation mechanism


def test_perturbation_is_applied_inside_and_restored_exactly_after():
    _need_rl()
    for p in S.registry_v1():
        before = p.base()
        with S.perturbed(p, 1.25) as value:
            assert value == before * 1.25
            assert p.base() == before * 1.25
        assert p.base() == before, p.name


def test_perturbation_is_restored_when_the_block_raises():
    _need_rl()
    for p in S.registry_v1():
        before = p.base()
        with pytest.raises(RuntimeError):
            with S.perturbed(p, 0.75):
                raise RuntimeError("boom")
        assert p.base() == before, p.name


def test_the_latent_heat_perturbation_moves_the_derived_water_bound_and_restores_it():
    latent = next(p for p in S.registry_v1() if p.name == "latent_heat_j_per_kg")
    bound = dt.LATENT_WATER_BOUND_L_PER_KWH
    with S.perturbed(latent, 1.10):
        assert dt.LATENT_WATER_BOUND_L_PER_KWH == pytest.approx(bound / 1.10, rel=1e-12)
    assert dt.LATENT_WATER_BOUND_L_PER_KWH == bound


def test_constructor_defaults_are_perturbed_through_kwdefaults_and_restored():
    tau = next(p for p in S.registry_v1() if p.name == "tau_air_min")
    before = dt.DigitalTwin.__init__.__kwdefaults__["thermal_time_constant_min"]
    with S.perturbed(tau, 1.5):
        assert dt.DigitalTwin.__init__.__kwdefaults__["thermal_time_constant_min"] == before * 1.5
    assert dt.DigitalTwin.__init__.__kwdefaults__["thermal_time_constant_min"] == before


def test_a_factor_of_one_reproduces_the_unperturbed_episode_exactly_and_runs_are_deterministic():
    _need_rl()
    pe = S._load_harness()
    cfg = pe.EvalConfig(physics_version="1")
    curve, _ = pe.load_diurnal_carbon_intensity()
    scenario = S.scenarios_for(pe, cfg, 1)[0]
    policy = S.study1_policies()[0]
    first, trace_a = S.run_episode_metrics(pe, policy, scenario, cfg, curve)
    second, trace_b = S.run_episode_metrics(pe, policy, scenario, cfg, curve)
    assert first == second and trace_a == trace_b
    for p in S.registry_v1():
        with S.perturbed(p, 1.0):
            same, _ = S.run_episode_metrics(pe, policy, scenario, cfg, curve)
        assert same == first, p.name


# ----------------------------------------------------------------------------- invariants the model guarantees


def test_baseline_outputs_are_finite_and_pue_is_at_least_one():
    _need_rl()
    pe = S._load_harness()
    cfg = pe.EvalConfig(physics_version="1")
    curve, _ = pe.load_diurnal_carbon_intensity()
    for scenario in S.scenarios_for(pe, cfg, 1):
        for policy in S.study1_policies():
            m, trace = S.run_episode_metrics(pe, policy, scenario, cfg, curve)
            assert all(math.isfinite(v) for v in m.values()), (scenario.scenario_id, policy.name)
            assert m["mean_pue"] >= 1.0  # total = IT + cooling with cooling >= 0 and IT > 0
            assert 0 <= m["violation_steps"] <= len(trace)
            assert m["max_outlet_C"] >= m["mean_outlet_C"] and m["max_inlet_C"] >= m["mean_inlet_C"]
            assert all(0.0 <= u <= 1.0 for u, _, _ in trace)  # utilisation is a fraction


def test_my_accumulator_agrees_with_the_harness_energy_and_mean_pue():
    _need_rl()
    pe = S._load_harness()
    cfg = pe.EvalConfig(physics_version="1")
    curve, _ = pe.load_diurnal_carbon_intensity()
    scenario = S.scenarios_for(pe, cfg, 1)[0]
    policy = S.study1_policies()[0]
    mine, _ = S.run_episode_metrics(pe, policy, scenario, cfg, curve)
    theirs = pe.run_episode(policy, scenario, cfg, curve).metrics
    assert mine["energy_kwh"] == pytest.approx(theirs["energy_kwh"], rel=1e-12)
    assert mine["mean_pue"] == pytest.approx(theirs["mean_pue"], rel=1e-12)
    assert mine["water_L"] == pytest.approx(theirs["water_L"], rel=1e-9)
    assert mine["outlet_above_max_steps"] == theirs["outlet_violation_steps"]
    assert mine["inlet_above_max_steps"] == theirs["inlet_over_max_steps"]
    assert mine["inlet_below_min_steps"] == theirs["inlet_under_min_steps"]


def test_energy_is_power_times_time_and_violations_follow_the_envelope():
    acc = S._Acc()
    dt_h = 5.0 / 60.0
    env = dt.SAFETY_ENVELOPE
    steps = [
        (22.0, 40.0, 1.3, 600.0),  # fine
        (env.inlet_min_C - 0.1, 40.0, 1.3, 600.0),  # inlet below min
        (env.inlet_max_C + 0.1, 40.0, 1.3, 600.0),  # inlet above max
        (22.0, env.outlet_max_C + 0.1, 1.3, 600.0),  # outlet above max
        (22.0, 40.0, env.pue_max + 0.01, 600.0),  # PUE above max
        (float("nan"), 40.0, 1.3, 600.0),  # NaN counts as a violation, like the envelope itself
    ]
    for inlet, outlet, pue, kw in steps:
        acc.add(inlet, outlet, pue, kw, 1.0, dt_h)
    m = acc.metrics()
    assert m["energy_kwh"] == pytest.approx(len(steps) * 600.0 * dt_h)
    assert m["water_L"] == pytest.approx(len(steps))
    assert m["violation_steps"] == 5.0
    assert m["inlet_below_min_steps"] == 2.0  # the low inlet and the NaN
    assert m["inlet_above_max_steps"] == 1.0
    assert m["outlet_above_max_steps"] == 1.0
    assert m["pue_above_max_steps"] == 1.0


def test_physics_2_energy_closure_holds_for_every_perturbed_parameter():
    base = PhysicsParams()
    trace = [(0.2 + 0.6 * ((i % 24) / 23), 15.0 + 0.5 * (i % 30), 0.0) for i in range(72)]
    controls = dict(S.study2_controls())
    for name in S.v2_fields(base):
        default = float(getattr(base, name))
        if default == 0.0:
            continue
        for factor in S.FACTORS:
            try:
                params = dataclasses.replace(base, **{name: default * factor})
            except Exception:  # an invalid value is refused by the model itself; covered by the next test
                continue
            try:
                _, residual = S.run_twin_v2(params, controls["rule_baseline"], trace)
            except Exception as exc:  # e.g. the model's own step-size stability guard
                assert type(exc).__name__ in {"PhysicsStabilityError", "InvalidInputError"}, (name, factor, exc)
                continue
            assert math.isfinite(residual) and residual <= 1e-6, (name, factor, residual)


def test_an_invalid_physics_2_perturbation_is_reported_as_rejected_not_clipped(monkeypatch):
    monkeypatch.setattr(S, "FACTORS", (5.0,))  # idle_power_fraction 0.4 x 5 = 2.0, outside [0, 1]
    monkeypatch.setattr(S, "LEVEL_LABELS", ("x5",))
    trace = {"t": [(0.5, 20.0, 0.0)] * 6}
    study = S.study2(trace, lambda _msg: None)
    entry = study["parameters"]["idle_power_fraction"]["levels"]["x5"]
    assert "rejected" in entry and "PhysicsParamsError" in entry["rejected"]
    assert "policies" not in entry
    ok = study["parameters"]["cop_closed_loop"]["levels"]["x5"]
    assert "policies" in ok  # a valid value in the same run is still evaluated


# ----------------------------------------------------------------------------- protocol and output


def test_scenarios_are_validation_split_only_and_in_protocol_order():
    _need_rl()
    pe = S._load_harness()
    cfg = pe.EvalConfig(physics_version="1")
    chosen = S.scenarios_for(pe, cfg, 2)
    assert chosen and all(s.split == "validation" for s in chosen)
    protocol = [s for s in pe.build_scenarios(cfg)["validation"]]
    assert [s.scenario_id for s in chosen] == [s.scenario_id for s in protocol if s in chosen]
    per_family: dict[str, int] = {}
    for s in chosen:
        per_family[s.family] = per_family.get(s.family, 0) + 1
    assert set(per_family.values()) == {2}
    test_seeds = {s.seed for s in pe.build_scenarios(cfg)["test"]}
    assert not test_seeds & {s.seed for s in chosen}


def _fake_study():
    def m(pue, energy, outlet=40.0, inlet=22.0, viol=0.0):
        return {k: 0.0 for k in S.METRICS} | {
            "mean_pue": pue,
            "energy_kwh": energy,
            "max_outlet_C": outlet,
            "max_inlet_C": inlet,
            "violation_steps": viol,
        }

    base = {"p": m(1.2, 100.0)}
    levels = {
        "-25%": {"value": 3.0, "policies": {"p": m(1.26, 110.0, outlet=41.0, viol=4.0)}},
        "-10%": {"value": 3.6, "policies": {"p": m(1.2, 100.0)}},
        "+10%": {"value": 4.4, "policies": {"p": m(1.2, 100.0)}},
        "+25%": {"value": 5.0, "policies": {"p": m(1.14, 90.0, outlet=39.0)}},
    }
    inert = {k: {"value": 1.0, "policies": {"p": m(1.2, 100.0)}} for k in S.LEVEL_LABELS}
    return {
        "policies": ["p"],
        "baseline": base,
        "parameters": {
            "x": {"default": 4.0, "levels": levels},
            "inert_one": {"default": 1.0, "levels": inert},
            "zero_one": {"default": 0.0, "skipped": "default is 0"},
        },
    }


def test_deltas_tables_inert_and_new_violations_from_hand_made_numbers():
    study = _fake_study()
    assert S.delta(1.2, 1.26, "pct") == pytest.approx(5.0)
    assert S.delta(0.0, 1.0, "pct") != S.delta(0.0, 1.0, "pct")  # NaN: no percentage of zero
    assert S.delta(40.0, 41.0, "abs") == 1.0
    table = S.markdown_table(study, "p")
    row = next(line for line in table.splitlines() if line.startswith("| x |"))
    assert "+5.00 / -5.00" in row  # mean PUE
    assert "+10.00 / -10.00" in row  # energy
    assert "+1.00 / -1.00" in row  # max outlet
    assert "+4.00 / +0.00" in row  # violation steps
    assert table.index("| x |") < table.index("| inert_one |")  # the parameter that moves is listed first
    assert S.inert_parameters(study) == ["inert_one"]
    assert S.new_violations(study) == [("x", "-25%", "p", 4.0)]


def test_results_hash_and_markdown_are_stable_for_the_same_numbers():
    study = _fake_study()
    result = {
        "environment": {"python": "3", "numpy": "2", "gymnasium": "1", "platform": "x"},
        "physics1": {**study, "scenarios": ["a"], "not_perturbable": {}},
        "results_sha256": "h",
    }
    assert S.render_markdown(result) == S.render_markdown(result)
    assert S._round({"a": 1.23456789012345}) == {"a": 1.23456789}
    assert S._round({"a": float("nan")}) == {"a": "nan"}


def test_the_cli_refuses_a_non_positive_scenario_count():
    with pytest.raises(SystemExit) as exc:
        S.main(["--scenarios-per-family", "0"])
    assert exc.value.code == 2
