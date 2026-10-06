"""T28: deterministic baselines v2 (Rule, Constant, Lookup, PID).

Unit tests (policies, PID anti-windup, tuners on synthetic sweeps) need no simulator run. The
integration tests tune and evaluate on a SMALL scenario set through the real environment and the T24 run
framework; the shipped ``configs/baselines`` and ``reports/runs/baselines-v2`` are checked at the end.
"""

from __future__ import annotations

import ast
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src import policy_evaluation as pe
from src import versions
from src.baselines import config as bcfg
from src.baselines import evaluation, tuning
from src.baselines import policies as bp
from src.optimizer import COOLING_MODES, DataCentreEnv
from src.repro import canonical, experiments, report
from src.repro.run import RunRequest, read_json, run
from src.repro.verify import verify_run

ROOT = Path(__file__).resolve().parent.parent
PREREG = "reports/policy_evaluation/PREREGISTRATION.json"
SMALL = replace(pe.EvalConfig(), n_validation_per_family=2, n_test_per_family=2, constant_chilled_C=(10.0, 15.0))
CURVE = np.full(24, 475.0)


# ============================================================================= policies


def test_actuator_limits_match_the_environment():
    env = DataCentreEnv(carbon_intensity_by_hour=CURVE)
    assert env._action_to_control(np.array([0.0, 0.0])) == (bp.CHILLED_MIN_C, "free_air")
    assert env._action_to_control(np.array([1.0, 1.0]))[0] == bp.CHILLED_MAX_C
    for mode in COOLING_MODES:
        assert env._action_to_control(bp.make_action(10.0, mode))[1] == mode
    for c in (5.0, 7.5, 10.0, 12.5, 15.0):
        assert env._action_to_control(bp.make_action(c, "hybrid"))[0] == pytest.approx(c)
    obs, _ = env.reset(seed=1)
    assert env._twin._applied_chilled_water_temp_C == bp.INITIAL_SETPOINT_C
    from src.digital_twin import DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP

    assert bp.MAX_RATE_C_PER_STEP == DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP


def test_policy_evaluation_re_exports_the_moved_policies_unchanged():
    assert pe.ConstantPolicy is bp.ConstantPolicy and pe.RulePolicy is bp.RulePolicy
    assert pe.constant_grid(SMALL)[0].name == "constant[10C,free_air]"
    assert len(pe.constant_grid(SMALL)) == 2 * len(COOLING_MODES)


def test_constant_policy_rejects_unknown_modes_and_emits_normalised_float32_actions():
    with pytest.raises(ValueError):
        bp.ConstantPolicy(10.0, "magic")
    a = bp.ConstantPolicy(12.5, "hybrid").act(None, {})
    assert a.dtype == np.float32 and a.shape == (2,) and a[0] == pytest.approx(0.75) and a[1] == pytest.approx(1.0)


def test_rule_policy_follows_the_production_mode_rule():
    from src.digital_twin import DigitalTwin

    rule, twin = bp.RulePolicy(), DigitalTwin()
    for outside, stress in ((5.0, 0.0), (25.0, 0.0), (25.0, 0.9), (15.0, 0.4)):
        mode = twin.select_cooling_mode(outside, stress).value
        assert rule.act(None, {"outside_temp": outside, "water_stress": stress})[1] == pytest.approx(
            COOLING_MODES.index(mode) / 3.0
        )


def _table(fn):
    return [[fn(i, j) for j in range(3)] for i in range(2)]


def test_lookup_bins_are_closed_left_open_right_with_unbounded_end_bins():
    p = bp.LookupPolicy([0.5], [10.0, 20.0], _table(lambda i, j: (5.0 + 5 * i, COOLING_MODES[j])))
    assert p.cell(0.49, 9.9) == (0, 0) and p.cell(0.5, 10.0) == (1, 1) and p.cell(0.5, 19.99) == (1, 1)
    assert p.cell(-3.0, -40.0) == (0, 0) and p.cell(99.0, 99.0) == (1, 2)
    action = p.act(None, {"utilisation": 0.7, "outside_temp": 25.0})
    assert action[0] == pytest.approx(bp.norm_chilled(10.0)) and action[1] == pytest.approx(
        COOLING_MODES.index(COOLING_MODES[2]) / 3.0
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"util_edges": [0.5, 0.2]},
        {"util_edges": [0.5, 0.5]},
        {"actions": [[(10.0, "hybrid")]]},
        {"actions": _table(lambda i, j: (20.0, "hybrid"))},
        {"actions": _table(lambda i, j: (10.0, "nope"))},
    ],
)
def test_lookup_rejects_malformed_tables(kwargs):
    base = {"util_edges": [0.5], "temp_edges": [10.0, 20.0], "actions": _table(lambda i, j: (10.0, "hybrid"))}
    with pytest.raises(ValueError):
        bp.LookupPolicy(**{**base, **kwargs})


# ----------------------------------------------------------------------------- PID


def pid(**kw):
    base = {"target_inlet_C": 22.0, "kp": 1.0, "ki": 0.0, "kd": 0.0, "mode_rule": "closed_loop"}
    return bp.PIDPolicy(**{**base, **kw})


def inlet_for_error(target: float, error: float) -> float:
    return target - error


def test_pid_raises_the_setpoint_when_the_inlet_is_colder_and_lowers_it_when_hotter():
    cold, hot = (
        pid(initial_setpoint_C=12.0),
        pid(initial_setpoint_C=12.0),
    )  # start mid-range so the 2 C/step rate limit is not what is being tested
    assert cold.setpoint(inlet_for_error(22.0, +1.5)) == pytest.approx(12.0 + 1.5)
    assert hot.setpoint(inlet_for_error(22.0, -1.5)) == pytest.approx(12.0 - 1.5)
    assert pid(kp=0.0).setpoint(18.0) == pytest.approx(12.0)  # no gain, no integral: the nominal set-point


