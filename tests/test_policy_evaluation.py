"""T8: harness unit tests -- scenario identity, seed disjointness, CI arithmetic, outcome rules,
pre-registration integrity, reproducibility. No PPO/torch needed: candidates are stand-in policies."""

from __future__ import annotations

import json
import math
from dataclasses import replace

import numpy as np
import pytest

from src import policy_evaluation as pe
from src.optimizer import COOLING_MODES, JointOptimizer

CFG = pe.EvalConfig()
SMALL = replace(CFG, n_validation_per_family=2, n_test_per_family=3, constant_chilled_C=(10.0, 15.0))
CURVE = np.full(24, 475.0)


# --------------------------------------------------------------------------- Student-t arithmetic
@pytest.mark.parametrize(
    "df,expected",
    [
        (1, 12.7062047362),
        (2, 4.30265272975),
        (4, 2.77644510520),
        (9, 2.26215716280),
        (19, 2.09302405441),
        (29, 2.04522964213),
        (120, 1.97993040),
    ],
)
def test_t_critical_matches_published_values(df, expected):
    assert pe.t_critical(df, 0.95) == pytest.approx(expected, abs=1e-6)


def test_t_critical_is_not_1_96_for_small_samples():
    assert pe.t_critical(4) > 2.7  # 5 seeds -> df=4: using 1.96 would understate the CI by ~30%


def test_t_matches_scipy_when_available():
    stats = pytest.importorskip("scipy.stats")
    for df in (1, 3, 7, 15, 40):
        for conf in (0.9, 0.95, 0.99):
            assert pe.t_critical(df, conf) == pytest.approx(stats.t.ppf(1 - (1 - conf) / 2, df), abs=1e-8)


def test_t_cdf_symmetry_and_median():
    assert pe.t_cdf(0.0, 5) == pytest.approx(0.5)
    assert pe.t_cdf(1.3, 7) + pe.t_cdf(-1.3, 7) == pytest.approx(1.0)
    assert pe.t_ppf(0.25, 6) == pytest.approx(-pe.t_ppf(0.75, 6))


def test_paired_difference_known_example():
    a = [10.0, 12.0, 11.0, 15.0, 13.0]
    b = [9.0, 10.0, 11.5, 12.0, 11.0]
    r = pe.paired_difference(a, b)
    d = np.array(a) - np.array(b)
    assert r["n"] == 5 and r["df"] == 4
    assert r["mean"] == pytest.approx(d.mean()) and r["sd"] == pytest.approx(d.std(ddof=1))
    half = 2.7764451052 * d.std(ddof=1) / math.sqrt(5)
    assert r["ci_low"] == pytest.approx(d.mean() - half, abs=1e-6)
    assert r["ci_high"] == pytest.approx(d.mean() + half, abs=1e-6)


def test_paired_difference_is_paired_not_independent():
    base = np.array([100.0, 200.0, 300.0, 400.0, 500.0])
    r = pe.paired_difference(base + 1.0, base)  # perfectly consistent +1 despite huge between-unit spread
    assert r["mean"] == pytest.approx(1.0) and r["sd"] == pytest.approx(0.0, abs=1e-12)
    assert r["ci_low"] == pytest.approx(1.0) and r["ci_high"] == pytest.approx(1.0)


def test_paired_difference_validation():
    with pytest.raises(ValueError):
        pe.paired_difference([1.0], [2.0])
    with pytest.raises(ValueError):
        pe.paired_difference([1.0, 2.0], [1.0])


# --------------------------------------------------------------------------- seeds / scenarios
def test_default_config_has_at_least_five_training_seeds_and_passes_disjointness():
    assert len(set(CFG.training_seeds)) >= 5
    pe.assert_disjoint(CFG)


