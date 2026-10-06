"""``configs/baselines/<name>.json``: parameters, tuning scenario IDs, tuner version, lineage (contract 13.8).

A baseline is fully determined by its config: ``build_policy(config)`` needs nothing else, so the same
config always gives the same policy. Configs are canonical JSON (``src.repro.canonical``) and are
passed to the T24 run as ``--config`` files, so their SHA-256 lands in the run manifest.

Schema ``twingrid-baseline-config/1``::

    {"schema", "name", "config_version", "tuner_version",
     "status": "feasible" | "infeasible", "infeasible_reason": str | null,
     "parameters": {...per baseline...},
     "tuning": {"split": "validation", "scenario_set_id", "scenario_ids": [...], "eval_config_sha256",
                "objective", "feasibility_rule", "search_space": {...}, "result": {...}},
     "lineage": {physics_version, physics_params_hash, environment_version, observation_schema_hash,
                 action_schema_hash, action_semantics_version, reward_version, safety_envelope_version,
                 input_cadence_s}}

``lineage`` is the T19 version record the tuning ran against. ``check_lineage`` refuses a config whose
lineage differs from the running code: a baseline tuned in an old environment must not be compared with
a policy trained in the new one (F-26), so it fails loudly until it is re-tuned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import versions
from ..repro.canonical import canonical_dumps, sha256_input_file
from .policies import ConstantPolicy, LookupPolicy, PIDPolicy, RulePolicy

SCHEMA = "twingrid-baseline-config/1"
CONFIG_VERSION = 1
BASELINE_NAMES = ("rule", "constant", "lookup", "pid")
CONFIG_DIR = "configs/baselines"
EVALUATION_CONFIG = f"{CONFIG_DIR}/evaluation.json"
STATUSES = ("feasible", "infeasible")
LINEAGE_FIELDS = versions.COMPAT_FIELDS


class BaselineConfigError(ValueError):
    """A baseline config is malformed."""


class BaselineConfigStale(BaselineConfigError):
    """The config was tuned against different code or scenarios than the ones running now."""

    def __init__(self, field: str, expected: Any, actual: Any) -> None:
        super().__init__(
            f"{field}: config records {actual!r} but the running code/scenarios have {expected!r}; re-tune the baselines"
        )
        self.field, self.expected, self.actual = field, expected, actual


def running_lineage() -> dict[str, Any]:
    values = versions.running_compat_values()
    return {k: values[k] for k in LINEAGE_FIELDS}


def config_path(name: str, root: Path, directory: str = CONFIG_DIR) -> Path:
    if name not in BASELINE_NAMES:
        raise BaselineConfigError(f"unknown baseline {name!r}; known: {', '.join(BASELINE_NAMES)}")
    return Path(root) / directory / f"{name}.json"


def validate(cfg: Any, name: str | None = None) -> None:
    if not isinstance(cfg, dict) or cfg.get("schema") != SCHEMA:
        raise BaselineConfigError(f"not a {SCHEMA} document")
    if cfg.get("name") not in BASELINE_NAMES or (name is not None and cfg["name"] != name):
        raise BaselineConfigError(f"config name {cfg.get('name')!r} does not match {name!r}")
    if cfg.get("config_version") != CONFIG_VERSION:
        raise BaselineConfigError("unsupported config_version")
    if not isinstance(cfg.get("tuner_version"), str) or not cfg["tuner_version"]:
        raise BaselineConfigError("tuner_version is required")
    if cfg.get("status") not in STATUSES:
        raise BaselineConfigError(f"status must be one of {STATUSES}")
    if cfg["status"] == "infeasible" and not cfg.get("infeasible_reason"):
        raise BaselineConfigError("an infeasible baseline must say why")
    if not isinstance(cfg.get("parameters"), dict):
        raise BaselineConfigError("parameters must be an object")
    tuning = cfg.get("tuning")
    if not isinstance(tuning, dict) or tuning.get("split") != "validation":
        raise BaselineConfigError("tuning.split must be 'validation': baselines are tuned on validation scenarios only")
    ids = tuning.get("scenario_ids")
    if not (isinstance(ids, list) and ids and all(isinstance(i, str) for i in ids)):
        raise BaselineConfigError("tuning.scenario_ids must list the validation scenario ids")
    if any("/test/" in i for i in ids):
        raise BaselineConfigError("tuning.scenario_ids contains a test scenario")
    for key in ("scenario_set_id", "eval_config_sha256", "objective", "feasibility_rule"):
        if not isinstance(tuning.get(key), str) or not tuning[key]:
            raise BaselineConfigError(f"tuning.{key} is required")
    carbon = tuning.get("carbon")
    if not (isinstance(carbon, dict) and isinstance(carbon.get("curve_sha256"), str)):
        raise BaselineConfigError("tuning.carbon.curve_sha256 is required (the carbon curve is an input of tuning)")
    lineage = cfg.get("lineage")
    if not isinstance(lineage, dict) or set(lineage) != set(LINEAGE_FIELDS):
        raise BaselineConfigError(f"lineage must have exactly the fields {list(LINEAGE_FIELDS)}")


def make_config(
    name: str,
    *,
    parameters: dict[str, Any],
    tuning: dict[str, Any],
    status: str,
    infeasible_reason: str | None,
    tuner_version: str,
) -> dict[str, Any]:
    cfg = {
        "schema": SCHEMA,
        "name": name,
        "config_version": CONFIG_VERSION,
        "tuner_version": tuner_version,
        "status": status,
        "infeasible_reason": infeasible_reason,
        "parameters": parameters,
        "tuning": {"split": "validation", **tuning},
        "lineage": running_lineage(),
    }
    validate(cfg, name)
    return cfg


def write_config(cfg: dict[str, Any], path: Path) -> str:
    """Write canonically (atomic); returns the file's input SHA-256."""
    from ..repro.run import write_atomic

    validate(cfg)
    write_atomic(Path(path), canonical_dumps(cfg).encode("ascii"))
    return sha256_input_file(Path(path))