def test_pid_output_respects_the_actuator_range_and_the_rate_limit_for_any_input():
    rng = np.random.default_rng(7)
    for kp, ki, kd in ((4.0, 0.1, 1.0), (0.5, 0.0, 0.0), (2.0, 0.05, 0.5)):
        p = pid(kp=kp, ki=ki, kd=kd)
        previous = p.output
        assert previous == bp.INITIAL_SETPOINT_C
        for inlet in rng.uniform(5.0, 45.0, size=400):
            u = p.setpoint(float(inlet))
            assert bp.CHILLED_MIN_C <= u <= bp.CHILLED_MAX_C
            assert abs(u - previous) <= bp.MAX_RATE_C_PER_STEP + 1e-12
            previous = u


def test_pid_anti_windup_bounds_the_integrator_under_sustained_saturation():
    guarded, naive = pid(ki=0.1, anti_windup=True), pid(ki=0.1, anti_windup=False)
    for _ in range(300):  # inlet 8 C under target: the output pins at the 15 C limit and stays there
        guarded.setpoint(14.0)
        naive.setpoint(14.0)
    assert guarded.output == naive.output == bp.CHILLED_MAX_C
    assert naive.integral > 2000.0  # the textbook windup
    assert guarded.integral < 5.0  # frozen as soon as the limit started to hold the output
    assert guarded.saturated_steps > 250


def test_pid_with_anti_windup_leaves_saturation_at_once_when_the_error_reverses_but_windup_does_not():
    def steps_until_below_limit(anti_windup: bool) -> int:
        p = pid(ki=0.1, anti_windup=anti_windup)
        for _ in range(300):
            p.setpoint(14.0)
        for n in range(1, 400):
            if p.setpoint(30.0) < bp.CHILLED_MAX_C:  # now 8 C too HOT: the set-point must come down
                return n
        return 400

    assert steps_until_below_limit(True) <= 2
    assert steps_until_below_limit(False) > 100


def test_pid_anti_windup_is_symmetric_at_the_lower_limit():
    guarded, naive = pid(ki=0.1), pid(ki=0.1, anti_windup=False)
    for _ in range(300):
        guarded.setpoint(40.0)
        naive.setpoint(40.0)
    assert guarded.output == naive.output == bp.CHILLED_MIN_C
    assert naive.integral < -2000.0 and guarded.integral > -30.0


def test_pid_freezes_the_integrator_while_the_rate_limit_holds_the_output_but_integrates_normally_otherwise():
    held = pid(kp=0.0, ki=0.5)
    held.setpoint(
        18.0
    )  # +4 C error: 12 + 0.5*4 = 14 C requested, but 10 C + 2 C/step = 12 C is all the actuator may do
    assert held.output == 12.0 and held.integral == 0.0  # held back and pushing deeper: not integrated
    free = pid(kp=0.0, ki=0.01, initial_setpoint_C=12.0)
    for _ in range(10):
        free.setpoint(21.0)  # +1 C error, well inside the limits: the integrator accumulates normally
    assert free.integral == pytest.approx(10.0) and free.saturated_steps == 0


def test_pid_reset_clears_the_integrator_the_derivative_memory_and_the_output():
    p = pid(ki=0.05, kd=1.0)
    for inlet in (19.0, 20.0, 25.0):
        p.setpoint(inlet)
    assert p.integral != 0.0
    first_run = [p.setpoint(x) for x in (19.0, 24.0)]
    p.reset()
    assert p.integral == 0.0 and p.output == bp.INITIAL_SETPOINT_C and p.saturated_steps == 0
    fresh = pid(ki=0.05, kd=1.0)
    assert [p.setpoint(x) for x in (19.0, 24.0)] == [fresh.setpoint(x) for x in (19.0, 24.0)]
    assert first_run != [] and p.setpoint(19.0) is not None


def test_pid_is_deterministic():
    seq = np.random.default_rng(3).uniform(15.0, 30.0, size=100)
    a, b = pid(kp=2.0, ki=0.05, kd=0.5), pid(kp=2.0, ki=0.05, kd=0.5)
    assert [a.setpoint(float(x)) for x in seq] == [b.setpoint(float(x)) for x in seq]


def test_pid_mode_rule_is_fixed_and_validated():
    from src.digital_twin import DigitalTwin

    state = {"inlet_temp": 18.0, "outside_temp": 25.0, "water_stress": 0.0}
    prod = bp.PIDPolicy(target_inlet_C=22.0, kp=1.0, ki=0.0, kd=0.0)
    mode = DigitalTwin().select_cooling_mode(25.0, 0.0).value
    assert prod.act(None, state)[1] == pytest.approx(COOLING_MODES.index(mode) / 3.0)
    assert pid(mode_rule="hybrid").act(None, state)[1] == pytest.approx(1.0)
    a = pid().act(None, state)
    assert a.dtype == np.float32 and a.shape == (2,) and 0.0 <= a[0] <= 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kp": -1.0},
        {"ki": -0.1},
        {"min_setpoint_C": 3.0},
        {"max_setpoint_C": 20.0},
        {"min_setpoint_C": 15.0, "max_setpoint_C": 10.0},
        {"max_rate_C_per_step": 0.0},
        {"mode_rule": "magic"},
    ],
)
def test_pid_rejects_parameters_outside_the_actuator_limits(kwargs):
    with pytest.raises(ValueError):
        pid(**kwargs)


# ============================================================================= run_episode hooks


class Counting:
    name = "counting"

    def __init__(self):
        self.resets = 0
        self.inner = bp.ConstantPolicy(15.0, "closed_loop")

    def reset(self):
        self.resets += 1

    def act(self, obs, state):
        return self.inner.act(obs, state)


def test_run_episode_resets_the_policy_and_reports_every_step_without_changing_the_result():
    s = pe.build_scenarios(SMALL)["validation"][0]
    plain = pe.run_episode(bp.ConstantPolicy(15.0, "closed_loop"), s, SMALL, CURVE)
    policy, seen = Counting(), []
    hooked = pe.run_episode(
        policy,
        s,
        SMALL,
        CURVE,
        on_step=lambda before, r, after: seen.append((before["utilisation"], r, after["inlet_temp"])),
    )
    assert policy.resets == 1 and len(seen) == SMALL.episode_steps
    assert hooked.metrics == plain.metrics and hooked.exogenous_hash == plain.exogenous_hash
    assert sum(r for _, r, _ in seen) == pytest.approx(plain.metrics["total_reward"])