def test_seeds_are_pairwise_disjoint_and_outside_the_training_range():
    sc = pe.build_scenarios(CFG)
    val, test = {s.seed for s in sc["validation"]}, {s.seed for s in sc["test"]}
    assert not (val & test) and not (set(CFG.training_seeds) & (val | test))
    lo, hi = CFG.training_seed_reserved
    assert all(not lo <= s <= hi for s in val | test)


def test_fewer_than_five_training_seeds_is_rejected():
    with pytest.raises(ValueError, match=">= 5"):
        pe.assert_disjoint(replace(CFG, training_seeds=(0, 1, 2)))


def test_overlapping_validation_and_test_seeds_are_rejected():
    with pytest.raises(ValueError, match="disjoint"):
        pe.assert_disjoint(replace(CFG, test_seed_start=CFG.validation_seed_start + 1))


def test_evaluation_seed_inside_training_range_is_rejected():
    with pytest.raises(ValueError):
        pe.assert_disjoint(replace(CFG, validation_seed_start=50))


def test_a_held_out_family_is_required():
    fams = tuple(replace(f, seen_in_training=True) for f in CFG.families)
    with pytest.raises(ValueError, match="held-out"):
        pe.assert_disjoint(replace(CFG, families=fams))


def test_scenario_sets_are_deterministic_and_have_stable_ids():
    a, b = pe.build_scenarios(CFG), pe.build_scenarios(CFG)
    assert a == b
    assert pe.scenario_set_id(a["test"]) == pe.scenario_set_id(b["test"])
    assert pe.scenario_set_id(a["test"]) != pe.scenario_set_id(a["validation"])
    assert len(a["test"]) == CFG.n_test_per_family * len(CFG.families)


def test_training_covers_only_the_in_distribution_family():
    assert [f.name for f in CFG.families if f.seen_in_training] == ["stress_0.0"]


# --------------------------------------------------------------------------- identical scenarios
def test_every_policy_sees_the_same_exogenous_trace():
    sc = pe.build_scenarios(SMALL)["test"]
    pols = [
        pe.RulePolicy(),
        pe.ConstantPolicy(5.0, "free_air"),
        pe.ConstantPolicy(15.0, "closed_loop"),
        pe.ConstantPolicy(10.0, "hybrid"),
    ]
    by = {p.name: pe.evaluate_policy(p, sc, SMALL, CURVE) for p in pols}
    pe.assert_identical_scenarios(by)  # raises if ids/order/exogenous hashes differ
    assert len({tuple(r.exogenous_hash for r in v) for v in by.values()}) == 1


def test_exogenous_trace_depends_on_the_seed_not_the_water_stress_family():
    """Same seed in different families = same weather and workload (common random numbers across
    families); different seeds = different traces."""
    sc = pe.build_scenarios(SMALL)["test"]
    res = pe.evaluate_policy(pe.ConstantPolicy(10.0, "hybrid"), sc, SMALL, CURVE)
    by_seed: dict[int, set[str]] = {}
    for s, r in zip(sc, res):
        by_seed.setdefault(s.seed, set()).add(r.exogenous_hash)
    assert all(len(v) == 1 for v in by_seed.values())
    assert len({next(iter(v)) for v in by_seed.values()}) == len(by_seed)


def test_assert_identical_scenarios_detects_a_mismatch():
    sc = pe.build_scenarios(SMALL)["test"]
    a = pe.evaluate_policy(pe.ConstantPolicy(10.0, "hybrid"), sc, SMALL, CURVE)
    b = pe.evaluate_policy(pe.ConstantPolicy(10.0, "hybrid"), sc, SMALL, CURVE)
    b[0] = pe.EpisodeResult(b[0].scenario_id, b[0].metrics, "deadbeef")
    with pytest.raises(AssertionError, match="exogenous"):
        pe.assert_identical_scenarios({"a": a, "b": b})
    with pytest.raises(AssertionError, match="ids differ"):
        pe.assert_identical_scenarios({"a": a, "b": list(reversed(a))})


