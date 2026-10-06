"""Tuning of the four baselines. Validation scenarios ONLY.

* **Rule**     nothing is tuned; it is run on validation to record whether it is envelope-feasible.
* **Constant** exhaustive search of a fixed ``(set-point, mode)`` grid.
* **Lookup**   state-dependent table over (IT utilisation, outside temperature) bins; for every bin an
               exhaustive search of the action grid; lexicographic tie-break.
* **PID**      deterministic grid over ``(kp, ki, kd)``.

Rules shared by all of them:

* Every function takes a list of validation scenarios and never sees the test split.
  ``assert_validation_only`` raises ``TuningLeak`` for any scenario that is not a validation scenario.
* Objective: highest mean total reward (the PPO objective) over the validation scenarios.
* Feasibility: a candidate is feasible only if it has ZERO outlet-over-limit, inlet-over-max and
  inlet-under-min steps in EVERY validation episode. The envelope is never loosened: if no candidate is
  feasible the baseline is recorded as ``infeasible`` (with the least-violating candidate for
  information) and is not evaluated on the test set.
* Ties (rewards within ``tie_tolerance``) are broken lexicographically on the candidate's key, ascending:
  ``(chilled_C, mode index)`` for actions, ``(kp, ki, kd)`` for gains. No randomness anywhere.

Lookup, honestly: the per-bin search attributes each step's reward to the bin the step STARTED in, from
constant-action rollouts of every grid action. It therefore ignores the cost of switching between actions
(thermal lag, the plant's rate limit). The finished table is run closed-loop on the validation scenarios
and that result, not the table's own estimate, decides feasibility and is what gets recorded.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import asdict, dataclass
from typing import Any, Callable, Sequence

import numpy as np

from .. import policy_evaluation as pe
from ..optimizer import COOLING_MODES
from . import config as bcfg
from .policies import (
    CHILLED_MAX_C,
    CHILLED_MIN_C,
    INITIAL_SETPOINT_C,
    MAX_RATE_C_PER_STEP,
    PRODUCTION_RULE,
    ConstantPolicy,
    LookupPolicy,
    PIDPolicy,
    RulePolicy,
)

TUNER_VERSION = "baselines-tuner/1"
OBJECTIVE = (
    "highest mean total_reward over the validation scenarios (the PPO objective), among envelope-feasible candidates"
)
FEASIBILITY_RULE = (
    "zero outlet_violation_steps, inlet_over_max_steps and inlet_under_min_steps in every validation episode"
)
_ENVELOPE_METRICS = ("outlet_violation_steps", "inlet_over_max_steps", "inlet_under_min_steps")
Progress = Callable[[str], None]


class TuningLeak(RuntimeError):
    """A scenario outside the validation split reached a tuner."""


def assert_validation_only(scenarios: Sequence[pe.Scenario]) -> None:
    if not scenarios:
        raise ValueError("tuning needs at least one validation scenario")
    bad = [s.scenario_id for s in scenarios if s.split != "validation" or "/test/" in s.scenario_id]
    if bad:
        raise TuningLeak(f"tuning may use validation scenarios only; got {bad[:3]}")


# ----------------------------------------------------------------------------- search space


@dataclass(frozen=True)
class TuningSpace:
    rule_chilled_C: float
    constant_chilled_C: tuple[float, ...]
    constant_modes: tuple[str, ...]
    lookup_util_edges: tuple[float, ...]
    lookup_temp_edges: tuple[float, ...]
    lookup_chilled_C: tuple[float, ...]
    lookup_modes: tuple[str, ...]
    lookup_min_cell_samples: int
    lookup_transient_steps_excluded: int
    pid_target_inlet_C: float
    pid_kp: tuple[float, ...]
    pid_ki: tuple[float, ...]
    pid_kd: tuple[float, ...]
    pid_nominal_setpoint_C: float
    pid_mode_rule: str
    tie_tolerance: float = 1e-9

    def to_json(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(self).items()}


def default_space(cfg: pe.EvalConfig) -> TuningSpace:
    """The registered search space. The constant grid is the pre-registered one (``cfg.constant_chilled_C``)."""
    return TuningSpace(
        rule_chilled_C=float(cfg.rule_chilled_C),
        constant_chilled_C=tuple(float(c) for c in cfg.constant_chilled_C),
        constant_modes=tuple(COOLING_MODES),
        lookup_util_edges=(0.2, 0.4, 0.6, 0.8),
        lookup_temp_edges=(16.0, 20.0, 24.0, 28.0),
        lookup_chilled_C=tuple(float(c) for c in cfg.constant_chilled_C),
        lookup_modes=tuple(COOLING_MODES),
        lookup_min_cell_samples=20,
        lookup_transient_steps_excluded=3,  # the plant needs <= 3 steps (5 C at 2 C/step) to reach any constant set-point from 10 C
        pid_target_inlet_C=22.0,
        pid_kp=(0.0, 0.5, 1.0, 2.0, 4.0),
        pid_ki=(0.0, 0.02, 0.05, 0.1),
        pid_kd=(0.0, 0.5, 1.0),
        pid_nominal_setpoint_C=12.0,
        pid_mode_rule=PRODUCTION_RULE,
    )


# ----------------------------------------------------------------------------- measurement helpers


def mean_reward(results: Sequence[pe.EpisodeResult]) -> float:
    return float(pe.metric_matrix(results, pe.PRIMARY_METRIC).mean())


def envelope_counts(results: Sequence[pe.EpisodeResult]) -> dict[str, int]:
    """Total envelope-violation steps over the scenarios, per kind."""
    return {m: int(round(float(pe.metric_matrix(results, m).sum()))) for m in _ENVELOPE_METRICS}


def is_feasible(counts: dict[str, int]) -> bool:
    return sum(counts.values()) == 0


def curve_sha256(curve: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(curve, dtype="<f8").tobytes()).hexdigest()


def pick(candidates: list[dict[str, Any]], tolerance: float) -> dict[str, Any] | None:
    """Best FEASIBLE candidate: highest reward, ties (within ``tolerance``) -> smallest ``key``. None if none feasible.
    Each candidate is ``{"key": tuple, "reward": float, "feasible": bool, ...}``."""
    feasible = [c for c in candidates if c["feasible"]]
    if not feasible:
        return None
    top = max(c["reward"] for c in feasible)
    return min((c for c in feasible if c["reward"] >= top - tolerance), key=lambda c: c["key"])


def least_violating(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Information only: fewest violation steps, then highest reward, then smallest key."""
    return min(candidates, key=lambda c: (sum(c["violations"].values()), -c["reward"], c["key"]))


