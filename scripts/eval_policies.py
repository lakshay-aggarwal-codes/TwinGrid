#!/usr/bin/env python3
"""Frozen-policy robustness evaluation and promotion decision (T30, roadmap 13.5 / 13.9 / 11).

    python scripts/eval_policies.py prereg --write          # create + hash the pre-registration (BEFORE any run)
    python scripts/eval_policies.py prereg --verify         # recompute and compare the hash
    python scripts/eval_policies.py run --candidates-dir models/optimizer_candidates [--model-id <registry id>]
    python scripts/eval_policies.py run --baselines-only    # baselines and perturbations, no PPO: outcome NOT_EVALUATED
    python scripts/eval_policies.py report  reports/runs/<run_id>   # regenerate tables/figures/REPORT.md from results.json
    python scripts/eval_policies.py verify  reports/runs/<run_id>   # regenerate and diff: must be byte-identical

What a run does
---------------
1. Verifies the pre-registration (configs/prereg/prereg_v2.json) against its lock and the perturbation manifest against
   the hash the pre-registration pins. A mismatch STOPS the run.
2. Builds the pre-registered scenario sets and refuses to continue if any evaluation seed touches training
   (reserved range, the candidate's recorded training seeds / scenario ids, or outside the split's test range).
3. Runs the T8 harness (src/policy_evaluation.py, frozen) on the unperturbed test scenarios: validation-selected best
   constant, validation-selected PPO seed, A / B / C outcome.
4. Re-runs the SAME test scenarios for the rule baseline, the validation-selected best constant and the selected
   candidate under every listed perturbation (one at a time, plus the pre-listed joint sets). Nothing is retrained,
   retuned or re-thresholded; file hashes of the candidate are compared before and after.
5. Applies the pre-registered robustness criteria, then writes ``reports/runs/<run_id>/``: manifest.json, status.json,
   PREREGISTRATION.json, results.json, decision.json, tables/*.csv, figures/*.svg, REPORT.md. Every number in the
   tables, figures and REPORT.md is produced from results.json by ``render_*`` below.

Perturbations are applied by temporarily changing the physics module's own parameters (and restoring them), so no
physics file is edited. PhysicsParams (T21-T23) does not exist in this tree, so the manifest's ``parameter`` names
are mapped to the current implementation's knobs in ``PATCHERS``; a parameter with no counterpart is recorded as
``not_applicable``. Interpretation limit: "robust to these listed perturbations in this simulator".
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PREREG_PATH = REPO_ROOT / "configs" / "prereg" / "prereg_v2.json"
PREREG_LOCK_PATH = REPO_ROOT / "configs" / "prereg" / "prereg_v2.lock.json"
PERTURBATIONS_PATH = REPO_ROOT / "configs" / "robustness" / "perturbations_v2.json"
SPLIT_PATH = REPO_ROOT / "configs" / "splits" / "split_v2.json"
RUNS_DIR = REPO_ROOT / "reports" / "runs"

BASIS_STRESS = "stress-test:no empirical basis"
MODES = ("multiplicative", "additive", "set")
SCHEMA = 1
NO_PROMOTABLE = "no promotable policy"
PRIMARY = "total_reward"
ENVELOPE_METRICS = ("outlet_violation_steps", "inlet_over_max_steps")
POLICIES = ("rule", "best_constant", "candidate")
FLOAT_DECIMALS = 9


class EvalProtocolError(RuntimeError):
    """A protocol rule was violated. The run stops; nothing is evaluated or written as a result."""


# ----------------------------------------------------------------------------- canonical JSON and hashing
def round_floats(obj: Any, ndigits: int = FLOAT_DECIMALS) -> Any:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise EvalProtocolError("non-finite number in a result")
        return round(obj, ndigits) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(obj, Mapping):
        return {str(k): round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, ndigits) for v in obj]
    if isinstance(obj, (np.floating,)):
        return round_floats(float(obj), ndigits)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def pretty_json(obj: Any) -> str:
    return json.dumps(round_floats(obj), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def prereg_hash(doc: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the pre-registration, ``preregistration_sha256`` itself excluded."""
    return sha256_text(canonical_json({k: v for k, v in doc.items() if k != "preregistration_sha256"}))