def test_episode_is_reproducible():
    s = pe.build_scenarios(SMALL)["test"][0]
    p = pe.ConstantPolicy(12.5, "hybrid")
    assert pe.run_episode(p, s, SMALL, CURVE) == pe.run_episode(p, s, SMALL, CURVE)


# --------------------------------------------------------------------------- policies / metrics
@pytest.mark.xfail(
    strict=True,
    reason="T20: the v1 env's chilled-water range is now 16-25 C (derived from the envelope); the T8 harness "
    "(src/policy_evaluation.py::_chilled_to_action) still encodes constants on the legacy 5-15 C axis. Fixing "
    "it needs src/policy_evaluation.py, which is not an allowed T20 file -- follow-up required.",
)
def test_constant_policy_encodes_the_action_the_env_decodes():
    from src.optimizer import DataCentreEnv

    env = DataCentreEnv(seed=0)
    for t in (5.0, 7.5, 12.5, 15.0):
        for m in COOLING_MODES:
            chilled, mode = env._action_to_control(pe.ConstantPolicy(t, m).act(None, {}))
            assert chilled == pytest.approx(t, abs=1e-5) and mode == m


def test_rule_policy_follows_the_production_selector():
    r = pe.RulePolicy()

    def mode(temp, ws):
        return COOLING_MODES[int(round(r.act(None, {"outside_temp": temp, "water_stress": ws})[1] * 3))]

    assert mode(5.0, 0.0) == "free_air" and mode(35.0, 0.0) == "evaporative"
    assert mode(20.0, 0.5) == "hybrid" and mode(5.0, 0.9) == "closed_loop"
    assert r.act(None, {"outside_temp": 20.0, "water_stress": 0.0})[0] == pytest.approx(0.7)  # 12 C


def test_unknown_constant_mode_is_rejected():
    with pytest.raises(ValueError):
        pe.ConstantPolicy(10.0, "magic")


def test_metrics_cover_every_pre_registered_name_and_violations_are_counts():
    s = pe.build_scenarios(SMALL)["test"][0]
    m = pe.run_episode(pe.ConstantPolicy(10.0, "hybrid"), s, SMALL, CURVE).metrics
    assert set(m) == set(pe.METRICS)
    for k in ("outlet_violation_steps", "inlet_over_max_steps", "inlet_under_min_steps"):
        assert m[k] == int(m[k]) and 0 <= m[k] <= SMALL.episode_steps


def test_energy_is_it_plus_cooling_over_five_minute_steps():
    from src.optimizer import DataCentreEnv

    s = pe.build_scenarios(SMALL)["test"][0]
    p = pe.ConstantPolicy(10.0, "hybrid")
    env = DataCentreEnv(seed=s.seed, water_stress=s.water_stress, carbon_intensity_by_hour=CURVE)
    obs, _ = env.reset(seed=s.seed)
    total = 0.0
    for _ in range(SMALL.episode_steps):
        obs, r, te, tr, info = env.step(p.act(obs, env.get_state_dict()))
        total += (info["state"]["it_power"] + info["state"]["cooling_power"]) * 5 / 60
    assert pe.run_episode(p, s, SMALL, CURVE).metrics["energy_kwh"] == pytest.approx(total)


def test_ppo_adapter_calls_the_optimizer_hook():
    class FakeModel:
        def predict(self, obs, deterministic=True):
            assert deterministic is True
            return np.array([0.25, 1.0]), None

    opt = JointOptimizer(seed=0)
    opt._model = FakeModel()
    a = pe.PPOPolicy(opt, "ppo_seed_0").act(np.zeros(9, dtype=np.float32), {})
    assert a.dtype == np.float32 and a.tolist() == [0.25, 1.0]
    with pytest.raises(RuntimeError):
        JointOptimizer(seed=1).policy_action(np.zeros(9))