def test_a_stateful_policy_gives_the_same_episode_twice_because_it_is_reset():
    s = pe.build_scenarios(SMALL)["validation"][0]
    p = bp.PIDPolicy(target_inlet_C=22.0, kp=1.0, ki=0.05, kd=0.5)
    assert pe.run_episode(p, s, SMALL, CURVE).metrics == pe.run_episode(p, s, SMALL, CURVE).metrics


# ============================================================================= tuners on synthetic data


def ep(reward: float, violations: int = 0, sid: str = "stress_0.0/validation/100000") -> pe.EpisodeResult:
    metrics = {m: 0.0 for m in pe.METRICS}
    metrics.update(total_reward=reward, outlet_violation_steps=float(violations))
    return pe.EpisodeResult(sid, metrics, "x")


def candidate(key, reward, feasible=True, steps=0):
    return {"key": key, "reward": reward, "feasible": feasible, "violations": {"steps": steps}}


def test_pick_takes_the_best_feasible_and_breaks_ties_lexicographically():
    cands = [
        candidate((15.0, 1), -3.0),
        candidate((5.0, 1), -3.0),
        candidate((5.0, 0), -3.0 - 1e-12),
        candidate((10.0, 2), -2.0, feasible=False),
    ]
    assert tuning.pick(cands, 1e-9)["key"] == (
        5.0,
        0,
    )  # the infeasible -2.0 never wins; ties within tolerance -> smallest key
    assert tuning.pick(cands, 0.0)["key"] == (5.0, 1)  # exact tolerance 0: the tiny difference now matters
    assert tuning.pick([candidate((1.0,), -1.0, feasible=False)], 1e-9) is None
    assert tuning.pick([], 1e-9) is None


def test_least_violating_is_information_only():
    c = [candidate((1.0,), -1.0, False, 9), candidate((2.0,), -5.0, False, 3), candidate((3.0,), -4.0, False, 3)]
    assert tuning.least_violating(c)["key"] == (3.0,)


class FakeSweep:
    """Per-step data built from explicit (reward, violation) tables so the expected table is known."""

    def __init__(self, rewards, violations, cell_layout, n_scenarios=2):
        self.rewards, self.violations, self.layout, self.n = rewards, violations, cell_layout, n_scenarios
        self.calls = []

    def get(self, chilled_C, mode):
        self.calls.append((chilled_C, mode))
        steps = np.zeros((self.n, len(self.layout), 4))
        for t, (util, temp, cell) in enumerate(self.layout):
            steps[:, t, 0], steps[:, t, 1] = util, temp
            steps[:, t, 2] = self.rewards[(chilled_C, mode)][cell]
            steps[:, t, 3] = self.violations.get((chilled_C, mode), {}).get(cell, 0)
        results = [ep(float(steps[s, :, 2].sum()), int(steps[s, :, 3].sum())) for s in range(self.n)]
        return results, steps


def _lookup_fixture():
    # 2 util bins (edge 0.5) x 2 temp bins (edge 20): cells (0,0) (0,1) (1,0) (1,1)
    layout = [
        (0.2, 10.0, "00"),
        (0.2, 10.0, "00"),
        (0.2, 25.0, "01"),
        (0.2, 25.0, "01"),
        (0.8, 10.0, "10"),
        (0.8, 10.0, "10"),
        (0.8, 25.0, "11"),
        (0.2, 10.0, "00"),
    ]
    acts = [(5.0, "closed_loop"), (5.0, "hybrid"), (15.0, "closed_loop"), (15.0, "hybrid")]
    rewards = {a: {"00": -10.0, "01": -9.0, "10": -9.0, "11": -9.0} for a in acts}
    rewards[(15.0, "hybrid")]["00"] = -5.0  # cell 00: a unique winner
    rewards[(5.0, "closed_loop")]["01"] = rewards[(15.0, "closed_loop")]["01"] = -3.0  # cell 01: an exact tie
    rewards[(15.0, "closed_loop")]["10"] = -1.0  # cell 10: the best reward ...
    rewards[(5.0, "hybrid")]["10"] = -4.0
    violations = {(15.0, "closed_loop"): {"10": 1}}  # ... but it violates the envelope, so it must lose
    return FakeSweep(rewards, violations, layout), acts


def _lookup_space(**kw):
    space = tuning.default_space(SMALL)
    return replace(
        space,
        lookup_util_edges=(0.5,),
        lookup_temp_edges=(20.0,),
        lookup_chilled_C=(5.0, 15.0),
        lookup_modes=("closed_loop", "hybrid"),
        lookup_min_cell_samples=3,
        lookup_transient_steps_excluded=0,
        **kw,
    )


def test_lookup_picks_the_best_feasible_action_per_cell_with_lexicographic_ties_and_a_fallback(monkeypatch):
    sweep, _ = _lookup_fixture()
    monkeypatch.setattr(pe, "evaluate_policy", lambda policy, scenarios, cfg, carbon: [ep(-7.0)])
    val = pe.build_scenarios(SMALL)["validation"]
    out = tuning.tune_lookup(_lookup_space(), sweep, val, SMALL, CURVE)
    t = out["parameters"]["table"]
    cell = lambda i, j: (t[i][j]["chilled_C"], t[i][j]["mode"], t[i][j]["source"])  # noqa: E731
    assert cell(0, 0) == (15.0, "hybrid", "table")  # unique best
    assert cell(0, 1) == (5.0, "closed_loop", "table")  # exact tie -> (chilled_C, mode index) ascending
    assert cell(1, 0) == (5.0, "hybrid", "table")  # the better-rewarded (15, closed_loop) violates the envelope
    assert t[1][1]["source"] == "fallback" and t[1][1]["n"] == 2  # too few validation steps (min 3)
    assert out["status"] == "feasible" and out["result"]["fallback_cells"] == 1
    assert out["parameters"]["fallback"]["chilled_C"] in (5.0, 15.0)


