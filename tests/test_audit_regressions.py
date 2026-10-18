"""Regression tests for the defects found in the deep audit (docs/audit/TwinGrid_Issue_Register.md).

Each test names the issue it guards. They run on the plain simulator (no torch / TF / DB).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src import policy_evaluation as pe
from src.baselines import config as bcfg
from src.optimizer import DataCentreEnv, JointOptimizer, UnsupportedPhysicsVersionForRL
from src.versions import PhysicsVersionError

ROOT = Path(__file__).resolve().parents[1]
CURVE = np.full(24, 475.0)
SMALL = replace(pe.EvalConfig(), n_validation_per_family=2, n_test_per_family=2, constant_chilled_C=(18.0, 22.0))
# a legacy-0 config registers its own (legacy-range) set-points
LEGACY = dict(constant_chilled_C=(10.0, 15.0), rule_chilled_C=12.0)


def _one_test_scenario(cfg: pe.EvalConfig, sid: str = "stress_0.0/test/200000"):
    return next(s for s in pe.build_scenarios(cfg)["test"] if s.scenario_id == sid)


# ------------------------------------------------------------------------------------------- TG-A-01
def test_evaluation_runs_the_physics_its_config_declares_not_the_process_default(monkeypatch):
    """TG-A-01: run_episode used to omit physics_version, so the environment ran the process default while the
    report carried the config's label."""
    v1 = replace(pe.EvalConfig(), physics_version="1")
    leg = replace(pe.EvalConfig(), physics_version="legacy-0", **LEGACY)
    sc = _one_test_scenario(v1)
    rule = pe.RulePolicy(v1.rule_chilled_C, physics_version="1")
    rule_leg = pe.RulePolicy(12.0)  # legacy-0 range

    monkeypatch.delenv("PHYSICS_VERSION", raising=False)
    base_v1 = pe.run_episode(rule, sc, v1, CURVE).metrics
    base_leg = pe.run_episode(rule_leg, sc, leg, CURVE).metrics
    assert base_v1 != base_leg, "the two physics versions must give different numbers for this to be a test"

    # flipping the process-wide default must not change what a config that names its physics produces
    for ambient in ("legacy-0", "1"):
        monkeypatch.setenv("PHYSICS_VERSION", ambient)
        assert pe.run_episode(rule, sc, v1, CURVE).metrics == base_v1
        assert pe.run_episode(rule_leg, sc, leg, CURVE).metrics == base_leg


def test_environment_receives_the_declared_version_explicitly(monkeypatch):
    seen: list[str | None] = []
    real = pe.DataCentreEnv

    def spy(**kw):
        seen.append(kw.get("physics_version"))
        return real(**kw)

    monkeypatch.setattr(pe, "DataCentreEnv", spy)
    cfg = replace(pe.EvalConfig(), physics_version="legacy-0", episode_steps=3, **LEGACY)
    pe.run_episode(pe.RulePolicy(12.0), _one_test_scenario(cfg), cfg, CURVE)
    assert seen == ["legacy-0"]


def test_a_mismatching_environment_is_refused(monkeypatch):
    real = pe.DataCentreEnv

    class Wrong(real):  # an environment that ignores the requested physics
        def __init__(self, **kw):
            kw["physics_version"] = "legacy-0"
            super().__init__(**kw)

    monkeypatch.setattr(pe, "DataCentreEnv", Wrong)
    cfg = replace(pe.EvalConfig(), physics_version="1", episode_steps=3)
    with pytest.raises(pe.PhysicsMismatchError):
        pe.run_episode(pe.RulePolicy(12.0), _one_test_scenario(cfg), cfg, CURVE)


def test_results_record_the_executed_physics():
    res = pe.run_evaluation(SMALL, ppo_candidates=None, carbon_curve=CURVE, carbon_is_real=False)
    assert res["physics_version"] == "1" == res["physics_version_executed"]
    leg = pe.run_evaluation(
        replace(SMALL, physics_version="legacy-0 (implicit)", **LEGACY),
        ppo_candidates=None,
        carbon_curve=CURVE,
        carbon_is_real=False,
    )
    assert leg["physics_version"] == "legacy-0 (implicit)" and leg["physics_version_executed"] == "legacy-0"


def test_unknown_and_unsupported_physics_labels_never_fall_back():
    with pytest.raises(PhysicsVersionError):
        pe.resolve_physics_version("legacy-0 (implicit) ")  # near-miss label
    with pytest.raises(PhysicsVersionError):
        pe.resolve_physics_version("3")
    with pytest.raises(UnsupportedPhysicsVersionForRL):
        pe.resolve_physics_version("2")