def load_config(path: Path, name: str | None = None) -> dict[str, Any]:
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BaselineConfigError(f"{Path(path).name} not found; run `python -m src.baselines.cli tune`") from None
    except ValueError:
        raise BaselineConfigError(f"{Path(path).name} is not valid JSON") from None
    validate(cfg, name)
    return cfg


def check_lineage(cfg: dict[str, Any]) -> None:
    """Raise BaselineConfigStale naming the first lineage field that differs from the running code."""
    running = running_lineage()
    for field in LINEAGE_FIELDS:
        if cfg["lineage"][field] != running[field]:
            raise BaselineConfigStale(f"lineage.{field}", running[field], cfg["lineage"][field])


def check_tuning_scenarios(
    cfg: dict[str, Any], validation_ids: list[str], validation_set_id: str, eval_config_sha: str, carbon_curve_sha: str
) -> None:
    """The config must have been tuned on exactly these validation scenarios under this evaluation config."""
    tuning = cfg["tuning"]
    if tuning["eval_config_sha256"] != eval_config_sha:
        raise BaselineConfigStale("tuning.eval_config_sha256", eval_config_sha, tuning["eval_config_sha256"])
    if tuning["carbon"]["curve_sha256"] != carbon_curve_sha:
        raise BaselineConfigStale("tuning.carbon.curve_sha256", carbon_curve_sha, tuning["carbon"]["curve_sha256"])
    if tuning["scenario_set_id"] != validation_set_id:
        raise BaselineConfigStale("tuning.scenario_set_id", validation_set_id, tuning["scenario_set_id"])
    if list(tuning["scenario_ids"]) != list(validation_ids):
        raise BaselineConfigStale(
            "tuning.scenario_ids", f"{len(validation_ids)} ids", f"{len(tuning['scenario_ids'])} ids"
        )


def build_policy(cfg: dict[str, Any]) -> Any:
    """The policy a config describes. Pure function of ``cfg['parameters']``."""
    p, name = cfg["parameters"], cfg["name"]
    try:
        if name == "rule":
            return RulePolicy(float(p["chilled_C"]))
        if name == "constant":
            sel = p["selected"]
            if sel is None:
                raise BaselineConfigError("the constant baseline is infeasible and has no selected action")
            return ConstantPolicy(float(sel["chilled_C"]), str(sel["mode"]), name="best_constant")
        if name == "lookup":
            table = [[(c["chilled_C"], c["mode"]) for c in row] for row in p["table"]]
            return LookupPolicy(p["util_edges"], p["temp_edges"], table, name="lookup")
        if name == "pid":
            g = p["selected_gains"]
            if g is None:
                raise BaselineConfigError("the pid baseline is infeasible and has no selected gains")
            return PIDPolicy(
                target_inlet_C=float(p["target_inlet_C"]),
                kp=float(g["kp"]),
                ki=float(g["ki"]),
                kd=float(g["kd"]),
                nominal_setpoint_C=float(p["nominal_setpoint_C"]),
                initial_setpoint_C=float(p["initial_setpoint_C"]),
                min_setpoint_C=float(p["min_setpoint_C"]),
                max_setpoint_C=float(p["max_setpoint_C"]),
                max_rate_C_per_step=float(p["max_rate_C_per_step"]),
                mode_rule=str(p["mode_rule"]),
                anti_windup=bool(p["anti_windup"]),
                name="pid",
            )
    except KeyError as exc:
        raise BaselineConfigError(f"{name}: parameters.{exc.args[0]} is missing") from None
    raise BaselineConfigError(f"unknown baseline {name!r}")


def describe_parameters(cfg: dict[str, Any]) -> str:
    """One-line human description of what a config tuned to (used by the report)."""
    p, name = cfg["parameters"], cfg["name"]
    if cfg["status"] == "infeasible":
        return f"INFEASIBLE on validation: {cfg['infeasible_reason']}"
    if name == "rule":
        return f"production mode rule at {p['chilled_C']:g} C"
    if name == "constant":
        s = p["selected"]
        return f"{s['chilled_C']:g} C, {s['mode']}"
    if name == "lookup":
        cells = sum(len(r) for r in p["table"])
        fb = sum(1 for r in p["table"] for c in r if c["source"] == "fallback")
        return f"{len(p['util_edges']) + 1} x {len(p['temp_edges']) + 1} bins ({cells} cells, {fb} fallback)"
    g = p["selected_gains"]
    return f"target inlet {p['target_inlet_C']:g} C, kp={g['kp']:g}, ki={g['ki']:g}, kd={g['kd']:g}, mode rule {p['mode_rule']}"