def _mode_index(mode: str) -> int:
    return COOLING_MODES.index(mode)


# ----------------------------------------------------------------------------- constant-action sweep


class ActionSweep:
    """Rolls every requested constant action over the validation scenarios once and caches the result,
    keeping per-step ``(utilisation, outside_temp, reward, violation)`` so Lookup can attribute reward to
    bins. Shared by the Constant and Lookup tuners."""

    def __init__(
        self,
        scenarios: Sequence[pe.Scenario],
        eval_cfg: pe.EvalConfig,
        carbon: np.ndarray,
        progress: Progress | None = None,
    ):
        assert_validation_only(scenarios)
        self.scenarios = list(scenarios)
        self.eval_cfg, self.carbon = eval_cfg, carbon
        self._say = progress or (lambda _m: None)
        self._cache: dict[tuple[float, str], tuple[list[pe.EpisodeResult], np.ndarray]] = {}

    def get(self, chilled_C: float, mode: str) -> tuple[list[pe.EpisodeResult], np.ndarray]:
        """``(episode results, steps)``; ``steps`` has shape ``(n_scenarios, n_steps, 4)``."""
        key = (float(chilled_C), mode)
        if key not in self._cache:
            policy = ConstantPolicy(chilled_C, mode)
            results, per_scenario = [], []
            for scenario in self.scenarios:
                rows: list[tuple[float, float, float, float]] = []

                def on_step(before: dict[str, Any], reward: float, after: dict[str, Any], rows=rows) -> None:
                    violated = (
                        after["outlet_temp"] > pe.OUTLET_MAX
                        or after["inlet_temp"] > pe.INLET_TEMP_MAX
                        or after["inlet_temp"] < pe.INLET_TEMP_MIN
                    )
                    rows.append((float(before["utilisation"]), float(before["outside_temp"]), reward, float(violated)))

                results.append(pe.run_episode(policy, scenario, self.eval_cfg, self.carbon, on_step=on_step))
                per_scenario.append(rows)
            self._cache[key] = (results, np.asarray(per_scenario, dtype=float))
            self._say(f"  swept {policy.name}")
        return self._cache[key]


# ----------------------------------------------------------------------------- rule


