"""A toy experiment: two deterministic dummy policies on synthetic cooling scenarios.

Purpose: prove the run framework's round trip (run -> results.json -> report -> verify) without
depending on the digital twin, TensorFlow or stable-baselines3. The "physics" here is a made-up
two-line formula; nothing in this module says anything about the real facility. It must stay
cheap and bit-for-bit deterministic on one machine, because it is the framework's own canary.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from . import RESULTS_SCHEMA


class ConstantPolicy:
    """Always the same chilled-water set-point."""

    name = "constant"

    def __init__(self, setpoint_c: float) -> None:
        self.setpoint_c = float(setpoint_c)

    def act(self, outside_c: float) -> float:
        return self.setpoint_c


class RulePolicy:
    """A warm set-point when it is cold outside, a cooler one when it is warm."""

    name = "rule"

    def __init__(self, cool_below_c: float, cool_setpoint_c: float, warm_setpoint_c: float) -> None:
        self.cool_below_c, self.cool_setpoint_c, self.warm_setpoint_c = (
            float(cool_below_c),
            float(cool_setpoint_c),
            float(warm_setpoint_c),
        )

    def act(self, outside_c: float) -> float:
        return self.cool_setpoint_c if outside_c < self.cool_below_c else self.warm_setpoint_c


def _scenario(rng: np.random.Generator, steps: int) -> tuple[np.ndarray, np.ndarray]:
    hours = np.arange(steps) / steps * 2.0 * math.pi
    base = rng.uniform(8.0, 18.0)
    amplitude = rng.uniform(2.0, 7.0)
    outside = base + amplitude * np.sin(hours) + rng.normal(0.0, 0.5, size=steps)
    load = rng.uniform(0.5, 1.0) + 0.1 * np.sin(2.0 * hours) + rng.normal(0.0, 0.02, size=steps)
    return outside, load


def _episode(policy: Any, outside: np.ndarray, load: np.ndarray) -> tuple[float, float]:
    cooling = 0.0
    water = 0.0
    it = float(np.sum(load))
    for t_out, p_it in zip(outside.tolist(), load.tolist()):
        setpoint = policy.act(t_out)
        lift = max(t_out - setpoint, 0.0)
        cooling += p_it * (0.05 + 0.012 * lift + 0.002 * (20.0 - setpoint) ** 2 / 20.0)
        water += p_it * max(0.0, 0.3 - 0.01 * setpoint)
    return 1.0 + cooling / it, water / it


def run(config: dict[str, Any], seeds: list[int], rng_factory: Callable[..., np.random.Generator]) -> dict[str, Any]:
    """The experiment body: ``(config, seeds, rng_factory) -> results`` (everything but run metadata)."""
    n_episodes, steps = int(config["episodes_per_seed"]), int(config["steps_per_episode"])
    rule_cfg = config["rule_setpoints_C"]
    policies = [
        ConstantPolicy(config["constant_setpoint_C"]),
        RulePolicy(rule_cfg["cool_below_C"], rule_cfg["cool_setpoint_C"], rule_cfg["warm_setpoint_C"]),
    ]
    per_policy: dict[str, dict[int, list[tuple[float, float]]]] = {p.name: {} for p in policies}
    for seed in seeds:
        for episode in range(n_episodes):
            outside, load = _scenario(rng_factory(seed, "scenario", episode), steps)  # same scenario for every policy
            for policy in policies:
                per_policy[policy.name].setdefault(seed, []).append(_episode(policy, outside, load))

    def seed_mean(name: str, seed: int, column: int) -> float:
        return float(np.mean([r[column] for r in per_policy[name][seed]]))

    per_seed_rows = [
        [seed, p.name, seed_mean(p.name, seed, 0), seed_mean(p.name, seed, 1)] for seed in seeds for p in policies
    ]
    summary_rows = []
    means: dict[str, float] = {}
    for p in policies:
        pue = [seed_mean(p.name, s, 0) for s in seeds]
        water = [seed_mean(p.name, s, 1) for s in seeds]
        means[p.name] = float(np.mean(pue))
        summary_rows.append(
            [p.name, means[p.name], float(np.std(pue, ddof=1)) if len(pue) > 1 else 0.0, float(np.mean(water))]
        )
    diffs = np.array([a[0] - b[0] for s in seeds for a, b in zip(per_policy["rule"][s], per_policy["constant"][s])])
    paired = [
        [
            int(diffs.size),
            float(np.mean(diffs)),
            float(np.std(diffs, ddof=1)) if diffs.size > 1 else 0.0,
            int(np.sum(diffs < 0)),
        ]
    ]

    return {
        "schema": RESULTS_SCHEMA,
        "experiment": "toy",
        "title": "Toy dummy-policy experiment",
        "seeds": [int(s) for s in seeds],
        "summary": {
            "episodes_total": int(len(seeds) * n_episodes),
            "mean_pue_constant": means["constant"],
            "mean_pue_rule": means["rule"],
            "mean_pue_difference_rule_minus_constant": float(np.mean(diffs)),
        },
        "tables": {
            "per_seed": {
                "title": "Mean PUE and water per seed",
                "columns": ["seed", "policy", "mean_pue", "mean_water"],
                "rows": per_seed_rows,
            },
            "policy_summary": {
                "title": "Policy summary across seeds",
                "columns": ["policy", "mean_pue", "std_pue_across_seeds", "mean_water"],
                "rows": summary_rows,
            },
            "paired_difference": {
                "title": "Paired PUE difference, rule minus constant",
                "columns": ["episodes", "mean_difference", "std_difference", "episodes_rule_better"],
                "rows": paired,
            },
        },
        "figures": {
            "mean_pue_by_policy": {
                "type": "bar",
                "title": "Mean PUE by policy",
                "x_label": "policy",
                "y_label": "mean PUE",
                "x": [r[0] for r in summary_rows],
                "series": {"mean_pue": [r[1] for r in summary_rows]},
            },
            "pue_by_seed": {
                "type": "line",
                "title": "Mean PUE per seed",
                "x_label": "seed",
                "y_label": "mean PUE",
                "x": [str(s) for s in seeds],
                "series": {p.name: [seed_mean(p.name, s, 0) for s in seeds] for p in policies},
            },
        },
        "notes": [
            "Synthetic scenarios and a made-up cooling formula; this experiment only exercises the reproducibility framework."
        ],
    }