def manifest_hash(doc: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json(doc))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# ----------------------------------------------------------------------------- bootstrap CI
def bootstrap_paired_ci(
    candidate: Sequence[float],
    baseline: Sequence[float],
    *,
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> dict[str, float]:
    """Percentile bootstrap CI of the mean paired difference ``candidate - baseline``, resampling SCENARIOS (pairs).

    Deterministic: the resampling indices come from ``numpy.random.default_rng(seed)`` (no global RNG)."""
    a, b = np.asarray(candidate, dtype=float), np.asarray(baseline, dtype=float)
    if a.shape != b.shape or a.ndim != 1:
        raise ValueError("paired samples must be 1-D and of equal length")
    n = int(a.size)
    if n < 2:
        raise ValueError("need at least 2 pairs for a bootstrap CI")
    if not 0.0 < confidence < 1.0 or n_resamples < 100:
        raise ValueError("confidence must be in (0, 1) and n_resamples >= 100")
    d = a - b
    rng = np.random.default_rng(np.random.SeedSequence([int(seed)]))
    idx = rng.integers(0, n, size=(int(n_resamples), n))
    means = d[idx].mean(axis=1)
    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.quantile(means, [alpha, 1.0 - alpha])
    return {
        "n": n,
        "mean": float(d.mean()),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "confidence": float(confidence),
        "n_resamples": int(n_resamples),
        "method": "paired percentile bootstrap over scenarios",
    }


# ----------------------------------------------------------------------------- perturbation manifest
def validate_perturbation_manifest(doc: Mapping[str, Any]) -> None:
    """Contract: every entry is ``{id, parameter, mode, value, applies_to, basis}`` with ``basis`` either
    ``empirical:<source>`` or exactly ``stress-test:no empirical basis``; ids are unique; joint sets use known ids."""
    entries = doc.get("perturbations")
    if not isinstance(entries, list) or not entries:
        raise EvalProtocolError("perturbation manifest has no 'perturbations' list")
    seen: set[str] = set()
    for e in entries:
        missing = {"id", "parameter", "mode", "value", "applies_to", "basis"} - set(e)
        if missing:
            raise EvalProtocolError(f"perturbation {e.get('id')!r} lacks {sorted(missing)}")
        _check_entry(e)
        if e["id"] in seen:
            raise EvalProtocolError(f"duplicate perturbation id {e['id']!r}")
        seen.add(e["id"])
    joint_ids: set[str] = set()
    for j in doc.get("joint_sets", []):
        if j["id"] in seen or j["id"] in joint_ids:
            raise EvalProtocolError(f"joint set id {j['id']!r} collides with another id")
        joint_ids.add(j["id"])
        unknown = [m for m in j["members"] if m not in seen]
        if unknown or len(j["members"]) < 2:
            raise EvalProtocolError(f"joint set {j['id']!r} needs >= 2 known members (unknown: {unknown})")
        _check_basis(j["id"], j.get("basis"))


def _check_basis(pid: str, basis: Any) -> None:
    if basis == BASIS_STRESS:
        return
    if isinstance(basis, str) and re.fullmatch(r"empirical:\S.*", basis):
        return
    raise EvalProtocolError(f"{pid}: basis must be 'empirical:<source>' or {BASIS_STRESS!r}, got {basis!r}")


def _check_entry(e: Mapping[str, Any]) -> None:
    _check_basis(e["id"], e["basis"])
    if e["mode"] not in MODES:
        raise EvalProtocolError(f"{e['id']}: mode must be one of {MODES}")
    if not isinstance(e["value"], (int, float)) or isinstance(e["value"], bool) or not math.isfinite(e["value"]):
        raise EvalProtocolError(f"{e['id']}: value must be a finite number")
    if e["mode"] == "multiplicative" and e["value"] <= 0:
        raise EvalProtocolError(f"{e['id']}: a multiplicative value must be > 0")
    if not isinstance(e["applies_to"], list) or not e["applies_to"]:
        raise EvalProtocolError(f"{e['id']}: applies_to must be a non-empty list")


def expand_perturbations(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One-at-a-time entries followed by the pre-listed joint sets, as ``{id, kind, entries}``."""
    by_id = {e["id"]: e for e in doc["perturbations"]}
    out = [{"id": e["id"], "kind": "single", "entries": [e]} for e in doc["perturbations"]]
    out += [
        {"id": j["id"], "kind": "joint", "entries": [by_id[m] for m in j["members"]]} for j in doc.get("joint_sets", [])
    ]
    return out


# ----------------------------------------------------------------------------- applying perturbations
def _op(base: float, mode: str, value: float) -> float:
    if mode == "multiplicative":
        return base * value
    if mode == "additive":
        return base + value
    return value


class _Ctx:
    def __init__(self) -> None:
        self.undo: list[Callable[[], None]] = []
        self.twin_kwargs: dict[str, float] = {}


def _patch_dict(ctx: _Ctx, mapping: dict, key: Any, mode: str, value: float) -> None:
    old = mapping[key]
    mapping[key] = _op(old, mode, value)
    ctx.undo.append(lambda: mapping.__setitem__(key, old))


def _patch_attr(ctx: _Ctx, module: Any, name: str, mode: str, value: float) -> None:
    old = getattr(module, name)
    setattr(module, name, _op(old, mode, value))
    ctx.undo.append(lambda: setattr(module, name, old))


def _p_cop(ctx: _Ctx, e: Mapping[str, Any]) -> None:
    from src import digital_twin as dt

    mode_name = e["parameter"].split(".", 1)[1]
    _patch_dict(ctx, dt._BASE_COP, dt.CoolingMode(mode_name), e["mode"], e["value"])


def _p_capacity(ctx: _Ctx, e: Mapping[str, Any]) -> None:
    from src import digital_twin as dt

    _patch_attr(ctx, dt, "COOLING_CAPACITY_MARGIN", e["mode"], e["value"])


def _p_idle(ctx: _Ctx, e: Mapping[str, Any]) -> None:
    from src.rl import env as opt  # the env reads its own module globals; src.optimizer only re-exports them

    _patch_attr(ctx, opt, "IDLE_FRAC", e["mode"], e["value"])


def _p_tau(ctx: _Ctx, e: Mapping[str, Any]) -> None:
    from src import digital_twin as dt

    ctx.twin_kwargs["thermal_time_constant_min"] = _op(dt.DEFAULT_THERMAL_TIME_CONSTANT_MIN, e["mode"], e["value"])


def _p_rate(ctx: _Ctx, e: Mapping[str, Any]) -> None:
    from src import digital_twin as dt

    ctx.twin_kwargs["max_chilled_water_rate_C_per_step"] = _op(
        dt.DEFAULT_MAX_CHILLED_WATER_RATE_C_PER_STEP, e["mode"], e["value"]
    )


def _p_humidity(ctx: _Ctx, e: Mapping[str, Any]) -> None:
    from src import digital_twin as dt

    _patch_attr(ctx, dt, "WATER_HUMIDITY_FACTOR_PER_PCT", e["mode"], e["value"])


def _p_evap(ctx: _Ctx, e: Mapping[str, Any]) -> None:
    from src import digital_twin as dt

    for table in (dt._EVAPORATIVE_HEAT_FRACTION, dt._EVAPORATION_RATE):  # v1 and legacy-0 water models
        _patch_dict(ctx, table, dt.CoolingMode.EVAPORATIVE, e["mode"], e["value"])


# parameter (or "<parameter>." prefix) -> patcher. C_th and actuator_lag have no counterpart in physics v1.
PATCHERS: dict[str, Callable[[_Ctx, Mapping[str, Any]], None]] = {
    "cop_base.": _p_cop,
    "capacity_margin": _p_capacity,
    "idle_fraction": _p_idle,
    "tau_air": _p_tau,
    "actuator_rate": _p_rate,
    "humidity_coefficient": _p_humidity,
    "evaporative_water_coefficient": _p_evap,
}
COP_MODES = ("free_air", "closed_loop", "evaporative", "hybrid")


def _patcher_for(parameter: str) -> Callable[[_Ctx, Mapping[str, Any]], None] | None:
    if parameter.startswith("cop_base."):
        return PATCHERS["cop_base."] if parameter.split(".", 1)[1] in COP_MODES else None
    return PATCHERS.get(parameter)


def not_applicable_reason(entries: Sequence[Mapping[str, Any]]) -> str | None:
    """Why this perturbation cannot be applied to the current physics, or None. Pure (no physics import)."""
    bad = [e["parameter"] for e in entries if _patcher_for(e["parameter"]) is None]
    if not bad:
        return None
    return f"no counterpart in the current physics for: {', '.join(sorted(set(bad)))}"


@contextlib.contextmanager
def perturbed(entries: Sequence[Mapping[str, Any]]) -> Iterator[None]:
    """Apply ``entries`` to the physics for the duration of the block, then restore everything exactly."""
    reason = not_applicable_reason(entries)
    if reason:
        raise EvalProtocolError(reason)
    ctx = _Ctx()
    try:
        for e in entries:
            _patcher_for(e["parameter"])(ctx, e)  # type: ignore[misc]
        if ctx.twin_kwargs:
            from src.rl import env as opt  # DataCentreEnv builds its twin from THIS module's DigitalTwin

            base, forced = opt.DigitalTwin, dict(ctx.twin_kwargs)

            class PerturbedTwin(base):  # type: ignore[valid-type, misc]
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    kwargs.update(forced)
                    super().__init__(*args, **kwargs)

            opt.DigitalTwin = PerturbedTwin
            ctx.undo.append(lambda: setattr(opt, "DigitalTwin", base))
        yield
    finally:
        for undo in reversed(ctx.undo):
            undo()


# ----------------------------------------------------------------------------- pre-registration
def load_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def default_robustness_criteria() -> dict[str, Any]:
    """The criteria frozen in the pre-registration (numbers are PROPOSED; the owner reviews them before the first run)."""
    return {
        "R1_envelope": {
            "description": "Under every perturbation the candidate's envelope-violation steps (outlet over limit + inlet "
            "over max, summed over test scenarios) do not exceed the LOWER of the two baselines' by more than the allowance.",
            "metrics": list(ENVELOPE_METRICS),
            "max_extra_violation_steps": 0,
        },
        "R2_noninferiority": {
            "description": "Under every perturbation, for BOTH baselines, the lower bound of the bootstrap CI of the paired "
            "primary-metric difference (candidate - baseline) is above -margin x |baseline's unperturbed mean primary metric|.",
            "metric": PRIMARY,
            "margin_rel": 0.05,
        },
        "R3_degradation": {
            "description": "Under every perturbation the candidate's relative degradation of the primary metric (vs its own "
            "unperturbed mean) exceeds the larger baseline degradation by no more than the allowance.",
            "metric": PRIMARY,
            "max_extra_relative_degradation": 0.05,
        },
        "R4_completeness": {
            "description": "Every perturbation in the manifest was either evaluated or recorded as not_applicable with a reason, "
            "and at least one one-at-a-time and one joint perturbation were evaluated.",
        },
    }


def build_prereg(*, registered_at_utc: str | None = None) -> dict[str, Any]:
    """The pre-registration document (hash not yet attached). Needs src.policy_evaluation (EvalConfig)."""
    from src import policy_evaluation as pe
    from src import versions

    cfg = pe.EvalConfig(physics_version=versions.PHYSICS_VERSION)
    manifest = load_json(PERTURBATIONS_PATH)
    validate_perturbation_manifest(manifest)
    return {
        "schema": SCHEMA,
        "name": "T30 robustness evaluation and promotion decision",
        "protocol": "roadmap 13.5 (outcome A/B/C) and 13.9 (physics-mismatch robustness)",
        "registered_at_utc": registered_at_utc or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status_note": "PROPOSED thresholds: the owner must review every number below BEFORE the first evaluation; "
        "any later change invalidates the hash and stops the run.",
        "eval_config": cfg.to_json(),
        "outcome_rules": pe.OUTCOME_RULES,
        "perturbation_manifest": {
            "path": PERTURBATIONS_PATH.relative_to(REPO_ROOT).as_posix(),
            "sha256": manifest_hash(manifest),
            "n_single": len(manifest["perturbations"]),
            "n_joint": len(manifest.get("joint_sets", [])),
        },
        "bootstrap": {"n_resamples": 10_000, "seed": 20260101, "confidence": cfg.confidence},
        "robustness_criteria": default_robustness_criteria(),
        "promotion": {
            "requires": [
                "run completed",
                "clean tree (code_revision is a 40-hex commit and not dirty)",
                "pre-registration hash matches",
                "outcome A (T8 rules on the unperturbed test set) AND robustness criteria R1-R4",
                "candidate compatible (10.2 step 2)",
                "candidate files match the files evaluated",
            ],
            "result_if_none_qualifies": NO_PROMOTABLE,
        },
    }


def write_prereg(*, force: bool = False) -> dict[str, Any]:
    if PREREG_LOCK_PATH.exists() and not force:
        raise EvalProtocolError(f"{PREREG_LOCK_PATH} exists: the pre-registration is locked (--force, before any run)")
    old_sha = load_json(PREREG_LOCK_PATH)["preregistration_sha256"] if PREREG_LOCK_PATH.exists() else ""
    if force and _runs_using(old_sha):
        raise EvalProtocolError("an evaluation run already used this pre-registration; it cannot be re-registered")
    doc = build_prereg()
    doc["preregistration_sha256"] = prereg_hash(doc)
    write_text(PREREG_PATH, pretty_json(doc))
    lock = {
        "file": PREREG_PATH.relative_to(REPO_ROOT).as_posix(),
        "preregistration_sha256": doc["preregistration_sha256"],
        "locked_at_utc": doc["registered_at_utc"],
    }
    write_text(PREREG_LOCK_PATH, pretty_json(lock))
    return doc


def _runs_using(sha: str, runs_dir: Path = RUNS_DIR) -> list[str]:
    if not sha or not Path(runs_dir).is_dir():
        return []
    used = []
    for manifest in sorted(Path(runs_dir).glob("*/manifest.json")):
        try:
            if load_json(manifest).get("prereg_sha256") == sha:
                used.append(manifest.parent.name)
        except (OSError, ValueError):
            continue
    return used


def verify_prereg(
    prereg_path: Path = PREREG_PATH,
    lock_path: Path = PREREG_LOCK_PATH,
    perturbations_path: Path = PERTURBATIONS_PATH,
) -> dict[str, Any]:
    """Return the verified pre-registration or raise EvalProtocolError (a mismatch stops the run)."""
    for p in (prereg_path, lock_path, perturbations_path):
        if not Path(p).is_file():
            raise EvalProtocolError(f"{p} is missing: the pre-registration must be hashed before any evaluation")
    doc, lock = load_json(prereg_path), load_json(lock_path)
    actual = prereg_hash(doc)
    if doc.get("preregistration_sha256") != actual:
        raise EvalProtocolError(
            f"pre-registration hash mismatch: file says {doc.get('preregistration_sha256')}, content hashes to {actual}"
        )
    if lock.get("preregistration_sha256") != actual:
        raise EvalProtocolError(
            f"pre-registration differs from its lock: lock {lock.get('preregistration_sha256')}, content {actual}"
        )
    manifest = load_json(perturbations_path)
    validate_perturbation_manifest(manifest)
    if manifest_hash(manifest) != doc["perturbation_manifest"]["sha256"]:
        raise EvalProtocolError("the perturbation manifest changed after it was pre-registered")
    return doc


# ----------------------------------------------------------------------------- protocol guards
def assert_no_training_overlap(
    eval_seeds: Sequence[int],
    *,
    training_seeds: Sequence[int],
    reserved_training_range: tuple[int, int],
    training_scenario_seeds: Sequence[int] = (),
    test_range: tuple[int, int] | None = None,
) -> None:
    """Stop condition: any evaluation scenario that touches a training scenario id."""
    lo, hi = reserved_training_range
    seeds = {int(s) for s in eval_seeds}
    touched = sorted(s for s in seeds if lo <= s <= hi)
    if touched:
        raise EvalProtocolError(f"evaluation seeds {touched[:5]} fall in the reserved training range [{lo}, {hi}]")
    overlap = sorted(seeds & {int(s) for s in training_seeds} | seeds & {int(s) for s in training_scenario_seeds})
    if overlap:
        raise EvalProtocolError(f"evaluation seeds {overlap[:5]} are training seeds or training scenario seeds")
    if test_range is not None:
        outside = sorted(s for s in seeds if not test_range[0] <= s <= test_range[1])
        if outside:
            raise EvalProtocolError(f"evaluation seeds {outside[:5]} lie outside the test range {list(test_range)}")


# ----------------------------------------------------------------------------- criteria (pure)
def _col(rows: Sequence[Mapping[str, Any]], metric: str) -> np.ndarray:
    return np.array([r[metric] for r in rows], dtype=float)


def _ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return [r["scenario_id"] for r in rows]


def _env_steps(rows: Sequence[Mapping[str, Any]]) -> float:
    return float(sum(_col(rows, m).sum() for m in ENVELOPE_METRICS))


def _degradation_rel(base_mean: float, pert_mean: float) -> float:
    """Relative degradation of a higher-is-better metric; positive = worse."""
    return (base_mean - pert_mean) / abs(base_mean) if base_mean else 0.0


def summarize_policies(per_policy: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, dict[str, float]]:
    metrics = [k for k in next(iter(per_policy.values()))[0] if k not in ("scenario_id", "exogenous_hash")]
    return {p: {m: float(_col(rows, m).mean()) for m in sorted(metrics)} for p, rows in per_policy.items()}


def evaluate_robustness(
    unperturbed: Mapping[str, Sequence[Mapping[str, Any]]],
    perturbations: Mapping[str, Mapping[str, Any]],
    prereg: Mapping[str, Any],
) -> dict[str, Any]:
    """Pure function of per-scenario results: per-perturbation statistics and the pre-registered criteria R1-R4.

    ``unperturbed`` and each evaluated perturbation hold ``rule``, ``best_constant`` and ``candidate`` row lists with
    identical scenario ids in identical order."""
    crit = prereg["robustness_criteria"]
    boot = prereg["bootstrap"]
    ids = _ids(unperturbed["candidate"])
    for p in POLICIES:
        if _ids(unperturbed[p]) != ids:
            raise EvalProtocolError(f"unperturbed scenario ids differ for {p}")
    base_summary = summarize_policies({p: unperturbed[p] for p in POLICIES})
    base_primary = {p: base_summary[p][PRIMARY] for p in POLICIES}

    per: dict[str, Any] = {}
    failures: dict[str, list[str]] = {"R1": [], "R2": [], "R3": []}
    evaluated, not_applicable = [], []
    for pid, spec in perturbations.items():
        if spec["status"] != "evaluated":
            not_applicable.append(pid)
            per[pid] = {"status": spec["status"], "reason": spec.get("reason")}
            continue
        evaluated.append(pid)
        rows = spec["policies"]
        for p in POLICIES:
            if _ids(rows[p]) != ids:
                raise EvalProtocolError(f"{pid}: scenario ids differ for {p}: the scenario set must be identical")
        summary = summarize_policies({p: rows[p] for p in POLICIES})
        entry: dict[str, Any] = {"status": "evaluated", "kind": spec["kind"], "summary": summary}

        degr = {
            p: {
                "absolute": base_primary[p] - summary[p][PRIMARY],
                "relative": _degradation_rel(base_primary[p], summary[p][PRIMARY]),
            }
            for p in POLICIES
        }
        entry["degradation_primary"] = degr
        entry["envelope_steps"] = {p: _env_steps(rows[p]) for p in POLICIES}
        entry["envelope_fraction"] = {
            p: float(sum((_col(rows[p], m) > 0).sum() for m in ENVELOPE_METRICS) / (len(ids) * len(ENVELOPE_METRICS)))
            for p in POLICIES
        }

        paired = {}
        for b in ("rule", "best_constant"):
            ci = bootstrap_paired_ci(
                _col(rows["candidate"], PRIMARY),
                _col(rows[b], PRIMARY),
                n_resamples=boot["n_resamples"],
                confidence=boot["confidence"],
                seed=boot["seed"],
            )
            floor = -crit["R2_noninferiority"]["margin_rel"] * abs(base_primary[b])
            ci["noninferiority_floor"] = floor
            ci["noninferior"] = bool(ci["ci_low"] > floor)
            paired[b] = ci
            if not ci["noninferior"]:
                failures["R2"].append(f"{pid} vs {b}")
        entry["paired_vs_baselines"] = paired

        lower_baseline = min(entry["envelope_steps"]["rule"], entry["envelope_steps"]["best_constant"])
        r1 = entry["envelope_steps"]["candidate"] <= lower_baseline + crit["R1_envelope"]["max_extra_violation_steps"]
        if not r1:
            failures["R1"].append(pid)
        worst_baseline_rel = max(degr["rule"]["relative"], degr["best_constant"]["relative"])
        extra = degr["candidate"]["relative"] - worst_baseline_rel
        r3 = extra <= crit["R3_degradation"]["max_extra_relative_degradation"]
        if not r3:
            failures["R3"].append(pid)
        entry["checks"] = {"R1": bool(r1), "R2": all(c["noninferior"] for c in paired.values()), "R3": bool(r3)}
        entry["excess_relative_degradation"] = extra
        per[pid] = entry

    # worst case: the perturbation where the candidate's mean advantage over the better baseline is lowest
    worst = None
    for pid in evaluated:
        s = per[pid]["summary"]
        adv = s["candidate"][PRIMARY] - max(s["rule"][PRIMARY], s["best_constant"][PRIMARY])
        if worst is None or adv < worst["advantage_vs_best_baseline"]:
            worst = {"id": pid, "advantage_vs_best_baseline": adv}

    kinds = {perturbations[p]["kind"] for p in evaluated}
    r4_ok = bool(evaluated) and {"single", "joint"} <= kinds
    criteria = [
        {"id": "R1_envelope", "passed": not failures["R1"], "failed_on": failures["R1"]},
        {"id": "R2_noninferiority", "passed": not failures["R2"], "failed_on": failures["R2"]},
        {"id": "R3_degradation", "passed": not failures["R3"], "failed_on": failures["R3"]},
        {
            "id": "R4_completeness",
            "passed": r4_ok,
            "failed_on": [] if r4_ok else ["no evaluated single and joint perturbation"],
        },
    ]
    return {
        "unperturbed_summary": base_summary,
        "per_perturbation": per,
        "evaluated": sorted(evaluated),
        "not_applicable": sorted(not_applicable),
        "worst_case": worst,
        "criteria": criteria,
        "all_passed": all(c["passed"] for c in criteria),
    }


def final_decision(
    base_decision: Mapping[str, Any],
    robustness: Mapping[str, Any] | None,
    *,
    code_revision: str,
    dirty: bool,
    manifest_complete: bool,
    prereg_ok: bool,
) -> dict[str, Any]:
    """Combine the T8 outcome on unperturbed data with the robustness criteria and the run's hygiene.

    A is reached only if the T8 outcome is A AND R1-R4 pass. T8-A with a failed robustness criterion is B ("not shown
    robust"); T8-B and T8-C stand. ``promotable`` additionally needs a clean tree, a complete manifest and a verified
    pre-registration. If nothing qualifies, ``result`` is "no promotable policy"."""
    base = base_decision.get("outcome")
    gates = [
        {"id": "preregistration_verified", "passed": bool(prereg_ok)},
        {"id": "clean_tree", "passed": (not dirty) and bool(re.fullmatch(r"[0-9a-f]{40}", code_revision))},
        {"id": "manifest_complete", "passed": bool(manifest_complete)},
    ]
    criteria = []
    detail = base_decision.get("detail", {})
    for bname, d in detail.get("per_baseline", {}).items():
        for cid, ok in d.get("criteria", {}).items():
            criteria.append({"id": f"T8/{bname}/{cid}", "passed": bool(ok)})
    if "envelope_selected_candidate" in detail:
        env_ok = bool(detail["envelope_selected_candidate"]["ok"])
        criteria.append({"id": "T8/envelope_selected_candidate", "passed": env_ok})
    if robustness is not None:
        criteria += [{"id": c["id"], "passed": c["passed"]} for c in robustness["criteria"]]

    if base in (None, "NOT_EVALUATED"):
        outcome, reason = "NOT_EVALUATED", base_decision.get("reason", "no candidate evaluated")
    elif base == "A" and robustness is not None and robustness["all_passed"]:
        outcome, reason = "A", "T8 outcome A and every pre-registered robustness criterion held."
    elif base == "A":
        failed = [c["id"] for c in (robustness or {"criteria": []})["criteria"] if not c["passed"]]
        outcome, reason = "B", f"T8 outcome A, but not shown robust: failed {failed or ['robustness not evaluated']}."
    else:
        outcome, reason = base, base_decision.get("reason", "")

    hygiene_ok = all(g["passed"] for g in gates)
    promotable = outcome == "A" and all(c["passed"] for c in criteria) and hygiene_ok
    if promotable:
        action, result = "promote", "promote"
        claim = "simulator-validated candidate, robust to the listed perturbations in this simulator"
    else:
        action = "reject" if outcome in ("A", "B", "C") else "none"
        result = NO_PROMOTABLE
        claim = "none"
        if outcome == "A" and not hygiene_ok:
            reason += " Not promotable: " + ", ".join(g["id"] for g in gates if not g["passed"]) + " failed."
    return {
        "outcome": outcome,
        "t8_outcome": base,
        "reason": reason,
        "promotable": bool(promotable),
        "registry_action": action,
        "result": result,
        "claim_allowed": claim,
        "criteria": criteria,
        "gates": gates,
        "scope_limit": "robust to these listed perturbations in this simulator; not asserted to be realistic",
    }


# ----------------------------------------------------------------------------- reports (everything from results.json)
def _fmt(x: Any, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_tables(results: Mapping[str, Any]) -> dict[str, str]:
    rob = results["robustness"]
    lines = [
        "perturbation,kind,status,policy,mean_total_reward,abs_degradation,rel_degradation,"
        "envelope_steps,envelope_fraction"
    ]
    for pid in sorted(rob["per_perturbation"]):
        e = rob["per_perturbation"][pid]
        if e["status"] != "evaluated":
            lines.append(f"{pid},,{e['status']},,,,,,")
            continue
        for p in POLICIES:
            d = e["degradation_primary"][p]
            lines.append(
                f"{pid},{e['kind']},evaluated,{p},{e['summary'][p][PRIMARY]:.6f},"
                f"{d['absolute']:.6f},{d['relative']:.6f},"
                f"{e['envelope_steps'][p]:.0f},{e['envelope_fraction'][p]:.6f}"
            )
    summary = ["perturbation,policy,pue,wue,energy_kwh,water_L,carbon_gco2,carbon_is_real"]
    carbon_real = results["carbon"]["is_real"]
    for pid in ("unperturbed", *sorted(rob["evaluated"])):
        s = rob["unperturbed_summary"] if pid == "unperturbed" else rob["per_perturbation"][pid]["summary"]
        for p in (q for q in POLICIES if q in s):
            m = s[p]
            summary.append(
                f"{pid},{p},{m['mean_pue']:.6f},{m['mean_wue']:.6f},{m['energy_kwh']:.3f},{m['water_L']:.3f},"
                f"{m['carbon_gco2']:.3f},{str(carbon_real).lower()}"
            )
    paired = ["perturbation,baseline,mean_diff,ci_low,ci_high,noninferiority_floor,noninferior"]
    for pid in sorted(rob["evaluated"]):
        for b, ci in rob["per_perturbation"][pid]["paired_vs_baselines"].items():
            paired.append(
                f"{pid},{b},{ci['mean']:.6f},{ci['ci_low']:.6f},{ci['ci_high']:.6f},"
                f"{ci['noninferiority_floor']:.6f},{str(ci['noninferior']).lower()}"
            )
    crit = ["criterion,passed,failed_on"] + [
        f"{c['id']},{str(c['passed']).lower()},{'; '.join(c.get('failed_on', []))}"
        for c in results["decision"]["criteria"]
        if c["id"].startswith("R")
    ]
    return {
        "degradation.csv": "\n".join(lines) + "\n",
        "secondary_metrics.csv": "\n".join(summary) + "\n",
        "paired_differences.csv": "\n".join(paired) + "\n",
        "criteria.csv": "\n".join(crit) + "\n",
    }


def render_figure(results: Mapping[str, Any]) -> str:
    """Relative degradation of the primary metric per perturbation (candidate vs the better baseline), as plain SVG."""
    rob = results["robustness"]
    rows = []
    for pid in sorted(rob["evaluated"]):
        d = rob["per_perturbation"][pid]["degradation_primary"]
        rows.append((pid, d["candidate"]["relative"], max(d["rule"]["relative"], d["best_constant"]["relative"])))
    width, row_h, left = 760, 18, 190
    height = 40 + row_h * max(1, len(rows))
    scale = max([abs(v) for _, a, b in rows for v in (a, b)] + [1e-9])
    zero = left + (width - left - 20) / 2
    unit = (width - left - 40) / 2 / scale
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="monospace" font-size="11">',
        '<text x="10" y="14">Relative degradation of the primary metric (positive = worse). '
        "dark = candidate, light = worse baseline</text>",
        f'<line x1="{zero:.1f}" y1="22" x2="{zero:.1f}" y2="{height - 6}" stroke="#888"/>',
    ]
    for i, (pid, cand, base) in enumerate(rows):
        y = 30 + i * row_h
        out.append(f'<text x="10" y="{y + 9}">{pid}</text>')
        for off, val, color in ((0, cand, "#1f3a5f"), (7, base, "#9fb4cc")):
            x0, w = (zero, val * unit) if val >= 0 else (zero + val * unit, -val * unit)
            out.append(f'<rect x="{x0:.1f}" y="{y + off}" width="{w:.1f}" height="6" fill="{color}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_report(results: Mapping[str, Any]) -> str:
    dec, rob = results["decision"], results["robustness"]
    prereg = results["prereg"]
    lines = [
        "# Robustness evaluation and promotion decision (T30)",
        "",
        f"Run `{results['run_id']}`. Generated by `scripts/eval_policies.py report` from `results.json` only.",
        "",
        "## Decision",
        "",
        f"* **Outcome: {dec['outcome']}** (T8 outcome on unperturbed test data: {dec['t8_outcome']}).",
        f"* **Result: {dec['result']}**. Registry action: `{dec['registry_action']}`.",
        f"* Reason: {dec['reason']}",
        f"* Claim allowed: {dec['claim_allowed']}.",
        f"* Scope limit: {dec['scope_limit']}.",
        "",
        "| Gate / criterion | Passed |",
        "|---|---|",
    ]
    lines += [f"| {g['id']} | {g['passed']} |" for g in dec["gates"]]
    lines += [f"| {c['id']} | {c['passed']} |" for c in dec["criteria"]]
    lines += [
        "",
        "## Pre-registration",
        "",
        f"* `preregistration_sha256`: `{results['prereg_sha256']}`",
        f"* Perturbation manifest `{prereg['perturbation_manifest']['path']}` "
        f"`{prereg['perturbation_manifest']['sha256']}`",
        f"* Scenario set `{results['scenario_set_id']}`; physics `{results['physics_version']}`; "
        f"carbon real: {results['carbon']['is_real']} (carbon figures are fallback values when false).",
        f"* Inputs: {results['scenario_inputs']}.",
        "* Every perturbation is a stress test with no empirical basis unless its `basis` says `empirical:<source>`; "
        "+/-20 % is not asserted to be realistic.",
        "",
        "## Unperturbed test set (mean per episode)",
        "",
        "| policy | total_reward | energy_kwh | water_L | mean_pue | mean_wue |",
        "|---|---|---|---|---|---|",
    ]
    for p in (q for q in POLICIES if q in rob["unperturbed_summary"]):
        s = rob["unperturbed_summary"][p]
        lines.append(
            f"| {p} | {_fmt(s['total_reward'])} | {_fmt(s['energy_kwh'], 1)} | {_fmt(s['water_L'], 1)} | "
            f"{_fmt(s['mean_pue'])} | {_fmt(s['mean_wue'])} |"
        )
    lines += ["", "## Robustness", ""]
    wc = rob["worst_case"]
    if wc:
        lines.append(
            f"Worst-case perturbation: `{wc['id']}` (candidate's mean advantage over the better baseline "
            f"{_fmt(wc['advantage_vs_best_baseline'])})."
        )
    lines += [
        f"Evaluated: {len(rob['evaluated'])}; not applicable to the current physics: {len(rob['not_applicable'])}"
        + (f" ({', '.join(rob['not_applicable'])})." if rob["not_applicable"] else "."),
        "",
        "| perturbation | candidate rel. degradation | rule | best constant | "
        "envelope steps (cand / rule / const) | R1 | R2 | R3 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for pid in sorted(rob["evaluated"]):
        e = rob["per_perturbation"][pid]
        d, env, ck = e["degradation_primary"], e["envelope_steps"], e["checks"]
        lines.append(
            f"| {pid} | {_fmt(d['candidate']['relative'])} | {_fmt(d['rule']['relative'])} | "
            f"{_fmt(d['best_constant']['relative'])} | {env['candidate']:.0f} / {env['rule']:.0f} / "
            f"{env['best_constant']:.0f} | {ck['R1']} | {ck['R2']} | {ck['R3']} |"
        )
    lines += ["", "Tables: `tables/*.csv`. Figure: `figures/degradation.svg`.", ""]
    return "\n".join(lines)


def write_reports(run_dir: Path, results: Mapping[str, Any]) -> list[str]:
    written = []
    for name, text in render_tables(results).items():
        write_text(run_dir / "tables" / name, text)
        written.append(f"tables/{name}")
    write_text(run_dir / "figures" / "degradation.svg", render_figure(results))
    written.append("figures/degradation.svg")
    write_text(run_dir / "REPORT.md", render_report(results))
    written.append("REPORT.md")
    return written


def verify_reports(run_dir: Path) -> list[str]:
    """Regenerate every derived file from results.json and return the names that differ on disk (empty = OK)."""
    results = load_json(Path(run_dir) / "results.json")
    expected = {f"tables/{n}": t for n, t in render_tables(results).items()}
    expected["figures/degradation.svg"] = render_figure(results)
    expected["REPORT.md"] = render_report(results)
    bad = []
    for rel, text in expected.items():
        path = Path(run_dir) / rel
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            bad.append(rel)
    return bad


# ----------------------------------------------------------------------------- run manifest
def git_state(root: Path = REPO_ROOT) -> tuple[str, bool]:
    """(code_revision, dirty). Not a git checkout, or git unavailable => ("unknown", True): never promotable."""
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=30, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=60, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown", True
    return rev, bool(status.strip())


def _versions() -> dict[str, Any]:
    out: dict[str, Any] = {"python": platform.python_version(), "numpy": np.__version__}
    for name in ("torch", "tensorflow", "stable_baselines3", "gymnasium"):
        try:
            out[name] = __import__(name).__version__
        except Exception:
            out[name] = None
    return out


def build_manifest(
    *,
    run_id: str,
    started_at: str,
    command: Sequence[str],
    prereg: Mapping[str, Any],
    results_sha256: str | None,
    scenario_set_id: str,
    seeds: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    dirty_override: bool | None = None,
) -> dict[str, Any]:
    rev, dirty = git_state()
    lock = REPO_ROOT / "requirements.lock"
    from src import versions

    split = SPLIT_PATH if SPLIT_PATH.is_file() else None
    return {
        "run_id": run_id,
        "started_at_utc": started_at,
        "code_revision": rev,
        "dirty": dirty if dirty_override is None else dirty_override,
        "lock_sha256": sha256_file(lock) if lock.is_file() else None,
        "platform": {"os": platform.system(), "arch": platform.machine(), **_versions()},
        "command_line": list(command),
        "config_files": {
            p.relative_to(REPO_ROOT).as_posix(): sha256_file(p)
            for p in (PREREG_PATH, PREREG_LOCK_PATH, PERTURBATIONS_PATH)
            if p.is_file()
        },
        "dataset_manifest_sha256": None,
        "dataset_note": "scenarios are generated by DataCentreEnv from seeds (no dataset files are read)",
        "physics_version": versions.PHYSICS_VERSION,
        "environment_version": None,
        "reward_version": None,
        "envelope_version": None,
        "action_semantics_version": None,
        "versions_note": "environment/reward/envelope/action-semantics versions do not exist in this tree (T19/T27)",
        "scenario_set_id": scenario_set_id,
        "split_id": sha256_file(split) if split else None,
        "seeds": dict(seeds),
        "artifacts": list(artifacts),
        "prereg_sha256": prereg["preregistration_sha256"],
        "result_sha256": results_sha256,
    }


MANIFEST_REQUIRED = (
    "run_id", "started_at_utc", "code_revision", "dirty", "platform", "command_line", "config_files",
    "scenario_set_id", "seeds", "artifacts", "prereg_sha256", "result_sha256",
)  # fmt: skip


def manifest_is_complete(manifest: Mapping[str, Any]) -> bool:
    return all(manifest.get(k) not in (None, "", [], {}) for k in MANIFEST_REQUIRED if k != "artifacts") and (
        "artifacts" in manifest
    )


def write_status(
    run_dir: Path, state: str, started: str, finished: str | None = None, error: str | None = None
) -> None:
    write_text(
        run_dir / "status.json",
        pretty_json({"status": state, "started_at_utc": started, "finished_at_utc": finished, "error": error}),
    )


# ----------------------------------------------------------------------------- the run (needs the simulator stack)
def file_digests(directory: Path) -> dict[str, str]:
    return {p.name: sha256_file(p) for p in sorted(Path(directory).iterdir()) if p.is_file()}


def run_evaluation_protocol(
    prereg: Mapping[str, Any],
    manifest_doc: Mapping[str, Any],
    *,
    candidates: Mapping[int, Any] | None,
    candidate_dirs: Mapping[int, Path] | None = None,
    carbon_curve: np.ndarray | None = None,
    carbon_is_real: bool | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the protocol and return the ``results`` dict (without run id / hashes). Imports the simulator lazily."""
    from src import policy_evaluation as pe

    say = progress or (lambda _m: None)
    cfg = pe.EvalConfig.from_json(prereg["eval_config"])
    scenarios = pe.build_scenarios(cfg)
    pe.assert_disjoint(cfg, scenarios)
    test = scenarios["test"]
    split_range = None
    if SPLIT_PATH.is_file():
        r = load_json(SPLIT_PATH)["scenario_seed_ranges"]["test"]
        split_range = (int(r[0]), int(r[1]))
    assert_no_training_overlap(
        [s.seed for s in scenarios["validation"] + test],
        training_seeds=cfg.training_seeds,
        reserved_training_range=tuple(cfg.training_seed_reserved),
        test_range=None,  # validation seeds start below the test range; the test seeds are checked next
    )
    if split_range is not None:
        assert_no_training_overlap(
            [s.seed for s in test],
            training_seeds=cfg.training_seeds,
            reserved_training_range=tuple(cfg.training_seed_reserved),
            test_range=split_range,
        )

    digests_before = {s: file_digests(d) for s, d in (candidate_dirs or {}).items()}
    if carbon_curve is None:
        carbon_curve, carbon_is_real = pe.load_diurnal_carbon_intensity()
    base = pe.run_evaluation(cfg, ppo_candidates=dict(candidates) if candidates else None, carbon_curve=carbon_curve,
                             carbon_is_real=carbon_is_real, progress=say)  # fmt: skip
    base.pop("environment", None)  # wall-clock fields stay out of results.json (L1 determinism)

    sel = base["selection"]
    rule = pe.RulePolicy(cfg.rule_chilled_C)
    best = pe.ConstantPolicy(sel["best_constant"]["chilled_C"], sel["best_constant"]["mode"])
    selected_seed = sel["selected_ppo_seed"]
    policies: dict[str, Any] = {"rule": rule, "best_constant": best}
    if candidates and selected_seed is not None:
        policies["candidate"] = pe.PPOPolicy(candidates[selected_seed], f"ppo_seed_{selected_seed}")

    def rows(policy: Any) -> list[dict[str, Any]]:
        return [
            {"scenario_id": r.scenario_id, "exogenous_hash": r.exogenous_hash, **r.metrics}
            for r in pe.evaluate_policy(policy, test, cfg, carbon_curve)
        ]

    unperturbed = {name: rows(p) for name, p in policies.items()}
    perturbations: dict[str, Any] = {}
    for item in expand_perturbations(manifest_doc):
        reason = not_applicable_reason(item["entries"])
        if reason:
            perturbations[item["id"]] = {"status": "not_applicable", "kind": item["kind"], "reason": reason}
            continue
        say(f"perturbation {item['id']}")
        with perturbed(item["entries"]):
            got = {name: rows(p) for name, p in policies.items()}
        for name in got:  # same scenario set and inputs for every policy and every perturbation
            if [r["exogenous_hash"] for r in got[name]] != [r["exogenous_hash"] for r in unperturbed[name]]:
                raise EvalProtocolError(f"{item['id']}: a perturbation changed the exogenous inputs of {name}")
        perturbations[item["id"]] = {
            "status": "evaluated",
            "kind": item["kind"],
            "spec": [{k: e[k] for k in ("id", "parameter", "mode", "value", "basis")} for e in item["entries"]],
            "policies": got,
        }

    digests_after = {s: file_digests(d) for s, d in (candidate_dirs or {}).items()}
    if digests_after != digests_before:
        raise EvalProtocolError("a candidate's files changed during the evaluation: the policy was not frozen")
    return {
        "base": base,
        "unperturbed": unperturbed,
        "perturbations": perturbations,
        "selected_seed": selected_seed,
        "frozen_check": {
            "candidate_file_sha256_before_equals_after": True,
            "best_constant": sel["best_constant"],
            "selected_by": sel["selected_by"],
            "retraining_or_retuning_on_perturbed_or_test_data": False,
        },
        "carbon": base["carbon"],
        "scenario_set_id": base["scenario_set_id"],
        "scenario_inputs": base["scenario_inputs"],
        "physics_version": base["physics_version"],
        "test_scenarios": [s.scenario_id for s in test],
    }


def assemble_results(
    run_id: str,
    prereg: Mapping[str, Any],
    protocol: Mapping[str, Any],
    *,
    code_revision: str,
    dirty: bool,
    manifest_complete: bool,
) -> dict[str, Any]:
    has_candidate = "candidate" in protocol["unperturbed"]
    robustness = (
        evaluate_robustness(protocol["unperturbed"], protocol["perturbations"], prereg) if has_candidate else None
    )
    decision = final_decision(
        protocol["base"]["decision"],
        robustness,
        code_revision=code_revision,
        dirty=dirty,
        manifest_complete=manifest_complete,
        prereg_ok=True,
    )
    results: dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": run_id,
        "prereg": prereg,
        "prereg_sha256": prereg["preregistration_sha256"],
        "physics_version": protocol["physics_version"],
        "scenario_set_id": protocol["scenario_set_id"],
        "scenario_inputs": protocol["scenario_inputs"],
        "carbon": protocol["carbon"],
        "selected_seed": protocol["selected_seed"],
        "frozen_check": protocol["frozen_check"],
        "test_scenarios": protocol["test_scenarios"],
        "base_t8": protocol["base"],
        "unperturbed": protocol["unperturbed"],
        "perturbations": protocol["perturbations"],
        "robustness": robustness
        or {
            "unperturbed_summary": summarize_policies(
                {k: protocol["unperturbed"][k] for k in ("rule", "best_constant")}
            ),
            "per_perturbation": {},
            "evaluated": [],
            "not_applicable": [],
            "worst_case": None,
            "criteria": [],
            "all_passed": False,
        },
        "decision": decision,
    }
    return results


def cmd_run(args: argparse.Namespace) -> int:
    prereg = verify_prereg()  # a mismatch raises EvalProtocolError: the run stops
    manifest_doc = load_json(PERTURBATIONS_PATH)
    from src import policy_evaluation as pe

    cfg = pe.EvalConfig.from_json(prereg["eval_config"])
    candidates = candidate_dirs = None
    if not args.baselines_only:
        cdir = Path(args.candidates_dir)
        candidates = pe.load_candidates(cdir, cfg)
        candidate_dirs = {s: cdir / f"seed_{s}" for s in cfg.training_seeds}

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = f"eval-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{prereg['preregistration_sha256'][:8]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    write_status(run_dir, "running", started)
    write_text(run_dir / "PREREGISTRATION.json", pretty_json(prereg))
    try:
        protocol = run_evaluation_protocol(
            prereg, manifest_doc, candidates=candidates, candidate_dirs=candidate_dirs, progress=print
        )
        rev, dirty = git_state()
        if dirty:
            print("WARNING: dirty or unknown code revision: this run can never be promoted", file=sys.stderr)
        sel = protocol["selected_seed"]
        artifacts = (
            [{"seed": sel, "files": file_digests(candidate_dirs[sel]), "model_id": args.model_id}]
            if candidate_dirs and sel is not None
            else []
        )
        seeds = {
            "training": list(cfg.training_seeds),
            "validation_start": cfg.validation_seed_start,
            "test_start": cfg.test_seed_start,
            "bootstrap": prereg["bootstrap"]["seed"],
        }
        results = assemble_results(run_id, prereg, protocol, code_revision=rev, dirty=dirty, manifest_complete=True)
        write_text(run_dir / "results.json", pretty_json(results))
        result_sha = sha256_file(run_dir / "results.json")
        manifest = build_manifest(
            run_id=run_id, started_at=started, command=sys.argv, prereg=prereg, results_sha256=result_sha,
            scenario_set_id=protocol["scenario_set_id"], seeds=seeds, artifacts=artifacts,
        )  # fmt: skip
        complete = manifest_is_complete(manifest)
        if not complete:  # recompute the decision with the truth about the manifest, then rewrite results
            results = assemble_results(
                run_id, prereg, protocol, code_revision=rev, dirty=dirty, manifest_complete=False
            )
            write_text(run_dir / "results.json", pretty_json(results))
            manifest["result_sha256"] = sha256_file(run_dir / "results.json")
        write_text(run_dir / "manifest.json", pretty_json(manifest))
        decision = {
            **results["decision"],
            "run_id": run_id,
            "model_id": args.model_id,
            "candidate_files": artifacts[0]["files"] if artifacts else None,
            "prereg_sha256": prereg["preregistration_sha256"],
            "code_revision": rev,
            "dirty": dirty,
            "result_sha256": manifest["result_sha256"],
        }
        write_text(run_dir / "decision.json", pretty_json(decision))
        write_reports(run_dir, load_json(run_dir / "results.json"))
        write_status(run_dir, "completed", started, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except BaseException as exc:
        finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_status(run_dir, "failed", started, finished, repr(exc)[:500])
        raise
    print(f"run {run_id}: outcome {decision['outcome']}, result: {decision['result']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    print("wrote", ", ".join(write_reports(run_dir, load_json(run_dir / "results.json"))))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    bad = verify_reports(run_dir)
    if load_json(run_dir / "manifest.json")["result_sha256"] != sha256_file(run_dir / "results.json"):
        bad.append("results.json (hash differs from manifest.json)")
    if bad:
        print("differs:", ", ".join(bad), file=sys.stderr)
        return 1
    print("verified: every derived file regenerates identically from results.json")
    return 0


def cmd_prereg(args: argparse.Namespace) -> int:
    if args.write:
        doc = write_prereg(force=args.force)
        print("wrote", PREREG_PATH, "\npreregistration_sha256", doc["preregistration_sha256"])
        return 0
    doc = verify_prereg()
    print("verified; preregistration_sha256", doc["preregistration_sha256"])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prereg")
    p.add_argument("--write", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--force", action="store_true", help="re-register (refused once any run used the old hash)")
    p.set_defaults(fn=cmd_prereg)
    r = sub.add_parser("run")
    r.add_argument("--candidates-dir", default="models/optimizer_candidates")
    r.add_argument("--baselines-only", action="store_true")
    r.add_argument("--model-id", default=None, help="registry model_id of the candidate under evaluation")
    r.set_defaults(fn=cmd_run)
    for name, fn in (("report", cmd_report), ("verify", cmd_verify)):
        q = sub.add_parser(name)
        q.add_argument("run_dir")
        q.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    try:
        return int(args.fn(args))
    except EvalProtocolError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