# --------------------------------------------------------------------------- outcome rules (synthetic)
def _results(scenarios, reward, **over):
    out = []
    for i, s in enumerate(scenarios):
        m = {k: 0.0 for k in pe.METRICS}
        m.update(
            total_reward=reward(i),
            energy_kwh=100.0,
            water_L=100.0,
            carbon_gco2=100.0,
            mean_pue=1.2,
            mean_wue=0.5,
            inlet_under_min_steps=288.0,
        )
        m.update(over)
        out.append(pe.EpisodeResult(s.scenario_id, m, "h"))
    return out


def _decide(ppo_reward, rule_reward, const_reward, *, ppo_over=None, const_over=None, seeds=5, n=6, noise=0.3):
    cfg = replace(CFG, n_test_per_family=n)
    sc = pe.build_scenarios(cfg)["test"]
    rng = np.random.default_rng(0)
    jitter = {s: rng.normal(0, noise, len(sc)) for s in range(seeds)}
    ppo = {s: _results(sc, lambda i, s=s: ppo_reward + jitter[s][i], **(ppo_over or {})) for s in range(seeds)}
    base = {
        "rule": _results(sc, lambda i: rule_reward),
        "best_constant": _results(sc, lambda i: const_reward, **(const_over or {})),
    }
    return pe.decide_outcome(cfg, ppo_test=ppo, selected_seed=0, baselines_test=base, test_scenarios=sc)


def test_outcome_A_when_ppo_clearly_beats_both_and_is_safe():
    assert _decide(-40.0, -150.0, -58.0)["outcome"] == "A"


def test_outcome_C_when_best_constant_beats_ppo():
    d = _decide(-60.0, -150.0, -58.0)
    assert d["outcome"] == "C" and "best_constant" in d["simpler_controllers_within_tolerance"]


def test_outcome_C_when_ppo_is_only_marginally_better_than_a_constant():
    d = _decide(-57.9, -150.0, -58.0)  # +0.1 on |58| is inside the 1% tolerance
    assert d["outcome"] == "C"


def test_outcome_C_when_rule_baseline_is_better_than_ppo():
    assert _decide(-100.0, -60.0, -200.0)["outcome"] == "C"


def test_unsafe_constant_cannot_be_the_replacement():
    d = _decide(-60.0, -150.0, -58.0, const_over={"outlet_violation_steps": 3.0})
    assert d["outcome"] == "B" and d["simpler_controllers_within_tolerance"] == []


def test_outcome_B_when_ppo_beats_both_but_violates_the_envelope():
    d = _decide(-40.0, -150.0, -58.0, ppo_over={"outlet_violation_steps": 1.0})
    assert d["outcome"] == "B" and d["detail"]["envelope_selected_candidate"]["ok"] is False


def test_outcome_B_when_secondary_metric_regresses_beyond_tolerance():
    d = _decide(-40.0, -150.0, -58.0, ppo_over={"water_L": 130.0})  # +30% water vs both baselines
    assert d["outcome"] == "B"
    assert d["detail"]["per_baseline"]["rule"]["secondary"]["water_L"]["ok"] is False


def test_outcome_B_when_seed_level_ci_includes_zero():
    cfg = replace(CFG, n_test_per_family=6)
    sc = pe.build_scenarios(cfg)["test"]
    # seeds disagree wildly: two of five are far worse than the constant -> seed-level t-CI includes 0
    levels = {0: -30.0, 1: -30.0, 2: -30.0, 3: -90.0, 4: -90.0}
    ppo = {s: _results(sc, lambda i, L=L: L) for s, L in levels.items()}
    base = {"rule": _results(sc, lambda i: -150.0), "best_constant": _results(sc, lambda i: -58.0)}
    d = pe.decide_outcome(cfg, ppo_test=ppo, selected_seed=0, baselines_test=base, test_scenarios=sc)
    assert d["outcome"] == "B"
    assert d["detail"]["per_baseline"]["best_constant"]["criteria"]["seed_ci_excludes_zero_for_ppo"] is False