def test_lookup_fallback_is_the_best_feasible_constant_over_the_lookup_grid(monkeypatch):
    sweep, acts = _lookup_fixture()
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: [ep(-7.0)])
    out = tuning.tune_lookup(_lookup_space(), sweep, pe.build_scenarios(SMALL)["validation"], SMALL, CURVE)
    totals = {a: sum(sweep.rewards[a][cell] for _, _, cell in sweep.layout) for a in acts}
    feasible = {a: v for a, v in totals.items() if sweep.violations.get(a, {}) == {}}
    best = max(feasible.items(), key=lambda kv: (kv[1], (-kv[0][0], -COOLING_MODES.index(kv[0][1]))))[0]
    assert (out["parameters"]["fallback"]["chilled_C"], out["parameters"]["fallback"]["mode"]) == best


def test_lookup_is_infeasible_when_the_closed_loop_run_violates_the_envelope(monkeypatch):
    sweep, _ = _lookup_fixture()
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: [ep(-7.0, violations=4)])
    out = tuning.tune_lookup(_lookup_space(), sweep, pe.build_scenarios(SMALL)["validation"], SMALL, CURVE)
    assert (
        out["status"] == "infeasible"
        and "closed-loop" in out["reason"]
        and out["result"]["validation_violation_steps"]["outlet_violation_steps"] == 4
    )


def test_a_cell_where_every_action_violates_is_reported_not_hidden(monkeypatch):
    sweep, acts = _lookup_fixture()
    sweep.violations = {a: {"00": 1} for a in acts}
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: [ep(-7.0)])
    out = tuning.tune_lookup(_lookup_space(), sweep, pe.build_scenarios(SMALL)["validation"], SMALL, CURVE)
    assert (
        out["parameters"]["table"][0][0]["source"] == "least_violating" and out["result"]["least_violating_cells"] == 1
    )


def test_lookup_tuning_uses_only_the_sweep_it_is_given(monkeypatch):
    sweep, acts = _lookup_fixture()
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: [ep(-7.0)])
    tuning.tune_lookup(_lookup_space(), sweep, pe.build_scenarios(SMALL)["validation"], SMALL, CURVE)
    assert set(sweep.calls) == set(acts)  # the exhaustive grid, nothing else


def test_constant_tuning_never_loosens_the_envelope():
    sweep = FakeSweep(
        {(c, m): {"a": -float(i)} for i, (c, m) in enumerate([(5.0, "closed_loop"), (15.0, "closed_loop")])},
        {(5.0, "closed_loop"): {"a": 1}, (15.0, "closed_loop"): {"a": 1}},
        [(0.2, 10.0, "a")] * 4,
    )
    space = replace(tuning.default_space(SMALL), constant_chilled_C=(5.0, 15.0), constant_modes=("closed_loop",))
    out = tuning.tune_constant(space, sweep)
    assert (
        out["status"] == "infeasible"
        and out["parameters"]["selected"] is None
        and out["result"]["validation_reward"] is None
    )
    assert "fewest violations" in out["reason"] and out["result"]["least_violating"]["feasible"] is False
    assert all(c["feasible"] is False for c in out["result"]["candidates"])


def test_constant_tuning_ties_go_to_the_smallest_setpoint_then_mode_index():
    rewards = {(c, m): {"a": -4.0} for c in (5.0, 15.0) for m in ("closed_loop", "hybrid")}
    sweep = FakeSweep(rewards, {}, [(0.2, 10.0, "a")] * 4)
    space = replace(
        tuning.default_space(SMALL), constant_chilled_C=(15.0, 5.0), constant_modes=("hybrid", "closed_loop")
    )
    out = tuning.tune_constant(space, sweep)
    assert out["parameters"]["selected"] == {"chilled_C": 5.0, "mode": "closed_loop"}  # independent of grid order


def _fake_pid_eval(rewards_by_gain, violating=()):
    def fake(policy, scenarios, cfg, carbon):
        key = (policy.kp, policy.ki, policy.kd)
        return [ep(rewards_by_gain.get(key, -50.0), violations=1 if key in violating else 0)]

    return fake


def test_pid_grid_is_searched_deterministically_with_lexicographic_ties(monkeypatch):
    space = replace(tuning.default_space(SMALL), pid_kp=(2.0, 0.0, 1.0), pid_ki=(0.05, 0.0), pid_kd=(0.0,))
    val = pe.build_scenarios(SMALL)["validation"]
    monkeypatch.setattr(pe, "evaluate_policy", _fake_pid_eval({}))  # everything ties
    tied = tuning.tune_pid(space, val, SMALL, CURVE)
    assert tied["parameters"]["selected_gains"] == {"kp": 0.0, "ki": 0.0, "kd": 0.0}
    assert len(tied["result"]["candidates"]) == 6
    monkeypatch.setattr(pe, "evaluate_policy", _fake_pid_eval({(1.0, 0.05, 0.0): -10.0, (2.0, 0.0, 0.0): -10.0}))
    best = tuning.tune_pid(space, val, SMALL, CURVE)
    assert best["parameters"]["selected_gains"] == {
        "kp": 1.0,
        "ki": 0.05,
        "kd": 0.0,
    }  # tie between two -> lexicographically smaller
    monkeypatch.setattr(pe, "evaluate_policy", _fake_pid_eval({(1.0, 0.05, 0.0): -1.0}, violating={(1.0, 0.05, 0.0)}))
    assert tuning.tune_pid(space, val, SMALL, CURVE)["parameters"]["selected_gains"] != {
        "kp": 1.0,
        "ki": 0.05,
        "kd": 0.0,
    }  # a violating set never wins