def tune_rule(
    space: TuningSpace, scenarios: Sequence[pe.Scenario], eval_cfg: pe.EvalConfig, carbon: np.ndarray
) -> dict[str, Any]:
    assert_validation_only(scenarios)
    results = pe.evaluate_policy(RulePolicy(space.rule_chilled_C), scenarios, eval_cfg, carbon)
    counts = envelope_counts(results)
    feasible = is_feasible(counts)
    return {
        "parameters": {"chilled_C": space.rule_chilled_C, "mode_rule": PRODUCTION_RULE},
        "result": {"validation_reward": mean_reward(results), "validation_violation_steps": counts, "tuned": False},
        "search_space": {"note": "the rule is not tuned; it is checked against the envelope on validation"},
        "status": "feasible" if feasible else "infeasible",
        "reason": None if feasible else f"the production rule violates the envelope on validation: {counts}",
    }


# ----------------------------------------------------------------------------- constant


def _constant_candidates(sweep: ActionSweep, grid: Sequence[float], modes: Sequence[str]) -> list[dict[str, Any]]:
    out = []
    for chilled, mode in itertools.product(grid, modes):
        results, _ = sweep.get(chilled, mode)
        counts = envelope_counts(results)
        out.append(
            {
                "key": (float(chilled), _mode_index(mode)),
                "chilled_C": float(chilled),
                "mode": mode,
                "reward": mean_reward(results),
                "violations": counts,
                "feasible": is_feasible(counts),
            }
        )
    return out


def _public(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "chilled_C": c["chilled_C"],
        "mode": c["mode"],
        "validation_reward": c["reward"],
        "violation_steps": c["violations"],
        "feasible": c["feasible"],
    }


def tune_constant(space: TuningSpace, sweep: ActionSweep) -> dict[str, Any]:
    cands = _constant_candidates(sweep, space.constant_chilled_C, space.constant_modes)
    best = pick(cands, space.tie_tolerance)
    info = least_violating(cands)
    return {
        "parameters": {"selected": None if best is None else {"chilled_C": best["chilled_C"], "mode": best["mode"]}},
        "result": {
            "validation_reward": None if best is None else best["reward"],
            "candidates": [_public(c) for c in cands],
            "least_violating": _public(info),
            "tie_break": "lexicographic ascending on (chilled_C, mode index)",
        },
        "search_space": {
            "chilled_C": list(space.constant_chilled_C),
            "modes": list(space.constant_modes),
            "tie_tolerance": space.tie_tolerance,
        },
        "status": "feasible" if best else "infeasible",
        "reason": None
        if best
        else f"no grid action satisfies the envelope on every validation scenario; fewest violations: {_public(info)}",
    }


# ----------------------------------------------------------------------------- lookup