def test_outcome_B_when_advantage_fails_in_one_family():
    cfg = replace(CFG, n_test_per_family=6)
    sc = pe.build_scenarios(cfg)["test"]

    def reward(i):
        return -40.0 if sc[i].family != "stress_0.8" else -80.0

    ppo = {s: _results(sc, reward) for s in range(5)}
    base = {"rule": _results(sc, lambda i: -150.0), "best_constant": _results(sc, lambda i: -58.0)}
    d = pe.decide_outcome(cfg, ppo_test=ppo, selected_seed=0, baselines_test=base, test_scenarios=sc)
    assert d["outcome"] == "B"


def test_inlet_under_min_is_judged_relative_to_the_rule_baseline():
    ok = _decide(-40.0, -150.0, -58.0, ppo_over={"inlet_under_min_steps": 288.0})
    worse = _decide(-40.0, -150.0, -58.0, ppo_over={"inlet_under_min_steps": 300.0})
    assert ok["outcome"] == "A" and worse["outcome"] == "B"


def test_fewer_than_five_ppo_seeds_cannot_be_decided():
    cfg = replace(CFG, n_test_per_family=3)
    sc = pe.build_scenarios(cfg)["test"]
    with pytest.raises(ValueError, match=">= 5"):
        pe.decide_outcome(
            cfg,
            ppo_test={s: _results(sc, lambda i: -40.0) for s in range(4)},
            selected_seed=0,
            baselines_test={"rule": _results(sc, lambda i: -150.0), "best_constant": _results(sc, lambda i: -58.0)},
            test_scenarios=sc,
        )


def test_claim_allowed_only_for_outcome_A():
    assert _decide(-40.0, -150.0, -58.0)["claim_allowed"] == "simulator-validated candidate"
    assert _decide(-60.0, -150.0, -58.0)["claim_allowed"] == "none"


# --------------------------------------------------------------------------- full run (stand-in candidates)
class _Stand:
    """Stand-in for a trained JointOptimizer: a fixed action, no torch."""

    def __init__(self, chilled_C, mode):
        self._a = pe.ConstantPolicy(chilled_C, mode).act(None, {})

    def policy_action(self, obs, deterministic=True):
        return self._a


@pytest.mark.xfail(
    strict=True,
    reason="T20: the v1 env's chilled-water range is now 16-25 C (derived from the envelope); the T8 harness "
    "(src/policy_evaluation.py::_chilled_to_action) still encodes constants on the legacy 5-15 C axis. Fixing "
    "it needs src/policy_evaluation.py, which is not an allowed T20 file -- follow-up required.",
)
def test_full_run_selects_by_validation_and_never_peeks_at_test():
    cands = {
        0: _Stand(5.0, "free_air"),
        1: _Stand(15.0, "closed_loop"),
        2: _Stand(10.0, "hybrid"),
        3: _Stand(12.5, "closed_loop"),
        4: _Stand(7.5, "evaporative"),
    }
    res = pe.run_evaluation(SMALL, ppo_candidates=cands, carbon_curve=CURVE, carbon_is_real=False)
    v = res["selection"]["ppo_validation_reward"]
    assert res["selection"]["selected_ppo_seed"] == int(max(v, key=v.get))
    assert res["selection"]["selected_ppo_seed"] != 0  # seed order is not the criterion
    # PPO identical to the best constant -> a simpler controller is within tolerance -> C
    assert res["decision"]["outcome"] == "C"
    assert res["physics_version"] == pe.PHYSICS_VERSION and len(res["scenario_set_id"]) == 16
    assert set(res["per_scenario_test"]) >= {"rule", "best_constant", "ppo_seed_0", "ppo_seed_4"}


def test_baselines_only_run_makes_no_ppo_claim():
    res = pe.run_evaluation(SMALL, ppo_candidates=None, carbon_curve=CURVE, carbon_is_real=False)
    assert res["decision"]["outcome"] == "NOT_EVALUATED" and res["decision"]["claim_allowed"] == "none"