def test_pid_is_infeasible_when_no_gain_set_satisfies_the_envelope(monkeypatch):
    space = replace(tuning.default_space(SMALL), pid_kp=(0.0, 1.0), pid_ki=(0.0,), pid_kd=(0.0,))
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: [ep(-5.0, violations=2)])
    out = tuning.tune_pid(space, pe.build_scenarios(SMALL)["validation"], SMALL, CURVE)
    assert (
        out["status"] == "infeasible"
        and out["parameters"]["selected_gains"] is None
        and "no PID gain set" in out["reason"]
    )
    cfg = bcfg.make_config(
        "pid",
        parameters=out["parameters"],
        tuning=_tuning_block(out),
        status=out["status"],
        infeasible_reason=out["reason"],
        tuner_version=tuning.TUNER_VERSION,
    )
    with pytest.raises(bcfg.BaselineConfigError, match="infeasible"):
        bcfg.build_policy(cfg)


def test_the_rule_is_checked_against_the_envelope_but_not_tuned(monkeypatch):
    val = pe.build_scenarios(SMALL)["validation"]
    ok = tuning.tune_rule(tuning.default_space(SMALL), val, SMALL, CURVE)
    assert (
        ok["status"] == "feasible"
        and ok["result"]["tuned"] is False
        and ok["parameters"]["mode_rule"] == "production_rule"
    )
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: [ep(-1.0, violations=3)])
    bad = tuning.tune_rule(tuning.default_space(SMALL), val, SMALL, CURVE)
    assert bad["status"] == "infeasible" and "violates the envelope" in bad["reason"]


def _tuning_block(out, val=None):
    val = val or pe.build_scenarios(SMALL)["validation"]
    return {
        "scenario_set_id": pe.scenario_set_id(val),
        "scenario_ids": [s.scenario_id for s in val],
        "eval_config_sha256": pe.config_sha256(SMALL),
        "objective": tuning.OBJECTIVE,
        "feasibility_rule": tuning.FEASIBILITY_RULE,
        "carbon": {"is_real": False, "flat_curve": True, "curve_sha256": tuning.curve_sha256(CURVE)},
        "search_space": out["search_space"],
        "result": out["result"],
    }


# ============================================================================= tuning reads validation scenarios only


def test_tuners_refuse_test_scenarios():
    test = pe.build_scenarios(SMALL)["test"]
    with pytest.raises(tuning.TuningLeak):
        tuning.assert_validation_only(test)
    with pytest.raises(tuning.TuningLeak):
        tuning.assert_validation_only(pe.build_scenarios(SMALL)["validation"] + test[:1])
    with pytest.raises(tuning.TuningLeak):
        tuning.tune_rule(tuning.default_space(SMALL), test, SMALL, CURVE)
    with pytest.raises(tuning.TuningLeak):
        tuning.ActionSweep(test, SMALL, CURVE)
    with pytest.raises(tuning.TuningLeak):
        tuning.tune_all(SMALL, test, CURVE, carbon_is_real=False)
    with pytest.raises(ValueError):
        tuning.assert_validation_only([])


def test_tuner_spy_proves_no_test_scenario_id_is_read():
    val, test = pe.build_scenarios(SMALL)["validation"], pe.build_scenarios(SMALL)["test"]
    seen = []
    real = pe.run_episode

    def spy(policy, scenario, cfg, carbon, on_step=None):
        seen.append(scenario.scenario_id)
        return real(policy, scenario, cfg, carbon, on_step=on_step)

    pe.run_episode = spy
    try:
        space = replace(tuning.default_space(SMALL), pid_kp=(0.0, 1.0), pid_ki=(0.0,), pid_kd=(0.0,))
        tuning.tune_all(SMALL, val, CURVE, carbon_is_real=False, space=space)
    finally:
        pe.run_episode = real
    assert seen and set(seen) == {s.scenario_id for s in val}  # exactly the validation scenarios ...
    assert not set(seen) & {s.scenario_id for s in test} and not any("/test/" in i for i in seen)  # ... and no test id


def test_the_tune_command_hands_the_tuners_only_the_validation_split(tmp_path, monkeypatch):
    from src.baselines import cli

    (tmp_path / "reports/policy_evaluation").mkdir(parents=True)
    pe.write_preregistration(SMALL, tmp_path / "reports/policy_evaluation")
    captured = {}

    class Stop(Exception):
        pass

    def fake_tune_all(eval_cfg, validation, carbon, **kw):
        captured["ids"] = [s.scenario_id for s in validation]
        raise Stop

    monkeypatch.setattr(tuning, "tune_all", fake_tune_all)
    with pytest.raises(Stop):
        cli.cmd_tune(type("A", (), {"out": "configs/baselines"})(), tmp_path)
    assert captured["ids"] and all("/validation/" in i for i in captured["ids"])


def test_tuning_modules_never_build_or_name_the_test_split():
    for name in ("tuning.py", "policies.py", "config.py"):
        source = (ROOT / "src/baselines" / name).read_text()
        assert "build_scenarios" not in source and '"test"' not in source.replace('"/test/" in', "").replace(
            "/test/", ""
        ).replace('"/test/"', "")


# ============================================================================= configs


def _config(name="constant", status="feasible", **kw):
    out = {
        "parameters": {"selected": {"chilled_C": 15.0, "mode": "closed_loop"}},
        "result": {"validation_reward": -1.0},
        "search_space": {},
    }
    return bcfg.make_config(
        name,
        parameters=kw.get("parameters", out["parameters"]),
        tuning=_tuning_block(out),
        status=status,
        infeasible_reason=None if status == "feasible" else "because",
        tuner_version=tuning.TUNER_VERSION,
    )