def tune_lookup(
    space: TuningSpace,
    sweep: ActionSweep,
    scenarios: Sequence[pe.Scenario],
    eval_cfg: pe.EvalConfig,
    carbon: np.ndarray,
) -> dict[str, Any]:
    assert_validation_only(scenarios)
    util_edges, temp_edges = np.array(space.lookup_util_edges), np.array(space.lookup_temp_edges)
    n_u, n_t = len(util_edges) + 1, len(temp_edges) + 1
    actions = list(itertools.product(space.lookup_chilled_C, space.lookup_modes))

    fallback_tune = tune_constant(
        TuningSpace(
            **{**asdict(space), "constant_chilled_C": space.lookup_chilled_C, "constant_modes": space.lookup_modes}
        ),
        sweep,
    )
    fb = fallback_tune["parameters"]["selected"] or {
        "chilled_C": fallback_tune["result"]["least_violating"]["chilled_C"],
        "mode": fallback_tune["result"]["least_violating"]["mode"],
    }

    reference_steps = None
    stats: dict[tuple[float, str], dict[str, np.ndarray]] = {}
    keep = slice(space.lookup_transient_steps_excluded, None)
    for chilled, mode in actions:
        _, steps = sweep.get(chilled, mode)
        util, temp = steps[:, keep, 0], steps[:, keep, 1]
        if reference_steps is None:
            reference_steps = (util, temp)
        elif not (np.array_equal(util, reference_steps[0]) and np.array_equal(temp, reference_steps[1])):
            raise AssertionError(
                "exogenous utilisation/outside temperature differ between actions; the sweep is not comparable"
            )
        cell_u = np.searchsorted(util_edges, util, side="right")
        cell_t = np.searchsorted(temp_edges, temp, side="right")
        flat = (cell_u * n_t + cell_t).ravel()
        reward, violated = steps[:, keep, 2].ravel(), steps[:, keep, 3].ravel()
        n = np.bincount(flat, minlength=n_u * n_t)
        stats[(chilled, mode)] = {
            "n": n,
            "reward_sum": np.bincount(flat, weights=reward, minlength=n_u * n_t),
            "violations": np.bincount(flat, weights=violated, minlength=n_u * n_t),
        }

    table: list[list[dict[str, Any]]] = []
    for i in range(n_u):
        row = []
        for j in range(n_t):
            cell = i * n_t + j
            n = int(stats[actions[0]]["n"][cell])
            if n < space.lookup_min_cell_samples:
                row.append(
                    {
                        "chilled_C": fb["chilled_C"],
                        "mode": fb["mode"],
                        "n": n,
                        "source": "fallback",
                        "mean_reward": None,
                        "violation_steps": None,
                    }
                )
                continue
            cands = [
                {
                    "key": (float(c), _mode_index(m)),
                    "chilled_C": float(c),
                    "mode": m,
                    "reward": float(stats[(c, m)]["reward_sum"][cell] / n),
                    "violations": {"steps": int(stats[(c, m)]["violations"][cell])},
                    "feasible": int(stats[(c, m)]["violations"][cell]) == 0,
                }
                for c, m in actions
            ]
            best = pick(cands, space.tie_tolerance)
            source = "table"
            if best is None:  # every action violates the envelope somewhere in this bin: report it, do not hide it
                best, source = least_violating(cands), "least_violating"
            row.append(
                {
                    "chilled_C": best["chilled_C"],
                    "mode": best["mode"],
                    "n": n,
                    "source": source,
                    "mean_reward": best["reward"],
                    "violation_steps": best["violations"]["steps"],
                }
            )
        table.append(row)

    policy = LookupPolicy(
        space.lookup_util_edges,
        space.lookup_temp_edges,
        [[(c["chilled_C"], c["mode"]) for c in r] for r in table],
        name="lookup",
    )
    closed_loop = pe.evaluate_policy(policy, scenarios, eval_cfg, carbon)
    counts = envelope_counts(closed_loop)
    feasible = is_feasible(counts)
    reward = mean_reward(closed_loop)
    best_const = fallback_tune["result"]["validation_reward"]
    return {
        "parameters": {
            "util_edges": list(space.lookup_util_edges),
            "temp_edges": list(space.lookup_temp_edges),
            "table": table,
            "fallback": {
                "chilled_C": fb["chilled_C"],
                "mode": fb["mode"],
                "rule": "best feasible constant over the lookup grid on validation",
            },
            "bin_rule": "bin = bisect_right(edges, value): closed on the left, open on the right, first/last bins unbounded",
        },
        "result": {
            "validation_reward_closed_loop": reward,
            "validation_violation_steps": counts,
            "best_constant_over_lookup_grid_validation_reward": best_const,
            "improves_on_best_constant": None if best_const is None else bool(reward > best_const),
            "cells": n_u * n_t,
            "fallback_cells": sum(1 for r in table for c in r if c["source"] == "fallback"),
            "least_violating_cells": sum(1 for r in table for c in r if c["source"] == "least_violating"),
            "tie_break": "lexicographic ascending on (chilled_C, mode index)",
        },
        "search_space": {
            "chilled_C": list(space.lookup_chilled_C),
            "modes": list(space.lookup_modes),
            "util_edges": list(space.lookup_util_edges),
            "temp_edges": list(space.lookup_temp_edges),
            "min_cell_samples": space.lookup_min_cell_samples,
            "transient_steps_excluded": space.lookup_transient_steps_excluded,
            "tie_tolerance": space.tie_tolerance,
            "attribution": "per-step reward of constant-action rollouts, attributed to the bin the step started in; switching costs are not modelled",
        },
        "status": "feasible" if feasible else "infeasible",
        "reason": None
        if feasible
        else f"the lookup table violates the envelope when run closed-loop on validation: {counts}",
    }


# ----------------------------------------------------------------------------- PID


