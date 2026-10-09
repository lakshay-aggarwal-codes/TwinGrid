"""T30: pre-registration, perturbation manifest, bootstrap CI, robustness criteria, decision, reports, registry promotion.

Everything here is a unit test on synthetic per-scenario rows or on temp files; no PPO policy is trained or loaded and
no real evaluation is run. Tests that need the Gymnasium environment (perturbing the plant through DataCentreEnv) are
skipped when gymnasium is not installed; the CI `test` job installs it.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ep = _load("eval_policies")
rc = _load("registry_cli")

POLICIES = ep.POLICIES
IDS = [f"s{i}" for i in range(12)]


# ----------------------------------------------------------------------------- synthetic rows
def _rows(mean: float, *, spread: float = 1.0, env: int = 0, seed: int = 0, ids=IDS) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for i, sid in enumerate(ids):
        out.append(
            {
                "scenario_id": sid,
                "exogenous_hash": f"h{i}",
                "total_reward": float(mean + spread * rng.normal()),
                "energy_kwh": 1000.0,
                "water_L": 500.0,
                "carbon_gco2": 1e6,
                "mean_pue": 1.3,
                "mean_wue": 0.9,
                "outlet_violation_steps": float(env if i == 0 else 0),
                "inlet_over_max_steps": 0.0,
                "inlet_under_min_steps": 0.0,
            }
        )
    return out


def _policies(rule: float, const: float, cand: float, *, cand_env: int = 0, seed: int = 0) -> dict:
    return {
        "rule": _rows(rule, seed=seed + 1),
        "best_constant": _rows(const, seed=seed + 2),
        "candidate": _rows(cand, seed=seed + 3, env=cand_env),
    }


@pytest.fixture(scope="module")
def prereg():
    return json.loads((ROOT / "configs" / "prereg" / "prereg_v2.json").read_text(encoding="utf-8"))


def _perts(prereg, **overrides):
    """Two evaluated perturbations (one single, one joint), each with its own policies."""
    base = {
        "single_a": {"status": "evaluated", "kind": "single", "policies": _policies(-110.0, -108.0, -100.0, seed=10)},
        "joint_b": {"status": "evaluated", "kind": "joint", "policies": _policies(-115.0, -112.0, -104.0, seed=20)},
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------------- bootstrap CI
def test_bootstrap_ci_is_deterministic_for_a_seed_and_differs_across_seeds():
    a, b = np.arange(20.0), np.arange(20.0) * 0.5
    one = ep.bootstrap_paired_ci(a, b, n_resamples=2000, seed=7)
    two = ep.bootstrap_paired_ci(a, b, n_resamples=2000, seed=7)
    other = ep.bootstrap_paired_ci(a, b, n_resamples=2000, seed=8)
    assert one == two
    assert (one["ci_low"], one["ci_high"]) != (other["ci_low"], other["ci_high"])
    assert one["mean"] == pytest.approx(4.75)


def test_bootstrap_ci_brackets_the_mean_and_is_exact_for_constant_differences():
    rng = np.random.default_rng(0)
    base = rng.normal(size=40)
    ci = ep.bootstrap_paired_ci(base + 2.0, base, n_resamples=2000, seed=1)
    assert ci["ci_low"] == pytest.approx(2.0) and ci["ci_high"] == pytest.approx(2.0)
    noisy = ep.bootstrap_paired_ci(rng.normal(size=40) + 0.5, rng.normal(size=40), n_resamples=2000, seed=1)
    assert noisy["ci_low"] < noisy["mean"] < noisy["ci_high"]


def test_bootstrap_ci_excludes_zero_for_a_clear_effect_and_includes_it_for_none():
    rng = np.random.default_rng(3)
    x = rng.normal(size=60)
    clear = ep.bootstrap_paired_ci(x + 1.5 + 0.1 * rng.normal(size=60), x, n_resamples=4000, seed=0)
    none = ep.bootstrap_paired_ci(x + 0.1 * rng.normal(size=60), x, n_resamples=4000, seed=0)
    assert clear["ci_low"] > 0
    assert none["ci_low"] < 0 < none["ci_high"]


def test_bootstrap_ci_width_shrinks_with_more_scenarios():
    rng = np.random.default_rng(5)
    widths = []
    for n in (10, 100, 1000):
        d = rng.normal(size=n)
        ci = ep.bootstrap_paired_ci(d, np.zeros(n), n_resamples=2000, seed=0)
        widths.append(ci["ci_high"] - ci["ci_low"])
    assert widths[0] > widths[1] > widths[2]


def test_bootstrap_ci_coverage_is_roughly_nominal():
    rng = np.random.default_rng(11)
    hits, trials = 0, 150
    for t in range(trials):
        d = rng.normal(loc=1.0, scale=2.0, size=30)
        ci = ep.bootstrap_paired_ci(d, np.zeros(30), n_resamples=1000, seed=t)
        hits += ci["ci_low"] <= 1.0 <= ci["ci_high"]
    assert 0.88 <= hits / trials <= 0.99  # nominal 0.95; the percentile bootstrap undercovers slightly at n=30


def test_bootstrap_ci_uses_no_global_rng_and_validates_input():
    np.random.seed(123)
    before = np.random.get_state()[1].copy()
    ep.bootstrap_paired_ci([1.0, 2.0, 3.0], [0.0, 0.0, 0.0], n_resamples=500, seed=0)
    assert np.array_equal(np.random.get_state()[1], before)
    with pytest.raises(ValueError, match="at least 2"):
        ep.bootstrap_paired_ci([1.0], [0.0])
    with pytest.raises(ValueError, match="equal length"):
        ep.bootstrap_paired_ci([1.0, 2.0], [1.0])
    with pytest.raises(ValueError, match="confidence"):
        ep.bootstrap_paired_ci([1.0, 2.0], [0.0, 0.0], confidence=1.5)
    with pytest.raises(ValueError, match="n_resamples"):
        ep.bootstrap_paired_ci([1.0, 2.0], [0.0, 0.0], n_resamples=10)


# ----------------------------------------------------------------------------- perturbation manifest
def test_shipped_manifest_is_valid_and_every_entry_is_a_stress_test():
    doc = json.loads((ROOT / "configs" / "robustness" / "perturbations_v2.json").read_text(encoding="utf-8"))
    ep.validate_perturbation_manifest(doc)
    assert {e["basis"] for e in doc["perturbations"]} == {ep.BASIS_STRESS}
    for e in doc["perturbations"]:
        assert set(e) == {"id", "parameter", "mode", "value", "applies_to", "basis"}
    assert len(ep.expand_perturbations(doc)) == len(doc["perturbations"]) + len(doc["joint_sets"])


def test_manifest_covers_the_listed_physics_parameters():
    doc = json.loads((ROOT / "configs" / "robustness" / "perturbations_v2.json").read_text(encoding="utf-8"))
    params = {e["parameter"].split(".")[0] for e in doc["perturbations"]}
    assert params == {
        "cop_base", "capacity_margin", "idle_fraction", "tau_air", "C_th", "actuator_rate", "actuator_lag",
        "humidity_coefficient", "evaporative_water_coefficient",
    }  # fmt: skip


@pytest.mark.parametrize(
    "basis", ["", "guess", "stress-test", "empirical:", "stress-test:no empirical basis ", None, 7]
)
def test_bad_basis_is_rejected(basis):
    doc = {"perturbations": [_entry(basis=basis)]}
    with pytest.raises(ep.EvalProtocolError, match="basis"):
        ep.validate_perturbation_manifest(doc)


def _entry(**kw):
    e = {"id": "p1", "parameter": "tau_air", "mode": "multiplicative", "value": 1.2, "applies_to": ["all"],
         "basis": ep.BASIS_STRESS}  # fmt: skip
    e.update(kw)
    return e


def test_empirical_basis_with_a_source_is_accepted():
    ep.validate_perturbation_manifest({"perturbations": [_entry(basis="empirical:vendor datasheet 2025-03")]})


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"mode": "scale"}, "mode"),
        ({"value": 0}, "> 0"),
        ({"value": "x"}, "finite number"),
        ({"value": float("inf")}, "finite"),
        ({"applies_to": []}, "applies_to"),
    ],
)
def test_bad_entries_are_rejected(change, match):
    with pytest.raises(ep.EvalProtocolError, match=match):
        ep.validate_perturbation_manifest({"perturbations": [_entry(**change)]})


def test_missing_field_duplicate_id_and_bad_joint_sets_are_rejected():
    broken = _entry()
    del broken["value"]
    with pytest.raises(ep.EvalProtocolError, match="lacks"):
        ep.validate_perturbation_manifest({"perturbations": [broken]})
    with pytest.raises(ep.EvalProtocolError, match="duplicate"):
        ep.validate_perturbation_manifest({"perturbations": [_entry(), _entry()]})
    with pytest.raises(ep.EvalProtocolError, match="known members"):
        ep.validate_perturbation_manifest(
            {
                "perturbations": [_entry()],
                "joint_sets": [{"id": "j", "members": ["p1", "nope"], "basis": ep.BASIS_STRESS}],
            }
        )
    with pytest.raises(ep.EvalProtocolError, match="collides"):
        ep.validate_perturbation_manifest(
            {
                "perturbations": [_entry()],
                "joint_sets": [{"id": "p1", "members": ["p1", "p1"], "basis": ep.BASIS_STRESS}],
            }
        )


def test_parameters_without_a_counterpart_in_the_current_physics_are_not_applicable():
    assert ep.not_applicable_reason([_entry(parameter="C_th")]).startswith("no counterpart")
    assert "actuator_lag" in ep.not_applicable_reason([_entry(parameter="actuator_lag")])
    assert ep.not_applicable_reason([_entry(parameter="cop_base.nonsense")]) is not None
    assert ep.not_applicable_reason([_entry(parameter="cop_base.hybrid"), _entry(parameter="tau_air")]) is None


def test_perturbed_refuses_a_parameter_with_no_counterpart():
    with pytest.raises(ep.EvalProtocolError):
        with ep.perturbed([_entry(parameter="C_th")]):
            pass


# ----------------------------------------------------------------------------- applying and restoring perturbations
def test_perturbation_changes_the_plant_and_is_restored_exactly():
    from src import digital_twin as dt

    before_cop, before_margin = dict(dt._BASE_COP), dt.COOLING_CAPACITY_MARGIN
    before_hum, before_evap = dt.WATER_HUMIDITY_FACTOR_PER_PCT, dict(dt._EVAPORATIVE_HEAT_FRACTION)
    twin = dt.DigitalTwin()
    base = twin.compute_cooling_power(300.0, dt.CoolingMode.CLOSED_LOOP, 25.0)
    entries = [
        _entry(id="a", parameter="cop_base.closed_loop", value=0.8),
        _entry(id="b", parameter="capacity_margin", value=0.8),
        _entry(id="c", parameter="humidity_coefficient", value=1.2),
        _entry(id="d", parameter="evaporative_water_coefficient", value=1.2),
    ]
    with ep.perturbed(entries):
        assert dt._BASE_COP[dt.CoolingMode.CLOSED_LOOP] == pytest.approx(before_cop[dt.CoolingMode.CLOSED_LOOP] * 0.8)
        assert dt.COOLING_CAPACITY_MARGIN == pytest.approx(before_margin * 0.8)
        assert dt.WATER_HUMIDITY_FACTOR_PER_PCT == pytest.approx(before_hum * 1.2)
        assert dt.DigitalTwin().compute_cooling_power(300.0, dt.CoolingMode.CLOSED_LOOP, 25.0) > base  # lower COP
    assert dict(dt._BASE_COP) == before_cop and dt.COOLING_CAPACITY_MARGIN == before_margin
    assert dt.WATER_HUMIDITY_FACTOR_PER_PCT == before_hum and dict(dt._EVAPORATIVE_HEAT_FRACTION) == before_evap
    assert twin.compute_cooling_power(300.0, dt.CoolingMode.CLOSED_LOOP, 25.0) == base


def test_perturbation_is_restored_when_the_block_raises():
    from src import digital_twin as dt

    before = dict(dt._BASE_COP)
    with pytest.raises(RuntimeError):
        with ep.perturbed([_entry(parameter="cop_base.hybrid", value=1.2)]):
            assert dt._BASE_COP != before
            raise RuntimeError("boom")
    assert dict(dt._BASE_COP) == before


def test_additive_and_set_modes():
    from src import digital_twin as dt

    before = dt.COOLING_CAPACITY_MARGIN
    with ep.perturbed([_entry(parameter="capacity_margin", mode="additive", value=-0.1)]):
        assert dt.COOLING_CAPACITY_MARGIN == pytest.approx(before - 0.1)
    with ep.perturbed([_entry(parameter="capacity_margin", mode="set", value=1.0)]):
        assert dt.COOLING_CAPACITY_MARGIN == 1.0
    assert dt.COOLING_CAPACITY_MARGIN == before


def test_plant_dynamics_perturbations_reach_the_environment_twin_and_are_restored():
    pytest.importorskip("gymnasium")
    from src.rl import env as opt  # DataCentreEnv lives here and reads its own module globals

    original = opt.DigitalTwin
    idle = opt.IDLE_FRAC
    with ep.perturbed(
        [_entry(id="t", parameter="tau_air", value=1.2), _entry(id="i", parameter="idle_fraction", value=1.2)]
    ):
        env = opt.DataCentreEnv(seed=1)
        env.reset(seed=1)  # the environment builds its twin on reset
        assert env._twin._thermal_time_constant_min == pytest.approx(12.0)  # 10.0 x 1.2
        assert opt.IDLE_FRAC == pytest.approx(idle * 1.2)
    env2 = opt.DataCentreEnv(seed=1)
    env2.reset(seed=1)
    assert env2._twin._thermal_time_constant_min == pytest.approx(10.0)  # restored
    assert opt.DigitalTwin is original and opt.IDLE_FRAC == idle


# ----------------------------------------------------------------------------- pre-registration
def _prereg_copy(tmp_path):
    files = {}
    for name, src in (
        ("prereg", ROOT / "configs" / "prereg" / "prereg_v2.json"),
        ("lock", ROOT / "configs" / "prereg" / "prereg_v2.lock.json"),
        ("pert", ROOT / "configs" / "robustness" / "perturbations_v2.json"),
    ):
        dst = tmp_path / src.name
        dst.write_bytes(src.read_bytes())
        files[name] = dst
    return files


def test_shipped_preregistration_verifies():
    doc = ep.verify_prereg()
    assert doc["preregistration_sha256"] == ep.prereg_hash(doc) and len(doc["preregistration_sha256"]) == 64
    assert doc["perturbation_manifest"]["n_single"] == 24 and doc["perturbation_manifest"]["n_joint"] == 2


def test_prereg_pins_the_frozen_t8_rules_and_the_never_before_run_criteria(prereg):
    assert prereg["eval_config"]["test_seed_start"] == 200_000 and prereg["eval_config"]["training_seeds"] == [
        0,
        1,
        2,
        3,
        4,
    ]
    assert set(prereg["robustness_criteria"]) == {
        "R1_envelope",
        "R2_noninferiority",
        "R3_degradation",
        "R4_completeness",
    }
    assert prereg["promotion"]["result_if_none_qualifies"] == "no promotable policy"
    assert set(prereg["outcome_rules"]) == {"A", "B", "C"}


def test_a_changed_threshold_breaks_the_hash(tmp_path, prereg):
    f = _prereg_copy(tmp_path)
    doc = copy.deepcopy(prereg)
    doc["robustness_criteria"]["R2_noninferiority"]["margin_rel"] = 0.5
    f["prereg"].write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ep.EvalProtocolError, match="hash mismatch"):
        ep.verify_prereg(f["prereg"], f["lock"], f["pert"])


def test_a_rehashed_prereg_still_fails_against_its_lock(tmp_path, prereg):
    f = _prereg_copy(tmp_path)
    doc = copy.deepcopy(prereg)
    doc["robustness_criteria"]["R2_noninferiority"]["margin_rel"] = 0.5
    doc["preregistration_sha256"] = ep.prereg_hash(doc)
    f["prereg"].write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ep.EvalProtocolError, match="differs from its lock"):
        ep.verify_prereg(f["prereg"], f["lock"], f["pert"])


def test_a_changed_perturbation_manifest_is_detected(tmp_path):
    f = _prereg_copy(tmp_path)
    doc = json.loads(f["pert"].read_text(encoding="utf-8"))
    doc["perturbations"][0]["value"] = 0.5
    f["pert"].write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ep.EvalProtocolError, match="perturbation manifest changed"):
        ep.verify_prereg(f["prereg"], f["lock"], f["pert"])


def test_a_missing_preregistration_stops_the_run(tmp_path):
    f = _prereg_copy(tmp_path)
    f["lock"].unlink()
    with pytest.raises(ep.EvalProtocolError, match="missing"):
        ep.verify_prereg(f["prereg"], f["lock"], f["pert"])


def test_prereg_hash_ignores_only_its_own_field(prereg):
    doc = copy.deepcopy(prereg)
    h = ep.prereg_hash(doc)
    doc["preregistration_sha256"] = "x"
    assert ep.prereg_hash(doc) == h
    doc["bootstrap"]["seed"] += 1
    assert ep.prereg_hash(doc) != h


def test_reregistering_is_refused_while_the_lock_exists():
    with pytest.raises(ep.EvalProtocolError, match="locked"):
        ep.write_prereg(force=False)


def test_runs_that_used_a_hash_are_found(tmp_path):
    run = tmp_path / "eval-1"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"prereg_sha256": "abc"}), encoding="utf-8")
    assert ep._runs_using("abc", tmp_path) == ["eval-1"] and ep._runs_using("zzz", tmp_path) == []


# ----------------------------------------------------------------------------- protocol guards
def test_training_overlap_is_a_stop_condition():
    ok = dict(training_seeds=[0, 1, 2, 3, 4], reserved_training_range=(0, 99_999))
    ep.assert_no_training_overlap([200_000, 200_001], **ok, test_range=(200_000, 299_999))
    with pytest.raises(ep.EvalProtocolError, match="reserved training range"):
        ep.assert_no_training_overlap([200_000, 42], **ok)
    with pytest.raises(ep.EvalProtocolError, match="training"):
        ep.assert_no_training_overlap([100_500], training_scenario_seeds=[100_500], **ok)
    with pytest.raises(ep.EvalProtocolError, match="outside the test range"):
        ep.assert_no_training_overlap([150_000], **ok, test_range=(200_000, 299_999))


def test_the_shipped_scenario_set_never_touches_training_ids(prereg):
    from src import policy_evaluation as pe

    cfg = pe.EvalConfig.from_json(prereg["eval_config"])
    scenarios = pe.build_scenarios(cfg)
    ep.assert_no_training_overlap(
        [s.seed for s in scenarios["validation"] + scenarios["test"]],
        training_seeds=cfg.training_seeds,
        reserved_training_range=tuple(cfg.training_seed_reserved),
    )
    split = json.loads((ROOT / "configs" / "splits" / "split_v2.json").read_text(encoding="utf-8"))[
        "scenario_seed_ranges"
    ]
    ep.assert_no_training_overlap(
        [s.seed for s in scenarios["test"]],
        training_seeds=cfg.training_seeds,
        reserved_training_range=tuple(cfg.training_seed_reserved),
        test_range=tuple(split["test"]),
    )


# ----------------------------------------------------------------------------- robustness criteria
def test_a_candidate_that_dominates_passes_every_robustness_criterion(prereg):
    unp = _policies(-110.0, -108.0, -100.0)
    res = ep.evaluate_robustness(unp, _perts(prereg), prereg)
    assert res["all_passed"] and [c["passed"] for c in res["criteria"]] == [True] * 4
    assert res["evaluated"] == ["joint_b", "single_a"] and res["not_applicable"] == []
    assert res["worst_case"]["id"] in ("single_a", "joint_b")
    for pid in res["evaluated"]:
        assert res["per_perturbation"][pid]["checks"] == {"R1": True, "R2": True, "R3": True}


def test_an_envelope_violation_under_perturbation_fails_r1(prereg):
    perts = _perts(prereg)
    perts["single_a"]["policies"] = _policies(-110.0, -108.0, -100.0, cand_env=3, seed=10)
    res = ep.evaluate_robustness(_policies(-110.0, -108.0, -100.0), perts, prereg)
    assert not res["all_passed"]
    assert next(c for c in res["criteria"] if c["id"] == "R1_envelope")["failed_on"] == ["single_a"]


def test_a_candidate_clearly_worse_than_a_baseline_fails_r2_and_r3(prereg):
    perts = _perts(prereg)
    perts["joint_b"]["policies"] = _policies(-115.0, -112.0, -140.0, seed=20)
    res = ep.evaluate_robustness(_policies(-110.0, -108.0, -100.0), perts, prereg)
    by_id = {c["id"]: c for c in res["criteria"]}
    assert (
        not by_id["R2_noninferiority"]["passed"]
        and "joint_b vs best_constant" in by_id["R2_noninferiority"]["failed_on"]
    )
    assert not by_id["R3_degradation"]["passed"]
    assert res["worst_case"]["id"] == "joint_b"


def test_not_applicable_perturbations_are_recorded_and_cannot_decide_anything(prereg):
    perts = _perts(prereg, c_th_p20={"status": "not_applicable", "kind": "single", "reason": "no counterpart"})
    res = ep.evaluate_robustness(_policies(-110.0, -108.0, -100.0), perts, prereg)
    assert res["not_applicable"] == ["c_th_p20"] and res["all_passed"]
    assert res["per_perturbation"]["c_th_p20"] == {"status": "not_applicable", "reason": "no counterpart"}


def test_without_a_joint_perturbation_completeness_fails(prereg):
    perts = {"single_a": _perts(prereg)["single_a"]}
    res = ep.evaluate_robustness(_policies(-110.0, -108.0, -100.0), perts, prereg)
    r4 = next(c for c in res["criteria"] if c["id"] == "R4_completeness")
    assert not r4["passed"] and not res["all_passed"]


def test_a_changed_scenario_set_is_refused(prereg):
    perts = _perts(prereg)
    perts["single_a"]["policies"]["candidate"] = _rows(-100.0, ids=IDS[::-1])
    with pytest.raises(ep.EvalProtocolError, match="scenario ids differ"):
        ep.evaluate_robustness(_policies(-110.0, -108.0, -100.0), perts, prereg)


def test_robustness_evaluation_is_deterministic(prereg):
    unp = _policies(-110.0, -108.0, -100.0)
    one = ep.pretty_json(ep.evaluate_robustness(unp, _perts(prereg), prereg))
    two = ep.pretty_json(ep.evaluate_robustness(unp, _perts(prereg), prereg))
    assert one == two


# ----------------------------------------------------------------------------- the decision
def _t8(outcome="A"):
    detail = {
        "per_baseline": {
            b: {"criteria": {"seed_ci_excludes_zero_for_ppo": True, "secondary_within_tolerance": True}}
            for b in ("rule", "best_constant")
        },
        "envelope_selected_candidate": {"ok": True},
    }
    return {"outcome": outcome, "reason": f"t8 {outcome}", "detail": detail}


def _robust(ok=True):
    return {"criteria": [{"id": f"R{i}", "passed": ok, "failed_on": []} for i in range(1, 5)], "all_passed": ok}


REV = "a" * 40


def test_decision_a_requires_t8_a_and_robustness_and_a_clean_run():
    d = ep.final_decision(
        _t8("A"), _robust(True), code_revision=REV, dirty=False, manifest_complete=True, prereg_ok=True
    )
    assert (d["outcome"], d["promotable"], d["registry_action"], d["result"]) == ("A", True, "promote", "promote")
    assert "robust to the listed perturbations in this simulator" in d["claim_allowed"]


def test_decision_downgrades_t8_a_that_is_not_robust_to_b_and_rejects():
    d = ep.final_decision(
        _t8("A"), _robust(False), code_revision=REV, dirty=False, manifest_complete=True, prereg_ok=True
    )
    assert (d["outcome"], d["promotable"], d["registry_action"], d["result"]) == (
        "B",
        False,
        "reject",
        ep.NO_PROMOTABLE,
    )
    assert d["claim_allowed"] == "none"


@pytest.mark.parametrize("outcome", ["B", "C"])
def test_decision_t8_b_and_c_stand_and_nothing_is_promotable(outcome):
    d = ep.final_decision(
        _t8(outcome), _robust(True), code_revision=REV, dirty=False, manifest_complete=True, prereg_ok=True
    )
    assert d["outcome"] == outcome and not d["promotable"] and d["result"] == ep.NO_PROMOTABLE


@pytest.mark.parametrize(
    ("rev", "dirty", "complete", "prereg_ok", "gate"),
    [
        (REV, True, True, True, "clean_tree"),
        ("unknown", False, True, True, "clean_tree"),
        (REV, False, False, True, "manifest_complete"),
        (REV, False, True, False, "preregistration_verified"),
    ],
)
def test_a_run_that_fails_a_hygiene_gate_is_never_promotable(rev, dirty, complete, prereg_ok, gate):
    d = ep.final_decision(
        _t8("A"), _robust(True), code_revision=rev, dirty=dirty, manifest_complete=complete, prereg_ok=prereg_ok
    )
    assert d["outcome"] == "A" and d["promotable"] is False and d["registry_action"] == "reject"
    assert gate in d["reason"] and d["result"] == ep.NO_PROMOTABLE


def test_a_baselines_only_run_records_no_promotable_policy():
    base = {"outcome": "NOT_EVALUATED", "reason": "no candidate"}
    d = ep.final_decision(base, None, code_revision=REV, dirty=False, manifest_complete=True, prereg_ok=True)
    assert (d["outcome"], d["registry_action"], d["result"], d["promotable"]) == (
        "NOT_EVALUATED", "none", ep.NO_PROMOTABLE, False,
    )  # fmt: skip


# ----------------------------------------------------------------------------- reports come from results.json only
def _results(prereg, *, candidate=-100.0):
    unp = _policies(-110.0, -108.0, candidate)
    rob = ep.evaluate_robustness(unp, _perts(prereg), prereg)
    decision = ep.final_decision(_t8("A"), rob, code_revision=REV, dirty=False, manifest_complete=True, prereg_ok=True)
    return ep.round_floats(
        {
            "run_id": "eval-test",
            "prereg": prereg,
            "prereg_sha256": prereg["preregistration_sha256"],
            "physics_version": "1",
            "scenario_set_id": "abc",
            "scenario_inputs": "synthetic",
            "carbon": {"is_real": False, "flat_curve": True},
            "robustness": rob,
            "decision": decision,
        }
    )


def test_report_tables_and_figure_are_generated_from_results_json_only(tmp_path, prereg):
    run = tmp_path / "run"
    run.mkdir()
    results = _results(prereg)
    (run / "results.json").write_text(ep.pretty_json(results), encoding="utf-8")
    written = ep.write_reports(run, json.loads((run / "results.json").read_text(encoding="utf-8")))
    assert {"REPORT.md", "figures/degradation.svg", "tables/degradation.csv", "tables/criteria.csv"} <= set(written)
    assert ep.verify_reports(run) == []
    text = (run / "REPORT.md").read_text(encoding="utf-8")
    assert "**Outcome: A**" in text and "stress test" in text and "not asserted to be realistic" in text
    assert "carbon real: False" in text  # carbon fallback is flagged
    assert (run / "figures" / "degradation.svg").read_text(encoding="utf-8").startswith("<svg")


def test_editing_a_generated_file_or_results_is_detected_by_verify(tmp_path, prereg):
    run = tmp_path / "run"
    run.mkdir()
    (run / "results.json").write_text(ep.pretty_json(_results(prereg)), encoding="utf-8")
    ep.write_reports(run, json.loads((run / "results.json").read_text(encoding="utf-8")))
    (run / "REPORT.md").write_text("hand-edited number: 99.9\n", encoding="utf-8")
    assert ep.verify_reports(run) == ["REPORT.md"]
    ep.write_reports(run, json.loads((run / "results.json").read_text(encoding="utf-8")))
    changed = json.loads((run / "results.json").read_text(encoding="utf-8"))
    changed["robustness"]["unperturbed_summary"]["candidate"]["total_reward"] = 12345.0
    (run / "results.json").write_text(ep.pretty_json(changed), encoding="utf-8")
    assert "REPORT.md" in ep.verify_reports(run)


def test_every_number_in_the_report_is_in_results_json(tmp_path, prereg):
    run = tmp_path / "run"
    run.mkdir()
    results = _results(prereg)
    (run / "results.json").write_text(ep.pretty_json(results), encoding="utf-8")
    ep.write_reports(run, results)
    haystack = (run / "results.json").read_text(encoding="utf-8")
    nums = set(re.findall(r"-?\d+\.\d+", (run / "REPORT.md").read_text(encoding="utf-8")))
    values = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", haystack)]
    for n in nums:
        assert any(
            abs(float(n) - v) <= 0.0006 + 0.0006 * abs(v) for v in values
        ), f"{n} is not derived from results.json"


def test_results_json_is_canonical_and_byte_stable(prereg):
    a, b = ep.pretty_json(_results(prereg)), ep.pretty_json(_results(prereg))
    assert a == b and "\r" not in a and a.endswith("\n")
    assert ep.pretty_json({"x": -0.0, "y": 0.1 + 0.2}) == '{\n  "x": 0.0,\n  "y": 0.3\n}\n'
    with pytest.raises(ep.EvalProtocolError):
        ep.round_floats({"x": float("nan")})


def test_manifest_completeness_rules():
    full = {
        "run_id": "r", "started_at_utc": "t", "code_revision": REV, "dirty": False, "platform": {"os": "x"},
        "command_line": ["a"], "config_files": {"f": "h"}, "scenario_set_id": "s", "seeds": {"a": 1},
        "artifacts": [], "prereg_sha256": "p", "result_sha256": "r",
    }  # fmt: skip
    assert ep.manifest_is_complete(full)
    for key in ("run_id", "prereg_sha256", "result_sha256", "seeds", "config_files"):
        broken = dict(full)
        broken[key] = None
        assert not ep.manifest_is_complete(broken), key
    broken = dict(full)
    del broken["artifacts"]
    assert not ep.manifest_is_complete(broken)


# ----------------------------------------------------------------------------- registry: promote / reject
def _setup(tmp_path, *, outcome="A", dirty=False, criteria_ok=True, rev=REV, status="candidate", mutate=None):
    """A registry with one candidate and a consistent evaluation run next to it."""
    root = tmp_path / "repo"
    model_dir = root / "models" / "cand" / "seed_0"
    model_dir.mkdir(parents=True)
    (model_dir / "ppo_model.zip").write_bytes(b"policy-bytes")
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    files = {
        f"models/cand/seed_0/{n}": {"sha256": ep.sha256_file(model_dir / n), "size": (model_dir / n).stat().st_size}
        for n in ("ppo_model.zip", "config.json")
    }
    compat = {f: f"v-{f}" for f in rc.COMPAT_FIELDS}
    entry = {"model_id": "ppo-cand-0", "name": "ppo_candidate", "status": status, "files": files, "history": [
        {"action": "register", "to": "candidate", "at_utc": "2026-10-01T00:00:00+00:00"}], **compat}  # fmt: skip
    registry = root / "models" / "registry.json"
    other = {"name": "forecaster", "version": "1", "history": [{"action": "x"}]}  # a v1-style entry stays untouched
    registry.write_text(json.dumps([other, entry]), encoding="utf-8")

    run = tmp_path / "runs" / "eval-1"
    run.mkdir(parents=True)
    prereg_sha = "p" * 64
    results = {"decision": {"outcome": outcome}, "prereg_sha256": prereg_sha}
    (run / "results.json").write_text(json.dumps(results), encoding="utf-8")
    result_sha = ep.sha256_file(run / "results.json")
    manifest = {
        "run_id": "eval-1", "started_at_utc": "t", "code_revision": rev, "dirty": dirty, "platform": {"os": "x"},
        "command_line": ["a"], "config_files": {"f": "h"}, "scenario_set_id": "s", "seeds": {"a": 1}, "artifacts": [],
        "prereg_sha256": prereg_sha, "result_sha256": result_sha,
    }  # fmt: skip
    decision = {
        "outcome": outcome, "promotable": outcome == "A" and criteria_ok, "registry_action": "promote",
        "criteria": [{"id": "R1_envelope", "passed": criteria_ok}, {"id": "R2_noninferiority", "passed": True}],
        "gates": [{"id": "clean_tree", "passed": not dirty}], "model_id": "ppo-cand-0",
        "candidate_files": {n: files[f"models/cand/seed_0/{n}"]["sha256"] for n in ("ppo_model.zip", "config.json")},
        "prereg_sha256": prereg_sha, "result_sha256": result_sha,
    }  # fmt: skip
    if mutate:
        mutate(manifest, decision, results, run)
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    (run / "status.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    return {"root": root, "registry": registry, "run": run, "compat": compat, "prereg_sha": prereg_sha}


def _promote(s, **kw):
    kw.setdefault("running", s["compat"])
    kw.setdefault("verify_prereg", lambda: {"preregistration_sha256": s["prereg_sha"]})
    kw.setdefault("audit", lambda *a: {"written": False, "reason": "test"})
    return rc.transition("promote", "ppo-cand-0", registry_path=s["registry"], run_dir=s["run"], root=s["root"], **kw)


def _refused(s, **kw):
    with pytest.raises(rc.RegistryError) as exc:
        _promote(s, **kw)
    return exc.value


def test_a_clean_outcome_a_run_promotes_the_candidate_and_appends_history(tmp_path):
    s = _setup(tmp_path)
    updated = _promote(s)
    assert updated["status"] == "promoted" and updated["evaluation_ref"] == "eval-1"
    stored = json.loads(s["registry"].read_text(encoding="utf-8"))
    assert stored[1]["status"] == "promoted" and len(stored[1]["history"]) == 2
    event = stored[1]["history"][-1]
    assert (event["action"], event["from"], event["to"], event["run_id"]) == (
        "promote",
        "candidate",
        "promoted",
        "eval-1",
    )
    assert event["prereg_sha256"] == s["prereg_sha"] and event["audit"] == {"written": False, "reason": "test"}
    assert stored[0] == {"name": "forecaster", "version": "1", "history": [{"action": "x"}]}


def test_promote_refuses_a_dirty_run(tmp_path):
    s = _setup(tmp_path, dirty=True)
    err = _refused(s)
    assert any("clean tree" in f for f in err.failures)
    assert json.loads(s["registry"].read_text(encoding="utf-8"))[1]["status"] == "candidate"


@pytest.mark.parametrize("rev", ["unknown", "dirty:abc123", "abc", "G" * 40])
def test_promote_refuses_a_revision_that_is_not_a_commit_hash(tmp_path, rev):
    assert any("clean tree" in f for f in _refused(_setup(tmp_path, rev=rev)).failures)


def test_promote_refuses_the_wrong_preregistration_hash(tmp_path):
    s = _setup(tmp_path)
    err = _refused(s, verify_prereg=lambda: {"preregistration_sha256": "q" * 64})
    assert any("pre-registration hash mismatch" in f for f in err.failures)


def test_promote_refuses_when_the_preregistration_cannot_be_verified(tmp_path):
    def broken():
        raise ep.EvalProtocolError("lock missing")

    assert any("cannot be verified" in f for f in _refused(_setup(tmp_path), verify_prereg=broken).failures)


def test_promote_refuses_a_failed_criterion(tmp_path):
    err = _refused(_setup(tmp_path, criteria_ok=False))
    assert any("criteria/gates not met" in f and "R1_envelope" in f for f in err.failures)
    assert any("does not say promote" in f for f in err.failures)


@pytest.mark.parametrize("outcome", ["B", "C", "NOT_EVALUATED"])
def test_promote_refuses_any_outcome_other_than_a(tmp_path, outcome):
    assert any("not 'A'" in f for f in _refused(_setup(tmp_path, outcome=outcome)).failures)


def test_promote_refuses_a_tampered_results_file(tmp_path):
    def tamper(manifest, decision, results, run):
        (run / "results.json").write_text(json.dumps({**results, "extra": 1}), encoding="utf-8")

    assert any("results.json does not match" in f for f in _refused(_setup(tmp_path, mutate=tamper)).failures)


def test_promote_refuses_an_incomplete_or_unfinished_run(tmp_path):
    s = _setup(tmp_path)
    (s["run"] / "decision.json").unlink()
    assert any("incomplete" in f for f in _refused(s).failures)
    s = _setup(tmp_path / "second")
    (s["run"] / "status.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    assert any("not 'completed'" in f for f in _refused(s).failures)


def test_promote_refuses_files_that_are_not_the_ones_evaluated(tmp_path):
    s = _setup(tmp_path)
    (s["root"] / "models" / "cand" / "seed_0" / "ppo_model.zip").write_bytes(b"other bytes")
    err = _refused(s)
    assert any("no longer matches its recorded sha256" in f for f in err.failures)

    def swap(manifest, decision, results, run):
        decision["candidate_files"]["ppo_model.zip"] = "0" * 64

    assert any("not the files that were evaluated" in f for f in _refused(_setup(tmp_path / "b", mutate=swap)).failures)


def test_promote_refuses_incompatible_or_unverifiable_candidates(tmp_path):
    s = _setup(tmp_path)
    running = dict(s["compat"], physics_version="2")
    assert any("compat physics_version" in f for f in _refused(s, running=running).failures)
    running = dict(s["compat"], reward_version=None)
    assert any("running value unavailable" in f for f in _refused(s, running=running).failures)


def test_promote_refuses_a_waived_candidate_and_missing_compat_fields(tmp_path):
    s = _setup(tmp_path)
    stored = json.loads(s["registry"].read_text(encoding="utf-8"))
    stored[1]["compat_waiver"] = {"fields": ["reward_version"], "reason": "x", "expires_after_task": "T27"}
    del stored[1]["action_schema_hash"]
    s["registry"].write_text(json.dumps(stored), encoding="utf-8")
    failures = _refused(s).failures
    assert any("compat_waiver" in f for f in failures) and any("lacks it" in f for f in failures)


def test_promote_refuses_when_the_run_evaluated_another_model(tmp_path):
    def other(manifest, decision, results, run):
        decision["model_id"] = "someone-else"

    assert any("evaluated model" in f for f in _refused(_setup(tmp_path, mutate=other)).failures)


def test_promote_lists_every_problem_at_once(tmp_path):
    err = _refused(_setup(tmp_path, dirty=True, criteria_ok=False, outcome="B"))
    assert len(err.failures) >= 4


@pytest.mark.parametrize("status", ["promoted", "quarantined", "rejected", "retired"])
def test_only_a_candidate_can_be_promoted(tmp_path, status):
    s = _setup(tmp_path, status=status)
    with pytest.raises(rc.RegistryError, match=f"status is '{status}'"):
        _promote(s)
    assert json.loads(s["registry"].read_text(encoding="utf-8"))[1]["status"] == status


def test_default_running_values_fail_closed_in_this_tree(tmp_path):
    s = _setup(tmp_path)
    err = _refused(s, running=rc.running_compat_values())
    assert any("running value unavailable" in f for f in err.failures)  # T19/T27 values do not exist yet


def test_reject_moves_a_candidate_to_quarantined_with_a_reason(tmp_path):
    s = _setup(tmp_path, outcome="B")
    updated = rc.transition(
        "reject", "ppo-cand-0", registry_path=s["registry"], run_dir=s["run"],
        reason="outcome B: not shown better than the rule baseline", audit=lambda *a: {"written": False, "reason": "t"},
    )  # fmt: skip
    assert updated["status"] == "quarantined"
    assert updated["quarantine_reason"].startswith("outcome B") and updated["evaluation_ref"] == "eval-1"
    last = updated["history"][-1]
    assert (last["action"], last["from"], last["to"]) == ("reject", "candidate", "quarantined")


def test_reject_and_quarantine_and_retire_need_a_reason(tmp_path):
    s = _setup(tmp_path)
    for action in ("reject", "quarantine"):
        with pytest.raises(rc.RegistryError, match="requires a reason"):
            rc.transition(action, "ppo-cand-0", registry_path=s["registry"], run_dir=s["run"], reason="  ")
    with pytest.raises(rc.RegistryError, match="needs --run"):
        rc.transition("promote", "ppo-cand-0", registry_path=s["registry"])
    with pytest.raises(rc.RegistryError, match="needs --run"):
        rc.transition("reject", "ppo-cand-0", registry_path=s["registry"], reason="x")


def test_retire_only_applies_to_a_promoted_model_and_records_the_previous_state(tmp_path):
    s = _setup(tmp_path)
    audit = lambda *a: {"written": False, "reason": "t"}  # noqa: E731
    with pytest.raises(rc.RegistryError, match="status is 'candidate'"):
        rc.transition("retire", "ppo-cand-0", registry_path=s["registry"], reason="x", audit=audit)
    _promote(s)
    retired = rc.transition("retire", "ppo-cand-0", registry_path=s["registry"], reason="rollback", audit=audit)
    assert retired["status"] == "retired" and retired["history"][-1]["from"] == "promoted"
    assert [h.get("to") for h in retired["history"]] == ["candidate", "promoted", "retired"]
    with pytest.raises(rc.RegistryError):
        rc.transition("promote", "ppo-cand-0", registry_path=s["registry"], run_dir=s["run"], root=s["root"])


def test_quarantine_works_from_candidate_and_promoted(tmp_path):
    s = _setup(tmp_path)
    audit = lambda *a: {"written": False, "reason": "t"}  # noqa: E731
    q = rc.transition("quarantine", "ppo-cand-0", registry_path=s["registry"], reason="bad", audit=audit)
    assert q["status"] == "quarantined" and q["quarantine_reason"] == "bad"
    with pytest.raises(rc.RegistryError):
        rc.transition("quarantine", "ppo-cand-0", registry_path=s["registry"], reason="again", audit=audit)


def test_history_is_append_only_and_prior_entries_are_never_altered(tmp_path):
    s = _setup(tmp_path)
    before = json.loads(s["registry"].read_text(encoding="utf-8"))
    _promote(s)
    rc.transition(
        "retire",
        "ppo-cand-0",
        registry_path=s["registry"],
        reason="r",
        audit=lambda *a: {"written": False, "reason": "t"},
    )
    after = json.loads(s["registry"].read_text(encoding="utf-8"))
    for old, new in zip(before, after, strict=True):
        assert new["history"][: len(old["history"])] == old["history"]
    assert len(after[1]["history"]) == 3
    rc.assert_history_unaltered(before, after)


def test_assert_history_unaltered_catches_edits_and_removals():
    old = [{"model_id": "m", "history": [{"a": 1}, {"b": 2}]}]
    with pytest.raises(rc.RegistryError, match="altered"):
        rc.assert_history_unaltered(old, [{"model_id": "m", "history": [{"a": 9}, {"b": 2}, {"c": 3}]}])
    with pytest.raises(rc.RegistryError, match="altered"):
        rc.assert_history_unaltered(old, [{"model_id": "m", "history": [{"a": 1}]}])
    with pytest.raises(rc.RegistryError, match="entries"):
        rc.assert_history_unaltered(old, [])
    rc.assert_history_unaltered(old, [{"model_id": "m", "history": [{"a": 1}, {"b": 2}, {"c": 3}]}])


def test_registry_write_is_atomic_and_keeps_a_backup(tmp_path):
    s = _setup(tmp_path)
    original = s["registry"].read_text(encoding="utf-8")
    _promote(s)
    assert s["registry"].with_name("registry.json.bak").read_text(encoding="utf-8") == original
    assert not list(s["registry"].parent.glob("*.tmp"))


def test_a_failed_write_leaves_the_registry_untouched(tmp_path, monkeypatch):
    s = _setup(tmp_path)
    original = s["registry"].read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(rc.os, "replace", boom)
    with pytest.raises(OSError):
        _promote(s)
    assert s["registry"].read_bytes() == original and not list(s["registry"].parent.glob("*.tmp"))


def test_an_unreachable_database_does_not_block_a_transition_but_is_recorded(tmp_path, monkeypatch):
    s = _setup(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    updated = rc.transition(
        "promote", "ppo-cand-0", registry_path=s["registry"], run_dir=s["run"], root=s["root"], running=s["compat"],
        verify_prereg=lambda: {"preregistration_sha256": s["prereg_sha"]},
    )  # fmt: skip
    assert updated["status"] == "promoted"
    assert updated["history"][-1]["audit"] == {"written": False, "reason": "DATABASE_URL not set"}


def test_audit_failures_are_swallowed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    result = rc.write_audit_row("promote", "m", {"x": 1})
    assert result["written"] is False and result["reason"]


def test_unknown_model_and_duplicate_ids_are_refused(tmp_path):
    s = _setup(tmp_path)
    with pytest.raises(rc.RegistryError, match="no registry entry"):
        rc.transition("quarantine", "nope", registry_path=s["registry"], reason="x")
    stored = json.loads(s["registry"].read_text(encoding="utf-8"))
    stored.append(dict(stored[1]))
    s["registry"].write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(rc.RegistryError, match="not unique"):
        rc.transition("quarantine", "ppo-cand-0", registry_path=s["registry"], reason="x")


def test_decide_promotes_a_qualifying_run(tmp_path):
    s = _setup(tmp_path)
    action, entry = rc.decide_from_run(
        "ppo-cand-0", s["run"], registry_path=s["registry"], root=s["root"], running=s["compat"],
        verify_prereg=lambda: {"preregistration_sha256": s["prereg_sha"]}, audit=lambda *a: {"written": False, "reason": "t"},
    )  # fmt: skip
    assert action == "promote" and entry["status"] == "promoted"


def test_decide_quarantines_a_non_qualifying_candidate_with_the_reasons(tmp_path):
    s = _setup(tmp_path, outcome="B", criteria_ok=False)
    action, entry = rc.decide_from_run(
        "ppo-cand-0", s["run"], registry_path=s["registry"], root=s["root"], running=s["compat"],
        verify_prereg=lambda: {"preregistration_sha256": s["prereg_sha"]}, audit=lambda *a: {"written": False, "reason": "t"},
    )  # fmt: skip
    assert action == "reject" and entry["status"] == "quarantined"
    assert "not 'A'" in entry["quarantine_reason"] and len(entry["quarantine_reason"]) <= 1000


def test_decide_does_nothing_when_no_candidate_was_evaluated(tmp_path):
    def baselines_only(manifest, decision, results, run):
        decision["outcome"] = "NOT_EVALUATED"
        decision["result"] = ep.NO_PROMOTABLE

    s = _setup(tmp_path, mutate=baselines_only)
    action, entry = rc.decide_from_run("ppo-cand-0", s["run"], registry_path=s["registry"])
    assert (action, entry) == ("none", None)
    assert json.loads(s["registry"].read_text(encoding="utf-8"))[1]["status"] == "candidate"


def test_cli_list_and_refusal_exit_codes(tmp_path, capsys):
    s = _setup(tmp_path)
    assert rc.main(["--registry", str(s["registry"]), "list"]) == 0
    assert "ppo-cand-0" in capsys.readouterr().out
    code = rc.main(["--registry", str(s["registry"]), "promote", "ppo-cand-0", "--run", str(s["run"])])
    assert code == 2 and "REFUSED" in capsys.readouterr().err


# ----------------------------------------------------------------------------- end to end on the real environment
class _ConstantCandidate:
    """A stand-in 'trained policy' (fixed action): enough to exercise the pipeline; it is not a PPO model."""

    def __init__(self, chilled: float, mode: float) -> None:
        self._a = np.array([chilled, mode], dtype=np.float32)

    def policy_action(self, obs, deterministic=True):
        return self._a


def _small_protocol_inputs(prereg):
    small = copy.deepcopy(prereg)
    small["eval_config"]["n_validation_per_family"] = 2
    small["eval_config"]["n_test_per_family"] = 3
    manifest = {
        "perturbations": [
            _entry(id="cop_m20", parameter="cop_base.closed_loop", value=0.8),
            _entry(id="cth_p20", parameter="C_th", value=1.2),
            _entry(id="cap_m20", parameter="capacity_margin", value=0.8),
        ],
        "joint_sets": [{"id": "joint", "members": ["cop_m20", "cap_m20"], "basis": ep.BASIS_STRESS}],
    }
    return small, manifest


def test_pipeline_end_to_end_is_deterministic_frozen_and_reportable(tmp_path, prereg):
    pytest.importorskip("gymnasium")
    small, manifest = _small_protocol_inputs(prereg)
    candidates = {s: _ConstantCandidate(0.3 + 0.1 * s, 0.4) for s in small["eval_config"]["training_seeds"]}
    from src import policy_evaluation as pe

    curve = np.full(24, 400.0)
    docs = []
    for _ in range(2):
        proto = ep.run_evaluation_protocol(
            small, manifest, candidates=candidates, carbon_curve=curve, carbon_is_real=False
        )
        docs.append(
            ep.assemble_results("eval-it", small, proto, code_revision="unknown", dirty=True, manifest_complete=True)
        )
    assert ep.pretty_json(docs[0]) == ep.pretty_json(docs[1])  # same inputs => byte-identical results.json (L1)
    res = docs[0]
    assert res["robustness"]["evaluated"] == ["cap_m20", "cop_m20", "joint"] and res["robustness"][
        "not_applicable"
    ] == ["cth_p20"]
    assert res["frozen_check"]["retraining_or_retuning_on_perturbed_or_test_data"] is False
    assert res["decision"]["promotable"] is False and res["decision"]["result"] == ep.NO_PROMOTABLE  # dirty + stand-in
    assert len(res["test_scenarios"]) == 9 and all(s.split("/")[1] == "test" for s in res["test_scenarios"])
    assert min(int(s.rsplit("/", 1)[1]) for s in res["test_scenarios"]) >= 200_000
    assert set(res["unperturbed"]) == {"rule", "best_constant", "candidate"}
    # a perturbation really changed the plant: the rule baseline's reward differs from the unperturbed one
    unp = np.mean([r["total_reward"] for r in res["unperturbed"]["rule"]])
    pert = np.mean([r["total_reward"] for r in res["perturbations"]["cop_m20"]["policies"]["rule"]])
    assert unp != pert
    run = tmp_path / "run"
    run.mkdir()
    out = json.loads(ep.pretty_json(res))
    (run / "results.json").write_text(ep.pretty_json(out), encoding="utf-8")
    ep.write_reports(run, out)
    assert ep.verify_reports(run) == []
    assert pe.PRIMARY_METRIC == ep.PRIMARY


def test_baselines_only_pipeline_records_not_evaluated(tmp_path, prereg):
    pytest.importorskip("gymnasium")
    small, manifest = _small_protocol_inputs(prereg)
    proto = ep.run_evaluation_protocol(
        small, manifest, candidates=None, carbon_curve=np.full(24, 400.0), carbon_is_real=False
    )
    res = ep.assemble_results("eval-bo", small, proto, code_revision=REV, dirty=False, manifest_complete=True)
    assert res["decision"]["outcome"] == "NOT_EVALUATED" and res["decision"]["result"] == ep.NO_PROMOTABLE
    assert res["decision"]["registry_action"] == "none" and "candidate" not in res["unperturbed"]
    run = tmp_path / "run"
    run.mkdir()
    out = json.loads(ep.pretty_json(res))
    (run / "results.json").write_text(ep.pretty_json(out), encoding="utf-8")
    ep.write_reports(run, out)  # a baselines-only run must still produce a complete, verifiable report
    assert ep.verify_reports(run) == []
    assert "NOT_EVALUATED" in (run / "REPORT.md").read_text(encoding="utf-8")