def test_config_round_trip_is_canonical_and_validated(tmp_path):
    cfg = _config()
    sha = bcfg.write_config(cfg, tmp_path / "constant.json")
    assert (tmp_path / "constant.json").read_bytes() == canonical.canonical_bytes(cfg)
    assert sha == canonical.sha256_input_file(tmp_path / "constant.json")
    assert bcfg.load_config(tmp_path / "constant.json", "constant") == cfg
    assert cfg["tuning"]["split"] == "validation" and cfg["tuner_version"] == tuning.TUNER_VERSION
    with pytest.raises(bcfg.BaselineConfigError):
        bcfg.load_config(tmp_path / "constant.json", "pid")
    with pytest.raises(bcfg.BaselineConfigError, match="not found"):
        bcfg.load_config(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(bcfg.BaselineConfigError):
        bcfg.load_config(tmp_path / "bad.json")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["tuning"].update(split="test"),
        lambda c: c["tuning"]["scenario_ids"].append("stress_0.0/test/200000"),
        lambda c: c["tuning"].update(scenario_ids=[]),
        lambda c: c.update(status="infeasible", infeasible_reason=None),
        lambda c: c.update(status="maybe"),
        lambda c: c.update(name="mpc"),
        lambda c: c.update(tuner_version=""),
        lambda c: c["lineage"].pop("reward_version"),
        lambda c: c["tuning"].pop("carbon"),
        lambda c: c.update(schema="other"),
    ],
)
def test_malformed_configs_are_rejected(mutate):
    cfg = json.loads(json.dumps(_config()))
    mutate(cfg)
    with pytest.raises(bcfg.BaselineConfigError):
        bcfg.validate(cfg)


def test_there_is_no_mpc_baseline():
    assert bcfg.BASELINE_NAMES == ("rule", "constant", "lookup", "pid")
    assert not (ROOT / "src/baselines/mpc.py").exists()
    with pytest.raises(bcfg.BaselineConfigError, match="unknown baseline"):
        bcfg.config_path("mpc", ROOT)


@pytest.mark.parametrize("field", list(versions.COMPAT_FIELDS))
def test_a_config_tuned_against_other_versions_is_stale_and_names_the_field(field):
    cfg = _config()
    bcfg.check_lineage(cfg)
    current = cfg["lineage"][field]
    cfg["lineage"][field] = current + 1 if isinstance(current, int) else f"{current}-old"
    with pytest.raises(bcfg.BaselineConfigStale) as exc:
        bcfg.check_lineage(cfg)
    assert exc.value.field == f"lineage.{field}"


def test_changing_a_version_constant_makes_every_existing_config_stale(monkeypatch):
    cfg = _config()
    monkeypatch.setattr(versions, "ENV_VERSION", "2")
    with pytest.raises(bcfg.BaselineConfigStale, match="environment_version"):
        bcfg.check_lineage(cfg)


def test_a_config_must_have_been_tuned_on_exactly_these_scenarios_config_and_carbon():
    cfg, val = _config(), pe.build_scenarios(SMALL)["validation"]
    ids, set_id, sha, carbon = (
        [s.scenario_id for s in val],
        pe.scenario_set_id(val),
        pe.config_sha256(SMALL),
        tuning.curve_sha256(CURVE),
    )
    bcfg.check_tuning_scenarios(cfg, ids, set_id, sha, carbon)
    for args, field in (
        ((ids[:-1], set_id, sha, carbon), "tuning.scenario_ids"),
        ((ids, "0" * 16, sha, carbon), "tuning.scenario_set_id"),
        ((ids, set_id, "0" * 64, carbon), "tuning.eval_config_sha256"),
        ((ids, set_id, sha, "0" * 64), "tuning.carbon.curve_sha256"),
    ):
        with pytest.raises(bcfg.BaselineConfigStale) as exc:
            bcfg.check_tuning_scenarios(cfg, *args)
        assert exc.value.field == field


def test_build_policy_is_a_pure_function_of_the_config():
    constant = bcfg.build_policy(_config())
    assert isinstance(constant, bp.ConstantPolicy) and (constant.chilled_C, constant.mode) == (15.0, "closed_loop")
    a, b = bcfg.build_policy(_config()), bcfg.build_policy(json.loads(json.dumps(_config())))
    assert np.array_equal(a.act(None, {}), b.act(None, {}))
    with pytest.raises(bcfg.BaselineConfigError, match="missing"):
        bcfg.build_policy(_config(parameters={}))


# ============================================================================= integration: tune, run through T24, verify

_CACHE: dict[str, Path] = {}