def test_run_is_reproducible():
    def strip(r):
        r = json.loads(json.dumps(r))
        r.pop("environment")
        return r

    a = pe.run_evaluation(SMALL, ppo_candidates=None, carbon_curve=CURVE, carbon_is_real=False)
    b = pe.run_evaluation(SMALL, ppo_candidates=None, carbon_curve=CURVE, carbon_is_real=False)
    assert strip(a) == strip(b)


# --------------------------------------------------------------------------- pre-registration + registry
def test_preregistration_roundtrip_and_tamper_detection(tmp_path):
    pe.write_preregistration(CFG, tmp_path)
    assert pe.load_preregistered_config(tmp_path) == CFG
    doc = json.loads((tmp_path / "PREREGISTRATION.json").read_text())
    assert doc["primary_metric"] == "total_reward" and set(doc["metrics"]) == set(pe.METRICS)
    assert "t-based" in (tmp_path / "PREREGISTRATION.md").read_text()
    doc["config"]["secondary_tolerance_rel"] = 0.5  # loosen the rules after the fact
    (tmp_path / "PREREGISTRATION.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="mismatch"):
        pe.load_preregistered_config(tmp_path)


def test_run_requires_a_preregistration(tmp_path):
    with pytest.raises(FileNotFoundError):
        pe.load_preregistered_config(tmp_path)


def test_cli_refuses_to_overwrite_a_preregistration(tmp_path):
    assert pe.main(["prereg", "--out", str(tmp_path)]) == 0
    assert pe.main(["prereg", "--out", str(tmp_path)]) == 2


def test_committed_preregistration_matches_the_default_config():
    from pathlib import Path

    cfg = pe.load_preregistered_config(Path(__file__).resolve().parents[1] / "reports" / "policy_evaluation")
    assert cfg == CFG


def test_registry_entries_record_physics_version_and_scenario_set_id():
    res = pe.run_evaluation(
        SMALL, ppo_candidates={s: _Stand(10.0, "hybrid") for s in range(5)}, carbon_curve=CURVE, carbon_is_real=False
    )
    logged = []
    entries = pe.register_candidates(
        res,
        {s: f"models/optimizer_candidates/seed_{s}" for s in range(5)},
        log_model=lambda name, **kw: logged.append((name, kw)) or {"name": name, **kw},
    )
    assert len(entries) == 5 and all(n == "ppo_candidate" for n, _ in logged)
    for _, kw in logged:
        assert kw["params"]["physics_version"] == pe.PHYSICS_VERSION
        assert kw["params"]["scenario_set_id"] == res["scenario_set_id"]
        assert "not auto-applied" in kw["params"]["status"]
    assert sum(kw["params"]["selected"] for _, kw in logged) == 1


def test_train_candidates_uses_registered_seeds_weights_and_never_touches_deployed_dir(tmp_path):
    calls = []

    class FakeOpt:
        def __init__(self, **kw):
            self.kw = kw

        def train(self, **kw):
            calls.append(("train", self.kw["seed"], kw))

        def save(self, path):
            calls.append(("save", self.kw["seed"], str(path)))

    dirs = pe.train_candidates(CFG, tmp_path / "cands", optimizer_cls=FakeOpt)
    assert sorted(dirs) == list(CFG.training_seeds) and len(dirs) >= 5
    trains = [c for c in calls if c[0] == "train"]
    assert all(c[2]["water_stress"] == 0.0 and c[2]["total_timesteps"] == 50_000 for c in trains)
    assert all(str(tmp_path / "cands") in c[2] for c in calls if c[0] == "save")
    assert not any(
        "models" in c[2] and "optimizer" in c[2] and "candidates" not in c[2] for c in calls if c[0] == "save"
    )


def test_load_candidates_rejects_missing_seed_directories(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing PPO candidate"):
        pe.load_candidates(tmp_path, CFG)
