"""Reproducible policy-evaluation harness (roadmap T8: PPO decision gate).

This is EVALUATION, not training and not deployment. It compares, on IDENTICAL scenarios:

  * PPO candidates (one per training seed),
  * the rule baseline (the production ``DigitalTwin.select_cooling_mode`` rule at the twin's
    default chilled-water setpoint),
  * the best CONSTANT policy (chosen on validation scenarios, never on test),

and ends in an A / B / C evidence outcome under rules that are registered BEFORE any run.

Honest scope: everything here runs inside the simulator (physics ``legacy-0``). Even outcome A
only supports the words "simulator-validated candidate".

Workflow (PowerShell):

    python -m src.policy_evaluation prereg   --out reports/policy_evaluation
    python -m src.policy_evaluation train-candidates --candidates-dir models/optimizer_candidates
    python -m src.policy_evaluation run      --out reports/policy_evaluation `
                                             --candidates-dir models/optimizer_candidates
    python -m src.policy_evaluation run      --out reports/policy_evaluation --baselines-only
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

import numpy as np

from .baselines.policies import ConstantPolicy, RulePolicy  # noqa: F401  (T28: moved to src/baselines; re-exported)
from .baselines.policies import norm_chilled as _norm_chilled  # noqa: F401
from .baselines.policies import norm_mode as _norm_mode  # noqa: F401
from .carbon_provider import load_diurnal_carbon_intensity
from .digital_twin import DEFAULT_CHILLED_WATER_TEMP_C, INLET_TEMP_MAX, INLET_TEMP_MIN
from .optimizer import (
    COOLING_MODES,
    EPISODE_STEPS,
    INTERVAL_MIN,
    OUTLET_MAX,
    DataCentreEnv,
)

PHYSICS_VERSION = "legacy-0 (implicit)"  # T1b/T7 introduce the real constant; this is the frozen current physics
SCHEMA_VERSION = 1

# =============================================================================================
# Metrics registry (pre-registered)
# =============================================================================================
# name -> (direction, description). "higher"/"lower" = which direction is BETTER.
METRICS: dict[str, tuple[str, str]] = {
    "total_reward": ("higher", "Sum of env reward over the episode (-J minus the outlet penalty): the PPO objective"),
    "energy_kwh": ("lower", "Facility energy, (IT + cooling power) x 5 min, summed"),
    "water_L": ("lower", "Water consumed, summed over the episode"),
    "carbon_gco2": ("lower", "Carbon emitted as accounted by the twin (cooling energy x intensity)"),
    "mean_pue": ("lower", "Mean of per-step PUE"),
    "mean_wue": ("lower", "Mean of per-step WUE"),
    "outlet_violation_steps": ("lower", f"Steps with outlet temperature > {OUTLET_MAX} C"),
    "inlet_over_max_steps": ("lower", f"Steps with inlet temperature > {INLET_TEMP_MAX} C"),
    "inlet_under_min_steps": ("lower", f"Steps with inlet temperature < {INLET_TEMP_MIN} C"),
}
PRIMARY_METRIC = "total_reward"
SECONDARY_METRICS = ("energy_kwh", "water_L", "carbon_gco2", "mean_pue", "mean_wue")


# =============================================================================================
# Configuration + pre-registration
# =============================================================================================
@dataclass(frozen=True)
class FamilySpec:
    name: str
    water_stress: float
    seen_in_training: bool  # PPO is trained at water_stress=0.0 only (notebooks/train_all.py)


@dataclass(frozen=True)
class EvalConfig:
    physics_version: str = PHYSICS_VERSION
    episode_steps: int = EPISODE_STEPS
    # objective weights (must equal the candidates' training weights, else rewards are not comparable)
    alpha: float = 0.5
    beta: float = 0.3
    gamma: float = 0.2
    # seeds: three disjoint integer ranges
    training_seeds: tuple[int, ...] = (0, 1, 2, 3, 4)  # >= 5 PPO training seeds
    training_seed_reserved: tuple[int, int] = (0, 99_999)  # inclusive; nothing here may be an evaluation seed
    validation_seed_start: int = 100_000
    n_validation_per_family: int = 10
    test_seed_start: int = 200_000
    n_test_per_family: int = 20
    families: tuple[FamilySpec, ...] = (
        FamilySpec("stress_0.0", 0.0, True),  # in-distribution family, held-out seeds
        FamilySpec("stress_0.4", 0.4, False),  # held-out family
        FamilySpec("stress_0.8", 0.8, False),  # held-out family (drought override active)
    )
    # best-constant search grid (selected on validation)
    constant_chilled_C: tuple[float, ...] = (5.0, 7.5, 10.0, 12.5, 15.0)
    rule_chilled_C: float = DEFAULT_CHILLED_WATER_TEMP_C
    # statistics
    confidence: float = 0.95
    # outcome rules (PROPOSED in the roadmap; frozen here before any run)
    primary_tolerance_rel: float = 0.01  # C: a simpler controller within 1% of |its mean reward| of PPO
    secondary_tolerance_rel: float = 0.02  # A: PPO no more than 2% worse on each secondary metric
    min_training_seeds: int = 5
    scenario_inputs_label: str = "synthetic diurnal weather and workload from DataCentreEnv; simulated plant"

    def to_json(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self)))

    @staticmethod
    def from_json(d: dict[str, Any]) -> "EvalConfig":
        d = dict(d)
        d["training_seeds"] = tuple(d["training_seeds"])
        d["training_seed_reserved"] = tuple(d["training_seed_reserved"])
        d["constant_chilled_C"] = tuple(d["constant_chilled_C"])
        d["families"] = tuple(FamilySpec(**f) for f in d["families"])
        return EvalConfig(**d)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def config_sha256(cfg: EvalConfig) -> str:
    return hashlib.sha256(canonical_json(cfg.to_json()).encode()).hexdigest()


OUTCOME_RULES = {
    "A": (
        "Continue under governance: for BOTH the rule baseline and the best constant, (1) the t-based 95% CI of the "
        "paired primary-metric difference across TRAINING SEEDS excludes zero in PPO's favour, (2) the same holds "
        "across test scenarios for the validation-selected candidate, (3) PPO's mean advantage is positive in every "
        "test family, (4) the selected candidate has zero outlet-over-limit and inlet-over-max steps and no more "
        "inlet-under-min steps than the rule baseline, (5) no secondary metric is worse by more than the secondary "
        "tolerance. Only supports 'simulator-validated candidate'."
    ),
    "C": (
        "Replace with a simpler controller: the rule baseline or the best constant, if it has zero outlet-over-limit "
        "and inlet-over-max steps on the test set and PPO's mean primary-metric advantage over it is at most the "
        "primary tolerance (including the case where PPO is worse). Checked before B."
    ),
    "B": "Offline research module only: PPO is not shown to be better than simple controllers, and not shown to be equal.",
}


# =============================================================================================
# Scenarios
# =============================================================================================
@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    family: str
    split: str  # "validation" | "test"
    seed: int
    water_stress: float


def build_scenarios(cfg: EvalConfig) -> dict[str, list[Scenario]]:
    out: dict[str, list[Scenario]] = {"validation": [], "test": []}
    for split, start, n in (
        ("validation", cfg.validation_seed_start, cfg.n_validation_per_family),
        ("test", cfg.test_seed_start, cfg.n_test_per_family),
    ):
        for fam in cfg.families:
            for i in range(n):
                seed = start + i
                out[split].append(Scenario(f"{fam.name}/{split}/{seed}", fam.name, split, seed, fam.water_stress))
    return out


def scenario_set_id(scenarios: Sequence[Scenario]) -> str:
    payload = canonical_json([asdict(s) for s in scenarios])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def assert_disjoint(cfg: EvalConfig, scenarios: dict[str, list[Scenario]] | None = None) -> None:
    """Training / validation / test seeds are pairwise disjoint and no evaluation seed falls in the
    range reserved for training; scenario ids are unique."""
    scenarios = scenarios or build_scenarios(cfg)
    lo, hi = cfg.training_seed_reserved
    train = set(cfg.training_seeds)
    if len(train) < cfg.min_training_seeds:
        raise ValueError(f"need >= {cfg.min_training_seeds} distinct training seeds, got {len(train)}")
    if not all(lo <= s <= hi for s in train):
        raise ValueError("training seeds must lie inside the reserved training range")
    val = {s.seed for s in scenarios["validation"]}
    test = {s.seed for s in scenarios["test"]}
    if train & val or train & test or val & test:
        raise ValueError("training, validation and test seeds must be pairwise disjoint")
    if any(lo <= s <= hi for s in val | test):
        raise ValueError("evaluation seeds must lie outside the reserved training range")
    ids = [s.scenario_id for v in scenarios.values() for s in v]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario ids must be unique")
    held_out = [f for f in cfg.families if not f.seen_in_training]
    if not held_out:
        raise ValueError("at least one held-out scenario family is required")


# =============================================================================================
# Policies
# =============================================================================================
class Policy(Protocol):
    """``act`` maps (observation, state dict) to a normalised action. A policy MAY define ``reset()``;
    ``run_episode`` calls it at the start of every episode (stateful controllers such as PID need it)."""

    name: str

    def act(self, obs: np.ndarray, state: dict[str, Any]) -> np.ndarray: ...


class PPOPolicy:
    """Adapter over a trained ``JointOptimizer`` (deterministic action)."""

    def __init__(self, optimizer: Any, name: str) -> None:
        self._opt = optimizer
        self.name = name

    def act(self, obs: np.ndarray, state: dict[str, Any]) -> np.ndarray:
        return self._opt.policy_action(obs, deterministic=True)


def constant_grid(cfg: EvalConfig) -> list[ConstantPolicy]:
    return [ConstantPolicy(t, m) for t, m in itertools.product(cfg.constant_chilled_C, COOLING_MODES)]


# =============================================================================================
# Episode runner
# =============================================================================================
@dataclass
class EpisodeResult:
    scenario_id: str
    metrics: dict[str, float]
    exogenous_hash: str  # hash of the (hour, utilisation, outside_temp) trace: must equal across policies


def _round_floats(v: float) -> float:
    return float(v)


def run_episode(
    policy: Policy,
    scenario: Scenario,
    cfg: EvalConfig,
    carbon_curve: np.ndarray,
    on_step: Callable[[dict[str, Any], float, dict[str, Any]], None] | None = None,
) -> EpisodeResult:
    """One episode. ``on_step(state_before, reward, state_after)`` (optional, read-only) is called after
    every environment step; baseline tuning uses it to attribute rewards to states without a second
    rollout loop. It cannot influence the episode."""
    reset = getattr(policy, "reset", None)
    if callable(reset):
        reset()
    env = DataCentreEnv(
        alpha=cfg.alpha,
        beta=cfg.beta,
        gamma=cfg.gamma,
        water_stress=scenario.water_stress,
        max_steps=cfg.episode_steps,
        seed=scenario.seed,
        carbon_intensity_by_hour=carbon_curve,
    )
    obs, _ = env.reset(seed=scenario.seed)
    state = env.get_state_dict()
    dt_h = INTERVAL_MIN / 60.0
    reward = energy = water = carbon = 0.0
    pue: list[float] = []
    wue: list[float] = []
    outlet_v = inlet_over = inlet_under = 0
    trace = hashlib.sha256()
    trace.update(
        repr(
            (
                round(float(state["hour"]), 9),
                round(float(state["utilisation"]), 9),
                round(float(state["outside_temp"]), 9),
            )
        ).encode()
    )
    for _ in range(cfg.episode_steps):
        action = policy.act(obs, state)
        state_before = state
        obs, r, term, trunc, info = env.step(action)
        state = info["state"]
        if on_step is not None:
            on_step(state_before, float(r), state)
        reward += float(r)
        energy += (float(state["it_power"]) + float(state["cooling_power"])) * dt_h
        water += float(state["water_consumed"])
        carbon += float(state["carbon_gco2"])
        pue.append(float(state["pue"]))
        wue.append(float(state["wue"]))
        outlet_v += int(state["outlet_temp"] > OUTLET_MAX)
        inlet_over += int(state["inlet_temp"] > INLET_TEMP_MAX)
        inlet_under += int(state["inlet_temp"] < INLET_TEMP_MIN)
        trace.update(
            repr(
                (
                    round(float(state["hour"]), 9),
                    round(float(state["utilisation"]), 9),
                    round(float(state["outside_temp"]), 9),
                )
            ).encode()
        )
        if term or trunc:
            break
    env.close()
    return EpisodeResult(
        scenario_id=scenario.scenario_id,
        metrics={
            "total_reward": reward,
            "energy_kwh": energy,
            "water_L": water,
            "carbon_gco2": carbon,
            "mean_pue": float(np.mean(pue)),
            "mean_wue": float(np.mean(wue)),
            "outlet_violation_steps": float(outlet_v),
            "inlet_over_max_steps": float(inlet_over),
            "inlet_under_min_steps": float(inlet_under),
        },
        exogenous_hash=trace.hexdigest()[:16],
    )


def evaluate_policy(
    policy: Policy, scenarios: Sequence[Scenario], cfg: EvalConfig, carbon_curve: np.ndarray
) -> list[EpisodeResult]:
    return [run_episode(policy, s, cfg, carbon_curve) for s in scenarios]


def metric_matrix(results: Sequence[EpisodeResult], metric: str) -> np.ndarray:
    return np.array([r.metrics[metric] for r in results], dtype=float)


def assert_identical_scenarios(by_policy: dict[str, list[EpisodeResult]]) -> None:
    """Every policy faced the very same scenarios: same ids in the same order, same exogenous trace."""
    names = list(by_policy)
    ref = by_policy[names[0]]
    for n in names[1:]:
        other = by_policy[n]
        if [r.scenario_id for r in other] != [r.scenario_id for r in ref]:
            raise AssertionError(f"scenario ids differ between {names[0]} and {n}")
        for a, b in zip(ref, other):
            if a.exogenous_hash != b.exogenous_hash:
                raise AssertionError(f"exogenous trace differs for {a.scenario_id}: {names[0]} vs {n}")


# =============================================================================================
# Statistics (no scipy dependency): exact Student-t quantile + paired CI
# =============================================================================================
def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    tail = 0.5 * _betai(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def t_ppf(q: float, df: float) -> float:
    """Student-t quantile by bisection on the exact CDF (accurate to ~1e-12)."""
    if not 0.0 < q < 1.0:
        raise ValueError("q must be in (0, 1)")
    if df <= 0:
        raise ValueError("df must be positive")
    if q == 0.5:
        return 0.0
    if q < 0.5:
        return -t_ppf(1.0 - q, df)
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < q:
        hi *= 2.0
        if hi > 1e12:
            raise ValueError("quantile out of range")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def t_critical(df: int, confidence: float = 0.95) -> float:
    return t_ppf(1.0 - (1.0 - confidence) / 2.0, df)


def paired_difference(a: Sequence[float], b: Sequence[float], confidence: float = 0.95) -> dict[str, float]:
    """Paired difference d = a - b with a t-based CI on the mean (df = n - 1). Never 1.96."""
    a_, b_ = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a_.shape != b_.shape or a_.ndim != 1:
        raise ValueError("paired samples must be 1-D and of equal length")
    n = int(a_.size)
    if n < 2:
        raise ValueError("need at least 2 pairs for a confidence interval")
    d = a_ - b_
    mean = float(d.mean())
    sd = float(d.std(ddof=1))
    se = sd / math.sqrt(n)
    tcrit = t_critical(n - 1, confidence)
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "se": se,
        "df": n - 1,
        "t_critical": tcrit,
        "ci_low": mean - tcrit * se,
        "ci_high": mean + tcrit * se,
    }


# =============================================================================================
# Outcome decision
# =============================================================================================
def _better(metric: str, diff: float) -> bool:
    """Is a positive/negative PPO-minus-baseline difference an improvement for this metric?"""
    return diff > 0 if METRICS[metric][0] == "higher" else diff < 0


def decide_outcome(
    cfg: EvalConfig,
    *,
    ppo_test: dict[int, list[EpisodeResult]],  # training seed -> test results
    selected_seed: int,
    baselines_test: dict[str, list[EpisodeResult]],  # "rule" and "best_constant"
    test_scenarios: Sequence[Scenario],
) -> dict[str, Any]:
    """Apply the pre-registered A/B/C rules. Pure function of its inputs."""
    if len(ppo_test) < cfg.min_training_seeds:
        raise ValueError(f"need >= {cfg.min_training_seeds} PPO training seeds, got {len(ppo_test)}")
    sel = ppo_test[selected_seed]
    fam_of = [s.family for s in test_scenarios]
    sel_primary = metric_matrix(sel, PRIMARY_METRIC)
    detail: dict[str, Any] = {"per_baseline": {}}

    a_ok = True
    c_candidates: list[str] = []
    for bname, bres in baselines_test.items():
        b_primary = metric_matrix(bres, PRIMARY_METRIC)
        # (1) across training seeds
        seed_means_ppo = np.array([metric_matrix(r, PRIMARY_METRIC).mean() for r in ppo_test.values()])
        seed_diff = paired_difference(seed_means_ppo, np.full_like(seed_means_ppo, b_primary.mean()), cfg.confidence)
        c1 = seed_diff["ci_low"] > 0
        # (2) across test scenarios, selected candidate
        scen_diff = paired_difference(sel_primary, b_primary, cfg.confidence)
        c2 = scen_diff["ci_low"] > 0
        # (3) every test family
        fam_diffs = {}
        for fam in sorted(set(fam_of)):
            idx = [i for i, f in enumerate(fam_of) if f == fam]
            fam_diffs[fam] = float((sel_primary[idx] - b_primary[idx]).mean())
        c3 = all(v > 0 for v in fam_diffs.values())
        # (5) secondary metrics
        sec = {}
        c5 = True
        for m in SECONDARY_METRICS:
            sm, bm = float(metric_matrix(sel, m).mean()), float(metric_matrix(bres, m).mean())
            rel_worse = (sm - bm) / abs(bm) if bm else 0.0
            if METRICS[m][0] == "higher":
                rel_worse = -rel_worse
            ok = rel_worse <= cfg.secondary_tolerance_rel
            sec[m] = {"ppo": sm, "baseline": bm, "relative_worse": rel_worse, "ok": ok}
            c5 = c5 and ok
        # (C) simpler-controller equivalence
        adv = float(sel_primary.mean() - b_primary.mean())
        tol = cfg.primary_tolerance_rel * abs(float(b_primary.mean()))
        b_safe = (
            float(metric_matrix(bres, "outlet_violation_steps").sum()) == 0
            and float(metric_matrix(bres, "inlet_over_max_steps").sum()) == 0
        )
        within = adv <= tol
        if within and b_safe:
            c_candidates.append(bname)
        detail["per_baseline"][bname] = {
            "seed_level_diff": seed_diff,
            "scenario_level_diff": scen_diff,
            "family_mean_diff": fam_diffs,
            "secondary": sec,
            "ppo_mean_advantage": adv,
            "primary_tolerance_abs": tol,
            "baseline_envelope_safe": b_safe,
            "criteria": {
                "seed_ci_excludes_zero_for_ppo": bool(c1),
                "scenario_ci_excludes_zero_for_ppo": bool(c2),
                "advantage_positive_in_every_family": bool(c3),
                "secondary_within_tolerance": bool(c5),
            },
        }
        a_ok = a_ok and c1 and c2 and c3 and c5

    # (4) envelope, selected candidate (independent of baseline)
    rule_under = float(metric_matrix(baselines_test["rule"], "inlet_under_min_steps").sum())
    env = {
        "outlet_violation_steps": float(metric_matrix(sel, "outlet_violation_steps").sum()),
        "inlet_over_max_steps": float(metric_matrix(sel, "inlet_over_max_steps").sum()),
        "inlet_under_min_steps": float(metric_matrix(sel, "inlet_under_min_steps").sum()),
        "rule_inlet_under_min_steps": rule_under,
    }
    env_ok = (
        env["outlet_violation_steps"] == 0
        and env["inlet_over_max_steps"] == 0
        and env["inlet_under_min_steps"] <= rule_under
    )
    detail["envelope_selected_candidate"] = {**env, "ok": env_ok}
    a_ok = a_ok and env_ok

    if a_ok:
        outcome, why = "A", "All pre-registered criteria for continuing under governance are met."
    elif c_candidates:
        outcome = "C"
        why = (
            f"A simpler controller ({', '.join(c_candidates)}) is within the primary tolerance of PPO "
            "and respects the safety envelope."
        )
    else:
        outcome = "B"
        why = (
            "PPO is not shown to be better than simple controllers, and no simple controller is within tolerance of it."
        )
    return {
        "outcome": outcome,
        "reason": why,
        "selected_seed": selected_seed,
        "simpler_controllers_within_tolerance": c_candidates,
        "detail": detail,
        "claim_allowed": "simulator-validated candidate" if outcome == "A" else "none",
    }


# =============================================================================================
# Full run
# =============================================================================================
def _mean(results: Sequence[EpisodeResult], metric: str = PRIMARY_METRIC) -> float:
    return float(metric_matrix(results, metric).mean())


def run_evaluation(
    cfg: EvalConfig,
    *,
    ppo_candidates: dict[int, Any] | None,
    carbon_curve: np.ndarray | None = None,
    carbon_is_real: bool | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the whole protocol and return a JSON-serialisable result dict.

    ``ppo_candidates`` maps training seed -> JointOptimizer (or anything with ``policy_action``);
    ``None`` runs baselines only and the outcome is "NOT_EVALUATED"."""
    say = progress or (lambda _m: None)
    scenarios = build_scenarios(cfg)
    assert_disjoint(cfg, scenarios)
    if carbon_curve is None:
        carbon_curve, carbon_is_real = load_diurnal_carbon_intensity()
    carbon_curve = np.asarray(carbon_curve, dtype=float)
    val, test = scenarios["validation"], scenarios["test"]

    # ---- validation: pick best constant and best PPO candidate (never from test) ----
    say(f"validation: {len(val)} scenarios")
    rule = RulePolicy(cfg.rule_chilled_C)
    val_results: dict[str, list[EpisodeResult]] = {rule.name: evaluate_policy(rule, val, cfg, carbon_curve)}
    consts = constant_grid(cfg)
    for c in consts:
        val_results[c.name] = evaluate_policy(c, val, cfg, carbon_curve)
    ppo_val: dict[int, list[EpisodeResult]] = {}
    for seed, opt in (ppo_candidates or {}).items():
        ppo_val[seed] = evaluate_policy(PPOPolicy(opt, f"ppo_seed_{seed}"), val, cfg, carbon_curve)
        val_results[f"ppo_seed_{seed}"] = ppo_val[seed]
    assert_identical_scenarios(val_results)
    best_const = max(consts, key=lambda c: (_mean(val_results[c.name]), c.name))
    selected_seed = max(ppo_val, key=lambda s: (_mean(ppo_val[s]), -s)) if ppo_val else None

    # ---- test: identical scenarios for every policy ----
    say(f"test: {len(test)} scenarios")
    test_results: dict[str, list[EpisodeResult]] = {
        "rule": evaluate_policy(rule, test, cfg, carbon_curve),
        "best_constant": evaluate_policy(best_const, test, cfg, carbon_curve),
    }
    ppo_test: dict[int, list[EpisodeResult]] = {}
    for seed, opt in (ppo_candidates or {}).items():
        ppo_test[seed] = evaluate_policy(PPOPolicy(opt, f"ppo_seed_{seed}"), test, cfg, carbon_curve)
    assert_identical_scenarios({**test_results, **{f"ppo_seed_{s}": r for s, r in ppo_test.items()}})

    # ---- summaries ----
    def summarize(results: Sequence[EpisodeResult]) -> dict[str, float]:
        return {m: float(metric_matrix(results, m).mean()) for m in METRICS}

    summary_test = {k: summarize(v) for k, v in test_results.items()}
    summary_test.update({f"ppo_seed_{s}": summarize(r) for s, r in ppo_test.items()})
    constants_validation = {c.name: _mean(val_results[c.name]) for c in consts}
    inlet_under_floor = min(float(metric_matrix(val_results[c.name], "inlet_under_min_steps").mean()) for c in consts)

    decision: dict[str, Any]
    if ppo_test:
        decision = decide_outcome(
            cfg,
            ppo_test=ppo_test,
            selected_seed=int(selected_seed),
            baselines_test={"rule": test_results["rule"], "best_constant": test_results["best_constant"]},
            test_scenarios=test,
        )
    else:
        decision = {
            "outcome": "NOT_EVALUATED",
            "reason": "No PPO candidates were supplied: this is a baselines-only run. No PPO claim can be made from it.",
            "claim_allowed": "none",
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "physics_version": cfg.physics_version,
        "scenario_inputs": cfg.scenario_inputs_label,
        "carbon": {"is_real": bool(carbon_is_real), "flat_curve": bool(np.ptp(carbon_curve) == 0)},
        "scenario_sets": {
            "validation": {"id": scenario_set_id(val), "n": len(val)},
            "test": {"id": scenario_set_id(test), "n": len(test)},
        },
        "scenario_set_id": scenario_set_id(val + test),
        "preregistration_sha256": config_sha256(cfg),
        "selection": {
            "best_constant": {"name": best_const.name, "chilled_C": best_const.chilled_C, "mode": best_const.mode},
            "best_constant_validation_reward": _mean(val_results[best_const.name]),
            "rule_validation_reward": _mean(val_results[rule.name]),
            "constants_validation_reward": constants_validation,
            "ppo_validation_reward": {str(s): _mean(r) for s, r in ppo_val.items()},
            "selected_ppo_seed": selected_seed,
            "selected_by": "highest mean validation reward (not seed order)",
            "min_inlet_under_min_steps_across_constant_grid": inlet_under_floor,
        },
        "summary_test_mean_per_episode": summary_test,
        "per_scenario_test": {
            k: [{"scenario_id": r.scenario_id, **r.metrics} for r in v] for k, v in test_results.items()
        }
        | {f"ppo_seed_{s}": [{"scenario_id": r.scenario_id, **r.metrics} for r in rs] for s, rs in ppo_test.items()},
        "decision": decision,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


# =============================================================================================
# Pre-registration + report files
# =============================================================================================
def preregistration_document(cfg: EvalConfig) -> dict[str, Any]:
    scenarios = build_scenarios(cfg)
    assert_disjoint(cfg, scenarios)
    return {
        "schema_version": SCHEMA_VERSION,
        "preregistration_sha256": config_sha256(cfg),
        "registered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "primary_metric": PRIMARY_METRIC,
        "secondary_metrics": list(SECONDARY_METRICS),
        "metrics": {k: {"better": v[0], "definition": v[1]} for k, v in METRICS.items()},
        "outcome_rules": OUTCOME_RULES,
        "scenario_sets": {k: {"id": scenario_set_id(v), "n": len(v)} for k, v in scenarios.items()},
        "config": cfg.to_json(),
    }


def preregistration_markdown(doc: dict[str, Any]) -> str:
    c = doc["config"]
    fam = "\n".join(
        f"| {f['name']} | {f['water_stress']} | {'yes (in-distribution)' if f['seen_in_training'] else 'NO (held-out family)'} |"
        for f in c["families"]
    )
    metrics = "\n".join(f"| `{k}` | {v['better']} | {v['definition']} |" for k, v in doc["metrics"].items())
    return f"""# PPO decision gate (T8): pre-registration

Registered BEFORE any evaluation run. `preregistration_sha256`: `{doc['preregistration_sha256']}`
(SHA-256 of the canonical JSON of `config` in `PREREGISTRATION.json`). `run` refuses to start if the file or its hash do not match.

**Scope.** Everything is simulator-only (physics `{c['physics_version']}`). Scenario inputs: {c['scenario_inputs_label']}.
The best that outcome A can support is the phrase "simulator-validated candidate"; never "AI-optimized".

## Protocol

- Policies, identical scenarios for all: PPO (one candidate per training seed, deterministic action), the **rule baseline**
  (`DigitalTwin.select_cooling_mode` at {c['rule_chilled_C']} C), and the **best constant** (grid of
  {len(c['constant_chilled_C'])} chilled-water setpoints x 4 modes, chosen on VALIDATION scenarios only).
- Each scenario is one {c['episode_steps']}-step (24 h) episode with a fixed environment seed; weather noise, workload,
  initial hour, initial state, timestep and constraints are identical for every policy (verified by an exogenous-trace hash).
- PPO training seeds ({len(c['training_seeds'])}): {c['training_seeds']}; seeds {c['training_seed_reserved'][0]}..{c['training_seed_reserved'][1]} are reserved for training.
  Validation seeds start at {c['validation_seed_start']} ({c['n_validation_per_family']} per family), test seeds at {c['test_seed_start']} ({c['n_test_per_family']} per family). All disjoint.
- The deployed candidate is chosen by highest mean VALIDATION reward, not by seed order.
- Statistics: paired differences with a **t-based** {int(c['confidence']*100)}% CI (df = n-1; exact t quantile, never 1.96).

| family | water stress | seen in training? |
|---|---|---|
{fam}

## Metrics

Primary: `{doc['primary_metric']}`. Secondary: {', '.join('`'+m+'`' for m in doc['secondary_metrics'])}.

| metric | better | definition |
|---|---|---|
{metrics}

## Outcome rules (PROPOSED in the roadmap; frozen here)

- **A**: {doc['outcome_rules']['A']}
- **C**: {doc['outcome_rules']['C']}
- **B**: {doc['outcome_rules']['B']}

Tolerances: primary {c['primary_tolerance_rel']:.0%} of the simpler controller's |mean reward|; secondary {c['secondary_tolerance_rel']:.0%}.

Scenario sets: validation `{doc['scenario_sets']['validation']['id']}` (n={doc['scenario_sets']['validation']['n']}),
test `{doc['scenario_sets']['test']['id']}` (n={doc['scenario_sets']['test']['n']}).
"""


def write_preregistration(cfg: EvalConfig, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = preregistration_document(cfg)
    (out_dir / "PREREGISTRATION.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "PREREGISTRATION.md").write_text(preregistration_markdown(doc), encoding="utf-8")
    return out_dir / "PREREGISTRATION.json"


def load_preregistered_config(out_dir: Path) -> EvalConfig:
    """Load the config from the pre-registration file and verify its hash. Raises if missing/tampered."""
    path = out_dir / "PREREGISTRATION.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: pre-register first (`python -m src.policy_evaluation prereg`)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    cfg = EvalConfig.from_json(doc["config"])
    if config_sha256(cfg) != doc["preregistration_sha256"]:
        raise ValueError("pre-registration hash mismatch: the registered config was modified after registration")
    return cfg


def results_markdown(res: dict[str, Any]) -> str:
    d = res["decision"]
    s = res["summary_test_mean_per_episode"]
    cols = [
        "total_reward",
        "energy_kwh",
        "water_L",
        "carbon_gco2",
        "mean_pue",
        "mean_wue",
        "outlet_violation_steps",
        "inlet_over_max_steps",
        "inlet_under_min_steps",
    ]
    rows = "\n".join(f"| {name} | " + " | ".join(f"{vals[c]:.4g}" for c in cols) + " |" for name, vals in s.items())
    sel = res["selection"]
    lines = [
        "# PPO decision gate (T8): evaluation report",
        "",
        f"**Outcome: {d['outcome']}**. {d['reason']}",
        f"Claim allowed: {d['claim_allowed']}.",
        "",
        f"Physics `{res['physics_version']}`. Inputs: {res['scenario_inputs']}. "
        f"Carbon curve real: {res['carbon']['is_real']} (flat: {res['carbon']['flat_curve']}).",
        f"Pre-registration `{res['preregistration_sha256']}`; scenario-set id `{res['scenario_set_id']}` "
        f"(validation n={res['scenario_sets']['validation']['n']}, test n={res['scenario_sets']['test']['n']}).",
        "",
        "## Selection (validation only)",
        f"- Best constant: `{sel['best_constant']['name']}` (validation reward {sel['best_constant_validation_reward']:.4g}); "
        f"rule baseline validation reward {sel['rule_validation_reward']:.4g}.",
        f"- Selected PPO seed: {sel['selected_ppo_seed']} ({sel['selected_by']}).",
        f"- Lowest inlet-under-min steps per episode reachable by ANY constant: {sel['min_inlet_under_min_steps_across_constant_grid']:.4g}.",
        "",
        "## Test set, mean per episode",
        "| policy | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
        rows,
    ]
    if "detail" in d:
        lines += ["", "## Paired differences, PPO minus baseline (primary metric, higher is better)"]
        for b, v in d["detail"]["per_baseline"].items():
            sd, cd = v["seed_level_diff"], v["scenario_level_diff"]
            lines.append(
                f"- vs **{b}**: across {sd['n']} training seeds mean {sd['mean']:.4g}, 95% t-CI [{sd['ci_low']:.4g}, {sd['ci_high']:.4g}]; "
                f"selected candidate across {cd['n']} test scenarios mean {cd['mean']:.4g}, CI [{cd['ci_low']:.4g}, {cd['ci_high']:.4g}]. "
                f"Criteria: {v['criteria']}"
            )
        lines.append(f"- Envelope (selected candidate): {d['detail']['envelope_selected_candidate']}")
    return "\n".join(lines) + "\n"


def write_results(res: dict[str, Any], out_dir: Path, tag: str) -> Path:
    run_dir = out_dir / tag
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "REPORT.md").write_text(results_markdown(res), encoding="utf-8")
    return run_dir


# =============================================================================================
# Registry (candidate entries record physics version + scenario-set id)
# =============================================================================================
def register_candidates(
    res: dict[str, Any], candidate_dirs: dict[int, str], *, log_model: Callable[..., Any] | None = None
) -> list[dict[str, Any]]:
    if log_model is None:
        from .model_registry import log_model as _log

        log_model = _log
    entries = []
    sel = res["selection"]["selected_ppo_seed"]
    for seed, path in sorted(candidate_dirs.items()):
        summary = res["summary_test_mean_per_episode"].get(f"ppo_seed_{seed}", {})
        entries.append(
            log_model(
                "ppo_candidate",
                metrics={
                    "validation_reward": res["selection"]["ppo_validation_reward"].get(str(seed)),
                    "test_mean_reward": summary.get("total_reward"),
                    "decision_outcome": res["decision"]["outcome"],
                },
                data_source="live DigitalTwin simulation (no historical dataset)",
                artifact_path=str(path),
                params={
                    "seed": seed,
                    "selected": seed == sel,
                    "physics_version": res["physics_version"],
                    "scenario_set_id": res["scenario_set_id"],
                    "preregistration_sha256": res["preregistration_sha256"],
                    "status": "evaluation candidate; not deployed; not auto-applied",
                },
            )
        )
    return entries


# =============================================================================================
# CLI
# =============================================================================================
def load_candidates(candidates_dir: Path, cfg: EvalConfig) -> dict[int, Any]:
    from .optimizer import JointOptimizer

    found: dict[int, Any] = {}
    for seed in cfg.training_seeds:
        d = candidates_dir / f"seed_{seed}"
        if not d.exists():
            raise FileNotFoundError(f"missing PPO candidate {d} (train all {len(cfg.training_seeds)} seeds first)")
        opt = JointOptimizer.load(d)
        if (opt._alpha, opt._beta, opt._gamma) != (cfg.alpha, cfg.beta, cfg.gamma):
            raise ValueError(
                f"{d}: objective weights differ from the pre-registered config; rewards are not comparable"
            )
        found[seed] = opt
    return found


def train_candidates(
    cfg: EvalConfig,
    candidates_dir: Path,
    *,
    total_timesteps: int = 50_000,
    n_envs: int = 4,
    optimizer_cls: Any = None,
    progress: Callable[[str], None] | None = None,
) -> dict[int, str]:
    """Train one PPO candidate per pre-registered training seed (same recipe as notebooks/train_all.py:
    50k steps, water_stress=0.0, the pre-registered objective weights) and save each under
    ``<candidates_dir>/seed_<n>``. Candidates are NOT deployed; nothing under models/optimizer is touched."""
    say = progress or (lambda _m: None)
    if optimizer_cls is None:
        from .optimizer import JointOptimizer as optimizer_cls
    dirs: dict[int, str] = {}
    for seed in cfg.training_seeds:
        say(f"training PPO candidate seed={seed}")
        opt = optimizer_cls(alpha=cfg.alpha, beta=cfg.beta, gamma=cfg.gamma, seed=seed)
        opt.train(total_timesteps=total_timesteps, n_envs=n_envs, water_stress=0.0)
        d = Path(candidates_dir) / f"seed_{seed}"
        opt.save(d)
        dirs[seed] = str(d)
    return dirs


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.policy_evaluation", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prereg", help="write PREREGISTRATION.json/.md for the default config")
    p1.add_argument("--out", default="reports/policy_evaluation")
    p3 = sub.add_parser("train-candidates", help="train one PPO candidate per registered training seed (slow)")
    p3.add_argument("--out", default="reports/policy_evaluation")
    p3.add_argument("--candidates-dir", default="models/optimizer_candidates")
    p3.add_argument("--timesteps", type=int, default=50_000)
    p2 = sub.add_parser("run", help="run the evaluation against the registered config")
    p2.add_argument("--out", default="reports/policy_evaluation")
    p2.add_argument("--candidates-dir", default="models/optimizer_candidates")
    p2.add_argument("--baselines-only", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.cmd == "prereg":
        if (out / "PREREGISTRATION.json").exists():
            print("pre-registration already exists; refusing to overwrite", file=sys.stderr)
            return 2
        print("wrote", write_preregistration(EvalConfig(), out))
        return 0
    cfg = load_preregistered_config(out)
    if args.cmd == "train-candidates":
        train_candidates(cfg, Path(args.candidates_dir), total_timesteps=args.timesteps, progress=print)
        return 0
    cands = None if args.baselines_only else load_candidates(Path(args.candidates_dir), cfg)
    res = run_evaluation(cfg, ppo_candidates=cands, progress=print)
    tag = f"{'baselines_only' if cands is None else 'full'}_{res['scenario_set_id']}"
    print("wrote", write_results(res, out, tag))
    print("outcome:", res["decision"]["outcome"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