def test_committed_baselines_only_report_reproduces_under_its_declared_physics():
    """The checked-in report says "legacy-0 (implicit)". Re-running its first rule episode under the committed
    protocol must give the recorded numbers: the label means what it says, and the number is reproducible."""
    cfg = pe.load_preregistered_config(ROOT / "reports" / "policy_evaluation")
    results = json.loads((ROOT / "reports/policy_evaluation/baselines_only_0fcafef9d28fd539/results.json").read_text())
    recorded = results["per_scenario_test"]["rule"][0]
    curve, is_real = pe.load_diurnal_carbon_intensity()
    if is_real:
        pytest.skip("a real carbon curve is installed; the committed report used the flat curve")
    sc = _one_test_scenario(cfg, recorded["scenario_id"])
    got = pe.run_episode(pe.RulePolicy(cfg.rule_chilled_C), sc, cfg, np.asarray(curve, float)).metrics
    for k in ("total_reward", "energy_kwh", "water_L", "inlet_under_min_steps"):
        assert got[k] == pytest.approx(recorded[k], rel=1e-9, abs=1e-9), k


# ------------------------------------------------------------------------------------------- TG-A-02
def test_hard_constraint_total_counts_all_four_limits():  # A2 (TG-A-12): the PUE limit is the fourth
    sc = pe.build_scenarios(replace(pe.EvalConfig(), n_test_per_family=1))["test"][:1]

    def res(**over):
        m = {k: 0.0 for k in pe.METRICS}
        m.update(over)
        return [pe.EpisodeResult(sc[0].scenario_id, m, "h")]

    assert pe.hard_constraint_total(res()) == 0
    for metric in pe.HARD_CONSTRAINT_METRICS:
        assert pe.hard_constraint_total(res(**{metric: 2.0})) == 2.0
    assert set(pe.HARD_CONSTRAINT_METRICS) == {
        "outlet_violation_steps",
        "inlet_over_max_steps",
        "inlet_under_min_steps",
        "pue_over_max_steps",
    }


def test_best_constant_is_chosen_among_envelope_feasible_constants():
    """TG-A-02b: the 'best constant' comparator used to be the highest-reward constant even if it violated the envelope."""
    res = pe.run_evaluation(SMALL, ppo_candidates=None, carbon_curve=CURVE, carbon_is_real=False)
    sel = res["selection"]
    if sel["best_constant_envelope_feasible"]:
        for row in res["per_scenario_test"]["best_constant"]:
            assert sum(row[m] for m in pe.HARD_CONSTRAINT_METRICS) == 0
    leg = pe.run_evaluation(
        replace(SMALL, physics_version="legacy-0", **LEGACY),
        ppo_candidates=None,
        carbon_curve=CURVE,
        carbon_is_real=False,
    )
    # legacy-0's envelope is unreachable: no constant is feasible and the result says so instead of hiding it
    assert leg["selection"]["best_constant_envelope_feasible"] is False
    assert leg["selection"]["min_inlet_under_min_steps_across_constant_grid"] > 0


# ------------------------------------------------------------------------------------------- TG-A-03
@pytest.mark.parametrize("cls", [DataCentreEnv, JointOptimizer])
def test_rl_environment_rejects_physics_v2_at_construction(cls):
    """TG-A-03: physics '2' passed validate_physics_version and failed with KeyError inside reset()."""
    with pytest.raises(UnsupportedPhysicsVersionForRL, match="not supported by the RL environment"):
        cls(physics_version="2", seed=0)


@pytest.mark.parametrize("version", ["legacy-0", "1"])
def test_rl_environment_still_runs_supported_versions(version):
    env = DataCentreEnv(physics_version=version, seed=0, max_steps=2)
    env.reset(seed=0)
    _obs, _r, _term, _trunc, info = env.step(np.array([0.5, 0.0], dtype=np.float32))
    assert env.physics_version == version and "state" in info


# ------------------------------------------------------------------------------------------- TG-A-04
def test_baselines_refuse_a_protocol_whose_physics_differs_from_the_running_code():
    """TG-A-04: lineage recorded the running physics while the protocol could declare another."""
    from src.versions import active_physics_version

    running = active_physics_version()
    bcfg.assert_eval_physics_matches_lineage(running)
    other = "legacy-0" if running != "legacy-0" else "1"
    with pytest.raises(bcfg.BaselineConfigError, match="--prereg"):
        bcfg.assert_eval_physics_matches_lineage(other)


# ------------------------------------------------------------------------------------------- TG-A-05
@pytest.mark.xfail(
    strict=True,
    reason="TG-A-05: DigitalTwinOptimized is NOT numerically equivalent to DigitalTwin(legacy-0): on the benchmark "
    "inputs outlet differs by ~20 C and PUE by ~0.10. Remove this xfail when the divergence is fixed or the module is retired.",
)
def test_optimized_twin_matches_the_main_twin_on_the_benchmark_inputs():
    import sys

    sys.path.insert(0, str(ROOT))
    from benchmark_performance import generate_test_actions
    from src.digital_twin import DigitalTwin
    from src.digital_twin_optimized import DigitalTwinOptimized

    main, fast = DigitalTwin(physics_version="legacy-0"), DigitalTwinOptimized(enable_logging=False)
    for a in generate_test_actions():
        s1, s2 = main.step(dict(a)), fast.step(dict(a))
        assert s2.server_outlet_temp_C == pytest.approx(s1.server_outlet_temp_C, abs=1e-6)
        assert s2.pue == pytest.approx(s1.pue, abs=1e-6)