def _built_world() -> Path:
    """Tune + write configs once per test session, in a scratch project root."""
    if "root" not in _CACHE:
        root = Path(tempfile.mkdtemp())
        (root / "reports/policy_evaluation").mkdir(parents=True)
        pe.write_preregistration(SMALL, root / "reports/policy_evaluation")
        curve, is_real = pe.load_diurnal_carbon_intensity()
        space = replace(tuning.default_space(SMALL), pid_kp=(0.0, 1.0), pid_ki=(0.0, 0.05), pid_kd=(0.0,))
        configs = tuning.tune_all(
            SMALL, pe.build_scenarios(SMALL)["validation"], np.asarray(curve), carbon_is_real=is_real, space=space
        )
        for name, cfg in configs.items():
            bcfg.write_config(cfg, root / "configs/baselines" / f"{name}.json")
        (root / "configs/baselines/evaluation.json").write_bytes(
            canonical.canonical_bytes(evaluation.evaluation_document(SMALL, prereg=PREREG))
        )
        _CACHE["root"] = root
    return _CACHE["root"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "root"
    shutil.copytree(_built_world(), root)
    monkeypatch.setenv("GIT_SHA", "a" * 40)
    monkeypatch.delenv("GIT_DIRTY", raising=False)
    evaluation.register(root)
    yield root
    experiments._REGISTRY.pop("baselines", None)


def request(run_id="r1", **kw):
    d = "configs/baselines"
    return RunRequest(
        experiment="baselines",
        config_paths=[f"{d}/evaluation.json", *[f"{d}/{n}.json" for n in bcfg.BASELINE_NAMES]],
        prereg=PREREG,
        run_id=run_id,
        **kw,
    )


def test_tuned_configs_describe_four_validation_tuned_baselines(world):
    val = pe.build_scenarios(SMALL)["validation"]
    for name in bcfg.BASELINE_NAMES:
        cfg = bcfg.load_config(world / "configs/baselines" / f"{name}.json", name)
        assert cfg["tuning"]["scenario_ids"] == [s.scenario_id for s in val] and cfg["status"] in bcfg.STATUSES
        bcfg.check_lineage(cfg)
        assert bcfg.build_policy(cfg).name


def test_same_config_gives_byte_identical_results(world):
    a, b = run(request("a"), world), run(request("b"), world)
    assert a.state == b.state == "completed", (a.error, b.error)
    assert (a.run_dir / "results.json").read_bytes() == (b.run_dir / "results.json").read_bytes()
    assert (a.run_dir / "REPORT.md").read_bytes() == (b.run_dir / "REPORT.md").read_bytes()


def test_baselines_only_run_through_t24_reproduces_on_rerun_and_the_report_lists_all_four(world):
    outcome = run(request("full", check_determinism=True), world)
    assert outcome.state == "completed", outcome.error
    rep = verify_run(world, "full", rerun=True)
    assert rep.failures == [], [str(f) for f in rep.failures]
    results = read_json(outcome.run_dir / "results.json")
    text = (outcome.run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert [r[0] for r in results["tables"]["baselines"]["rows"]] == ["rule", "constant", "lookup", "pid"]
    assert [r[0] for r in results["tables"]["test_summary"]["rows"]] == ["rule", "constant", "lookup", "pid"]
    for name in bcfg.BASELINE_NAMES:
        assert f"| {name} |" in text
    assert report.check_report_numbers(text, results) == []
    assert (
        results["claims"]["allowed"] == evaluation.CLAIM_ALLOWED
        and "optimal" in results["claims"]["not_allowed"].lower()
    )


def test_manifest_hashes_all_five_configs_and_the_preregistration(world):
    outcome = run(request("hash"), world)
    m = read_json(outcome.run_dir / "manifest.json")
    assert set(m["config_files"]) == {f"configs/baselines/{n}.json" for n in (*bcfg.BASELINE_NAMES, "evaluation")}
    for rel, sha in m["config_files"].items():
        assert sha == canonical.sha256_input_file(world / rel)
    assert m["prereg_sha256"] == canonical.sha256_input_file(world / PREREG) and m["experiment"] == "baselines"
    test = pe.build_scenarios(SMALL)["test"]
    assert (
        m["seeds"] == sorted({s.seed for s in test}) and m["scenario_set_id"] is None
    )  # set by the CLI, not by this helper


def test_editing_a_baseline_config_after_the_run_fails_verify_naming_it(world):
    outcome = run(request("edit"), world)
    path = world / "configs/baselines/pid.json"
    cfg = json.loads(path.read_text())
    cfg["parameters"]["target_inlet_C"] = 25.0
    path.write_text(json.dumps(cfg))
    rep = verify_run(world, "edit")
    assert [f.field for f in rep.failures] == [
        "config_files[configs/baselines/pid.json]"
    ] and outcome.state == "completed"


def test_scenario_input_hash_is_identical_across_policies(world):
    results = read_json(run(request("hash2"), world).run_dir / "results.json")
    hashes = results["scenario_input_hash_by_policy"]
    assert set(hashes) == set(bcfg.BASELINE_NAMES) and len(set(hashes.values())) == 1
    assert results["scenario_input_hash"] == next(iter(hashes.values()))


def test_a_policy_facing_different_scenarios_is_caught(world, monkeypatch):
    real = pe.evaluate_policy

    def tampered(policy, scenarios, cfg, carbon):
        out = real(policy, scenarios, cfg, carbon)
        if getattr(policy, "name", "") == "lookup":
            out[0] = pe.EpisodeResult(out[0].scenario_id, out[0].metrics, "deadbeef")
        return out

    monkeypatch.setattr(pe, "evaluate_policy", tampered)
    outcome = run(request("tamper"), world)
    assert outcome.state == "failed" and "exogenous trace differs" in outcome.error


def test_evaluation_runs_on_test_scenarios_and_tuning_ran_on_validation_scenarios(world):
    seen = []
    real = pe.run_episode
    pe.run_episode = lambda policy, scenario, *a, **k: (
        seen.append(scenario.scenario_id),
        real(policy, scenario, *a, **k),
    )[1]
    try:
        outcome = run(request("split"), world)
    finally:
        pe.run_episode = real
    sc = pe.build_scenarios(SMALL)
    assert outcome.state == "completed" and set(seen) == {s.scenario_id for s in sc["test"]}
    assert not set(seen) & {s.scenario_id for s in sc["validation"]}
    cfgs = [bcfg.load_config(world / "configs/baselines" / f"{n}.json", n) for n in bcfg.BASELINE_NAMES]
    assert all(set(c["tuning"]["scenario_ids"]) == {s.scenario_id for s in sc["validation"]} for c in cfgs)
    with pytest.raises(evaluation.BaselineRunError, match="test scenarios only"):
        evaluation.evaluate_baselines(
            SMALL, {n: c for n, c in zip(bcfg.BASELINE_NAMES, cfgs)}, sc["validation"], CURVE, {}, sc["validation"]
        )


def test_a_stale_config_fails_the_run_instead_of_comparing_against_the_wrong_environment(world, monkeypatch):
    monkeypatch.setattr(versions, "REWARD_VERSION", "2")
    outcome = run(request("stale"), world)
    assert outcome.state == "failed" and "BaselineConfigStale" in outcome.error and "reward_version" in outcome.error


def test_a_config_tuned_on_other_validation_scenarios_fails_the_run(world):
    path = world / "configs/baselines/rule.json"
    cfg = json.loads(path.read_text())
    cfg["tuning"]["scenario_ids"] = cfg["tuning"]["scenario_ids"][:-1]
    path.write_text(canonical.canonical_dumps(cfg))
    outcome = run(request("othersc"), world)
    assert outcome.state == "failed" and "tuning.scenario_ids" in outcome.error


def test_an_infeasible_baseline_is_reported_and_not_evaluated(world):
    path = world / "configs/baselines/constant.json"
    cfg = json.loads(path.read_text())
    cfg.update(status="infeasible", infeasible_reason="no grid action satisfies the envelope on validation")
    cfg["parameters"]["selected"] = None
    path.write_text(canonical.canonical_dumps(cfg))
    evaluated = []
    real = pe.evaluate_policy
    pe.evaluate_policy = lambda policy, *a, **k: (evaluated.append(policy.name), real(policy, *a, **k))[1]
    try:
        outcome = run(request("infeasible"), world)
    finally:
        pe.evaluate_policy = real
    assert outcome.state == "completed", outcome.error
    results = read_json(outcome.run_dir / "results.json")
    assert [r[0] for r in results["tables"]["test_summary"]["rows"]] == ["rule", "lookup", "pid"]
    row = next(r for r in results["tables"]["baselines"]["rows"] if r[0] == "constant")
    assert row[1] == "infeasible" and "INFEASIBLE" in row[4] and results["summary"]["baselines_infeasible"] == 1
    assert "best_constant" not in evaluated and not any("constant" in n for n in evaluated)
    assert any("constant is infeasible on validation" in n for n in results["notes"])
    assert "| constant |" in (outcome.run_dir / "REPORT.md").read_text()  # still listed


def test_the_run_refuses_seeds_that_are_not_the_registered_test_seeds(world):
    outcome = run(request("badseed", seeds=[1, 2, 3]), world)
    assert outcome.state == "failed" and "test-scenario seeds" in outcome.error


def test_the_run_refuses_a_modified_preregistration(world):
    path = world / PREREG
    doc = json.loads(path.read_text())
    doc["config"]["alpha"] = 0.9
    path.write_text(json.dumps(doc))
    outcome = run(request("prereg"), world)
    assert outcome.state == "failed" and "hash mismatch" in outcome.error


# ============================================================================= static rules


def test_baselines_use_no_global_random_state():
    banned = {
        "seed",
        "RandomState",
        "rand",
        "randn",
        "randint",
        "random",
        "shuffle",
        "choice",
        "normal",
        "uniform",
        "permutation",
    }
    offenders = []
    for path in sorted((ROOT / "src/baselines").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in banned:
                chain, cur = [node.attr], node.value
                while isinstance(cur, ast.Attribute):
                    chain.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    chain.append(cur.id)
                dotted = ".".join(reversed(chain))
                if dotted.startswith(("np.random", "numpy.random", "random.")):
                    offenders.append((path.name, dotted))
    assert offenders == []


def test_baselines_do_not_read_the_clock_or_the_environment():
    for name in ("policies.py", "tuning.py", "evaluation.py", "config.py"):
        source = (ROOT / "src/baselines" / name).read_text()
        assert not any(w in source for w in ("datetime", "time.time", "perf_counter", "os.environ", "getenv"))


# ============================================================================= the shipped configs and run


def _shipped_context():
    eval_cfg = pe.load_preregistered_config((ROOT / PREREG).parent)
    return eval_cfg, pe.build_scenarios(eval_cfg)


def test_shipped_configs_are_valid_current_and_tuned_on_the_registered_validation_scenarios():
    eval_cfg, sc = _shipped_context()
    val = sc["validation"]
    curve, _ = pe.load_diurnal_carbon_intensity()
    for name in bcfg.BASELINE_NAMES:
        path = ROOT / "configs/baselines" / f"{name}.json"
        assert path.read_bytes() == canonical.canonical_bytes(
            json.loads(path.read_text())
        ), "configs must be canonical JSON"
        cfg = bcfg.load_config(path, name)
        bcfg.check_lineage(cfg)
        bcfg.check_tuning_scenarios(
            cfg,
            [s.scenario_id for s in val],
            pe.scenario_set_id(val),
            pe.config_sha256(eval_cfg),
            tuning.curve_sha256(np.asarray(curve)),
        )
        assert cfg["tuner_version"] == tuning.TUNER_VERSION and cfg["tuning"]["split"] == "validation"
        assert not any("/test/" in i for i in cfg["tuning"]["scenario_ids"])
    doc = json.loads((ROOT / "configs/baselines/evaluation.json").read_text())
    assert doc == evaluation.evaluation_document(eval_cfg)


def test_shipped_baselines_run_verifies_and_lists_all_four():
    run_dir = ROOT / "reports/runs/baselines-v2"
    assert run_dir.is_dir()
    rep = verify_run(ROOT, "baselines-v2")
    assert rep.failures == [], [str(f) for f in rep.failures]
    results = read_json(run_dir / "results.json")
    assert [r[0] for r in results["tables"]["baselines"]["rows"]] == list(bcfg.BASELINE_NAMES)
    text = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert all(f"| {n} |" in text for n in bcfg.BASELINE_NAMES)
    m = read_json(run_dir / "manifest.json")
    assert set(m["config_files"]) == {f"configs/baselines/{n}.json" for n in (*bcfg.BASELINE_NAMES, "evaluation")}
    assert m["prereg_sha256"] == canonical.sha256_input_file(ROOT / PREREG)


def _close(a, b, rel=1e-6):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], rel) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_close(x, y, rel) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= rel * max(1.0, abs(a), abs(b))
    return a == b


def test_shipped_baselines_run_reproduces_on_rerun():
    """Level L1 (same machine/environment) is byte-identical; on another platform only numeric agreement is claimed (L2)."""
    from src.repro import env

    m = read_json(ROOT / "reports/runs/baselines-v2/manifest.json")
    evaluation.register(ROOT)
    try:
        cfg = read_json(ROOT / m["primary_config"])
        again = __import__("src.repro.run", fromlist=["execute_experiment"]).execute_experiment(
            "baselines", cfg, m["seeds"], digits=m["determinism"]["float_sig_digits"]
        )
    finally:
        experiments._REGISTRY.pop("baselines", None)
    shipped_bytes = (ROOT / "reports/runs/baselines-v2/results.json").read_bytes()
    now = env.platform_info()
    same_environment = all(m["platform"][k] == now[k] for k in ("os", "arch", "python", "numpy"))
    if same_environment:
        assert canonical.canonical_bytes(again) == shipped_bytes.replace(b"\r\n", b"\n")
    assert _close(json.loads(canonical.canonical_dumps(again)), json.loads(shipped_bytes))
