"""Evaluate the four tuned baselines on the held-out TEST scenarios and build the T24 ``results.json``.

``baselines_experiment(root)`` returns an experiment function for the T24 framework
(``src.repro.experiments.register``): ``fn(config, seeds, rng_factory) -> results``. It

1. loads the pre-registered evaluation config (hash-verified) and builds the scenario sets with the
   existing generator (``policy_evaluation.build_scenarios``; not modified here);
2. loads the four baseline configs and REFUSES stale ones: a lineage field (physics / environment /
   reward / envelope / action semantics / schema hashes / cadence) that differs from the running code, a
   different evaluation config, a different validation scenario set or a different carbon curve means the
   baseline was tuned somewhere else;
3. runs every FEASIBLE baseline on the same test scenarios and asserts the scenario-input hash is
   identical across policies; an infeasible baseline is reported as infeasible and is not run;
4. returns tables, figures and per-scenario numbers in the results schema; tables, figures and REPORT.md
   are then generated from it by ``src/repro/report.py`` and nothing else.

Nothing here reads the clock or a random generator; the environments are seeded per scenario.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from .. import policy_evaluation as pe
from ..repro import RESULTS_SCHEMA
from ..repro.canonical import sha256_input_file
from . import config as bcfg
from . import tuning

EXPERIMENT_NAME = "baselines"
EVALUATION_SCHEMA = "twingrid-baselines-run/1"
CLAIM_ALLOWED = "Four deterministic baselines tuned on validation are evaluated on held-out scenarios."
CLAIM_NOT_ALLOWED = "Optimal control; any statement about PPO versus MPC."


class BaselineRunError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- inputs


def evaluation_document(
    eval_cfg: pe.EvalConfig,
    *,
    directory: str = bcfg.CONFIG_DIR,
    prereg: str = "reports/policy_evaluation/PREREGISTRATION.json",
) -> dict[str, Any]:
    """Content of ``configs/baselines/evaluation.json`` (the primary config of the T24 run)."""
    test = pe.build_scenarios(eval_cfg)["test"]
    return {
        "schema": EVALUATION_SCHEMA,
        "experiment": EXPERIMENT_NAME,
        "description": "Deterministic baselines v2 evaluated on the held-out test scenarios of the pre-registered evaluation config",
        "preregistration": prereg,
        "baseline_configs": {n: f"{directory}/{n}.json" for n in bcfg.BASELINE_NAMES},
        "seeds": sorted({s.seed for s in test}),
    }


def carbon_info(curve: np.ndarray, is_real: bool) -> dict[str, Any]:
    from ..carbon_provider import CLEANED_CARBON_PATH

    source = sha256_input_file(CLEANED_CARBON_PATH) if is_real and Path(CLEANED_CARBON_PATH).is_file() else None
    return {
        "is_real": bool(is_real),
        "flat_curve": bool(np.ptp(curve) == 0),
        "curve_sha256": tuning.curve_sha256(curve),
        "source_sha256": source,
    }


def scenario_input_hash(results: Sequence[pe.EpisodeResult]) -> str:
    """One hash over (scenario id, exogenous trace hash) for a whole policy run."""
    h = hashlib.sha256()
    for r in results:
        h.update(f"{r.scenario_id}:{r.exogenous_hash}\n".encode())
    return h.hexdigest()


def load_baselines(
    root: Path,
    paths: dict[str, str],
    eval_cfg: pe.EvalConfig,
    validation: Sequence[pe.Scenario],
    carbon_sha: str,
) -> dict[str, dict[str, Any]]:
    """The four configs, each checked against the running code and scenarios (raises BaselineConfigStale)."""
    if set(paths) != set(bcfg.BASELINE_NAMES):
        raise BaselineRunError(f"the evaluation config must list exactly the baselines {list(bcfg.BASELINE_NAMES)}")
    ids = [s.scenario_id for s in validation]
    val_set, eval_sha = pe.scenario_set_id(validation), pe.config_sha256(eval_cfg)
    out = {}
    for name in bcfg.BASELINE_NAMES:
        cfg = bcfg.load_config(Path(root) / paths[name], name)
        bcfg.check_lineage(cfg)
        bcfg.check_tuning_scenarios(cfg, ids, val_set, eval_sha, carbon_sha)
        out[name] = cfg
    return out


# ----------------------------------------------------------------------------- evaluation


def _validation_reward(cfg: dict[str, Any]) -> float | str:
    r = cfg["tuning"]["result"]
    value = r.get("validation_reward_closed_loop", r.get("validation_reward"))
    return "n/a" if value is None else float(value)


def _validation_violations(cfg: dict[str, Any]) -> int | str:
    r = cfg["tuning"]["result"]
    if cfg["name"] in ("rule", "lookup"):
        return int(sum(r["validation_violation_steps"].values()))
    least = r["least_violating"] if cfg["status"] == "infeasible" else None
    return int(sum(least["violation_steps"].values())) if least else 0


def evaluate_baselines(
    eval_cfg: pe.EvalConfig,
    configs: dict[str, dict[str, Any]],
    test: Sequence[pe.Scenario],
    carbon: np.ndarray,
    carbon_meta: dict[str, Any],
    validation: Sequence[pe.Scenario],
) -> dict[str, Any]:
    if any(s.split != "test" for s in test):
        raise BaselineRunError("the evaluation runs on test scenarios only")
    family_of = {s.scenario_id: s.family for s in test}
    families = [f.name for f in eval_cfg.families]
    runnable = [n for n in bcfg.BASELINE_NAMES if configs[n]["status"] == "feasible"]
    by_policy: dict[str, list[pe.EpisodeResult]] = {}
    for name in runnable:
        by_policy[name] = pe.evaluate_policy(bcfg.build_policy(configs[name]), test, eval_cfg, carbon)
    if len(by_policy) > 1:
        pe.assert_identical_scenarios(by_policy)  # same ids, same order, same exogenous trace, for every policy
    hashes = {n: scenario_input_hash(r) for n, r in by_policy.items()}
    if len(set(hashes.values())) > 1:
        raise AssertionError(f"scenario-input hash differs between policies: {hashes}")
    input_hash = next(iter(hashes.values()), None)

    def mean(name: str, metric: str, subset: str | None = None) -> float:
        rows = [r for r in by_policy[name] if subset is None or family_of[r.scenario_id] == subset]
        return float(np.mean([r.metrics[metric] for r in rows]))

    metrics = list(pe.METRICS)
    tables = {
        "baselines": {
            "title": "Baselines: tuning outcome on validation",
            "columns": ["baseline", "status", "validation_reward", "validation_violation_steps", "parameters"],
            "rows": [
                [
                    n,
                    configs[n]["status"],
                    _validation_reward(configs[n]),
                    _validation_violations(configs[n]),
                    bcfg.describe_parameters(configs[n]),
                ]
                for n in bcfg.BASELINE_NAMES
            ],
        },
        "test_summary": {
            "title": "Held-out test scenarios: mean per episode",
            "columns": ["baseline", *metrics],
            "rows": [[n, *[mean(n, m) for m in metrics]] for n in runnable],
        },
        "test_reward_by_family": {
            "title": "Held-out test scenarios: mean total reward by scenario family",
            "columns": ["baseline", *families],
            "rows": [[n, *[mean(n, pe.PRIMARY_METRIC, f) for f in families]] for n in runnable],
        },
    }
    figures: dict[str, Any] = {}
    if runnable:
        figures["test_mean_reward"] = {
            "type": "bar",
            "title": "Mean test reward by baseline",
            "x_label": "baseline",
            "y_label": "mean total reward (higher is better)",
            "x": runnable,
            "series": {"total_reward": [mean(n, "total_reward") for n in runnable]},
        }
        figures["test_mean_energy"] = {
            "type": "bar",
            "title": "Mean test facility energy by baseline",
            "x_label": "baseline",
            "y_label": "energy per episode, kWh (lower is better)",
            "x": runnable,
            "series": {"energy_kwh": [mean(n, "energy_kwh") for n in runnable]},
        }
    summary: dict[str, Any] = {
        "validation_scenarios": len(validation),
        "test_scenarios": len(test),
        "baselines_evaluated": len(runnable),
        "baselines_infeasible": len(bcfg.BASELINE_NAMES) - len(runnable),
    }
    summary.update({f"mean_test_reward_{n}": mean(n, "total_reward") for n in runnable})
    notes = [
        CLAIM_ALLOWED,
        "Not optimal control: the grids and bins are coarse and everything is tuned and evaluated inside the simulator.",
        "MPC is not implemented (contract section 13.8): a perfect-model controller would be an oracle upper bound, not a deployable baseline.",
        "All four use the same actuator limits, the same environment, scenarios and envelope; the scenario-input hash is identical across policies.",
    ]
    lookup = configs["lookup"]["tuning"]["result"]
    if lookup.get("improves_on_best_constant") is False:
        notes.append(
            "On validation the lookup table did not improve on the best constant over the same action grid; the exhaustive per-bin search kept the constant action in the bins it filled."
        )
    for n in bcfg.BASELINE_NAMES:
        if configs[n]["status"] == "infeasible":
            notes.append(
                f"{n} is infeasible on validation and was not evaluated on the test set: {configs[n]['infeasible_reason']}"
            )
    return {
        "schema": RESULTS_SCHEMA,
        "experiment": EXPERIMENT_NAME,
        "title": "Deterministic baselines v2: held-out evaluation",
        "seeds": sorted({s.seed for s in test}),
        "summary": summary,
        "tables": tables,
        "figures": figures,
        "notes": notes,
        "claims": {"allowed": CLAIM_ALLOWED, "not_allowed": CLAIM_NOT_ALLOWED},
        "scenario_sets": {
            "validation": {"id": pe.scenario_set_id(validation), "n": len(validation)},
            "test": {"id": pe.scenario_set_id(test), "n": len(test)},
        },
        "scenario_input_hash": input_hash,
        "scenario_input_hash_by_policy": hashes,
        "carbon": carbon_meta,
        "tuner_version": configs[bcfg.BASELINE_NAMES[0]]["tuner_version"],
        "per_scenario_test": {
            n: [{"scenario_id": r.scenario_id, "family": family_of[r.scenario_id], **r.metrics} for r in by_policy[n]]
            for n in runnable
        },
    }


# ----------------------------------------------------------------------------- T24 experiment


def baselines_experiment(root: Path) -> Callable[[dict[str, Any], list[int], Callable[..., Any]], dict[str, Any]]:
    root = Path(root)

    def run(config: dict[str, Any], seeds: list[int], rng_factory: Callable[..., Any]) -> dict[str, Any]:
        if config.get("schema") != EVALUATION_SCHEMA:
            raise BaselineRunError(f"the primary config must be a {EVALUATION_SCHEMA} document")
        prereg = root / config["preregistration"]
        eval_cfg = pe.load_preregistered_config(prereg.parent)  # verifies the pre-registration hash
        scenarios = pe.build_scenarios(eval_cfg)
        pe.assert_disjoint(eval_cfg, scenarios)
        validation, test = scenarios["validation"], scenarios["test"]
        if sorted(seeds) != sorted({s.seed for s in test}) or sorted(config["seeds"]) != sorted(seeds):
            raise BaselineRunError(
                "the run seeds must be exactly the test-scenario seeds of the pre-registered evaluation config"
            )
        curve, is_real = pe.load_diurnal_carbon_intensity()
        curve = np.asarray(curve, dtype=float)
        meta = carbon_info(curve, is_real)
        configs = load_baselines(root, config["baseline_configs"], eval_cfg, validation, meta["curve_sha256"])
        return evaluate_baselines(eval_cfg, configs, test, curve, meta, validation)

    return run


def register(root: Path) -> None:
    """Make ``baselines`` runnable through the T24 framework (replaces an earlier registration, e.g. for another root)."""
    from ..repro import experiments

    experiments.register(EXPERIMENT_NAME, baselines_experiment(root), replace=True)


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