def tune_pid(
    space: TuningSpace,
    scenarios: Sequence[pe.Scenario],
    eval_cfg: pe.EvalConfig,
    carbon: np.ndarray,
    progress: Progress | None = None,
) -> dict[str, Any]:
    assert_validation_only(scenarios)
    say = progress or (lambda _m: None)
    cands = []
    for kp, ki, kd in itertools.product(space.pid_kp, space.pid_ki, space.pid_kd):
        policy = PIDPolicy(
            target_inlet_C=space.pid_target_inlet_C,
            kp=kp,
            ki=ki,
            kd=kd,
            nominal_setpoint_C=space.pid_nominal_setpoint_C,
            mode_rule=space.pid_mode_rule,
        )
        results = pe.evaluate_policy(policy, scenarios, eval_cfg, carbon)
        counts = envelope_counts(results)
        cands.append(
            {
                "key": (float(kp), float(ki), float(kd)),
                "kp": float(kp),
                "ki": float(ki),
                "kd": float(kd),
                "reward": mean_reward(results),
                "violations": counts,
                "feasible": is_feasible(counts),
            }
        )
    say(f"  swept {len(cands)} PID gain sets")
    best = pick(cands, space.tie_tolerance)
    info = least_violating(cands)

    def public(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "kp": c["kp"],
            "ki": c["ki"],
            "kd": c["kd"],
            "validation_reward": c["reward"],
            "violation_steps": c["violations"],
            "feasible": c["feasible"],
        }

    return {
        "parameters": {
            "target_inlet_C": space.pid_target_inlet_C,
            "nominal_setpoint_C": space.pid_nominal_setpoint_C,
            "initial_setpoint_C": INITIAL_SETPOINT_C,
            "min_setpoint_C": CHILLED_MIN_C,
            "max_setpoint_C": CHILLED_MAX_C,
            "max_rate_C_per_step": MAX_RATE_C_PER_STEP,
            "mode_rule": space.pid_mode_rule,
            "anti_windup": True,
            "anti_windup_method": "conditional integration (integrator frozen while the output is held by a limit and the error pushes deeper)",
            "selected_gains": None if best is None else {"kp": best["kp"], "ki": best["ki"], "kd": best["kd"]},
        },
        "result": {
            "validation_reward": None if best is None else best["reward"],
            "candidates": [public(c) for c in cands],
            "least_violating": public(info),
            "tie_break": "lexicographic ascending on (kp, ki, kd)",
        },
        "search_space": {
            "kp": list(space.pid_kp),
            "ki": list(space.pid_ki),
            "kd": list(space.pid_kd),
            "target_inlet_C": space.pid_target_inlet_C,
            "tie_tolerance": space.tie_tolerance,
        },
        "status": "feasible" if best else "infeasible",
        "reason": None
        if best
        else f"no PID gain set satisfies the envelope on every validation scenario; fewest violations: {public(info)}",
    }


# ----------------------------------------------------------------------------- all four


def tune_all(
    eval_cfg: pe.EvalConfig,
    validation: Sequence[pe.Scenario],
    carbon: np.ndarray,
    *,
    carbon_is_real: bool,
    space: TuningSpace | None = None,
    progress: Progress | None = None,
) -> dict[str, dict[str, Any]]:
    """Tune all four baselines on ``validation`` and return their config documents (not yet written)."""
    assert_validation_only(validation)
    say = progress or (lambda _m: None)
    space = space or default_space(eval_cfg)
    carbon = np.asarray(carbon, dtype=float)
    common = {
        "scenario_set_id": pe.scenario_set_id(validation),
        "scenario_ids": [s.scenario_id for s in validation],
        "eval_config_sha256": pe.config_sha256(eval_cfg),
        "objective": OBJECTIVE,
        "feasibility_rule": FEASIBILITY_RULE,
        "carbon": {
            "is_real": bool(carbon_is_real),
            "flat_curve": bool(np.ptp(carbon) == 0),
            "curve_sha256": curve_sha256(carbon),
        },
    }
    sweep = ActionSweep(validation, eval_cfg, carbon, progress)
    say("rule")
    tuned = {"rule": tune_rule(space, validation, eval_cfg, carbon)}
    say("constant")
    tuned["constant"] = tune_constant(space, sweep)
    say("lookup")
    tuned["lookup"] = tune_lookup(space, sweep, validation, eval_cfg, carbon)
    say("pid")
    tuned["pid"] = tune_pid(space, validation, eval_cfg, carbon, progress)
    out = {}
    for name in bcfg.BASELINE_NAMES:
        t = tuned[name]
        out[name] = bcfg.make_config(
            name,
            parameters=t["parameters"],
            tuning={**common, "search_space": t["search_space"], "result": t["result"]},
            status=t["status"],
            infeasible_reason=t["reason"],
            tuner_version=TUNER_VERSION,
        )
    return out
