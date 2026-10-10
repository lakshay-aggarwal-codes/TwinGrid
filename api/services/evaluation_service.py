"""BC-11 / G-EVAL: read-only projection of the policy-evaluation reports (BE-G2).

Serves ``reports/policy_evaluation/<evaluation_id>/results.json`` (``schema_version`` 1, written by
``src/policy_evaluation.py``) and nothing else. This module computes NOTHING: no score, rank, delta, confidence
interval or outcome. Every number and sentence comes from ``results.json`` or ``PREREGISTRATION.json``; a field that
is absent there stays absent here.

The only text this module owns is static and says where the data came from:

* ``source``  ``policy_evaluation_v1`` (the only format served; T30 ``reports/runs/*`` is out of scope until a real
              T30 run exists and has its own contract record).
* ``origin``  ``simulated``: the harness only ever runs the in-repo DataCentreEnv.

Pre-registration text (``metrics``, ``outcome_definitions``, ``ci_level``) is attached ONLY when the pre-registration
file's own ``preregistration_sha256`` equals the report's. A mismatch means the text may not be the text the report
was run under, so it is left out.

Policy order is fixed here, not by any metric: ``rule``, ``best_constant``, then the remaining policies in the order
``results.json`` lists them (``ppo_seed_<n>``).

``per_scenario_test`` (60 episodes x policy) and ``environment`` are not served in v1.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Final

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

SOURCE: Final[str] = "policy_evaluation_v1"
ORIGIN: Final[str] = "simulated"
SUPPORTED_SCHEMA_VERSION: Final[int] = 1
MAX_REPORT_BYTES: Final[int] = 5_000_000

_ROOT = Path(__file__).resolve().parents[2]
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_FIXED_ORDER: Final[tuple[str, ...]] = ("rule", "best_constant")


def reports_dir() -> Path:
    """Directory holding the evaluation reports (tests point this at a temporary directory)."""
    return _ROOT / "reports" / "policy_evaluation"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > MAX_REPORT_BYTES:
            logger.warning("evaluation file too large, skipped: %s", path.name)
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("evaluation file unreadable, skipped: %s", path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def _load_report(evaluation_id: str) -> dict[str, Any] | None:
    """The parsed ``results.json`` for an id that exists in the directory listing, else None."""
    if not _ID_RE.fullmatch(evaluation_id):
        return None
    base = reports_dir()
    # The id must be an entry of the directory listing: it is never joined to a path before that check.
    try:
        known = {p.name for p in base.iterdir() if p.is_dir() and not p.is_symlink()}
    except OSError:
        return None
    if evaluation_id not in known:
        return None
    results = _read_json(base / evaluation_id / "results.json")
    if results is None or results.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        return None
    return results


def _generated_at(results: dict[str, Any]) -> str | None:
    env = results.get("environment")
    value = env.get("generated_at_utc") if isinstance(env, dict) else None
    return value if isinstance(value, str) else None


def _decision(results: dict[str, Any]) -> dict[str, Any]:
    decision = results.get("decision")
    return decision if isinstance(decision, dict) else {}


def _policy_kind(policy_id: str) -> str | None:
    if policy_id in _FIXED_ORDER:
        return policy_id
    if policy_id == "ppo" or policy_id.startswith("ppo_"):
        return "ppo"
    return None  # unknown stays unknown


def _policies(results: dict[str, Any]) -> list[dict[str, Any]]:
    summary = results.get("summary_test_mean_per_episode")
    if not isinstance(summary, dict):
        return []
    ids = [p for p in _FIXED_ORDER if p in summary] + [p for p in summary if p not in _FIXED_ORDER]
    out: list[dict[str, Any]] = []
    for pid in ids:
        metrics = summary[pid]
        if not isinstance(metrics, dict):
            continue
        item: dict[str, Any] = {"policy_id": pid}
        kind = _policy_kind(pid)
        if kind is not None:
            item["kind"] = kind
        item["metrics"] = dict(metrics)
        out.append(item)
    return out


def _preregistration_for(results: dict[str, Any]) -> dict[str, Any] | None:
    prereg = _read_json(reports_dir() / "PREREGISTRATION.json")
    if prereg is None:
        return None
    sha = results.get("preregistration_sha256")
    if not isinstance(sha, str) or prereg.get("preregistration_sha256") != sha:
        return None
    return prereg


def _summary(evaluation_id: str, results: dict[str, Any]) -> dict[str, Any]:
    decision = _decision(results)
    return {
        "evaluation_id": evaluation_id,
        "source": SOURCE,
        "generated_at_utc": _generated_at(results),
        "outcome": decision.get("outcome"),
        "claim_allowed": decision.get("claim_allowed"),
        "ppo_evaluated": any(p.get("kind") == "ppo" for p in _policies(results)),
    }


def list_evaluations() -> dict[str, Any]:
    base = reports_dir()
    try:
        names = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        return {"evaluations": []}
    items = []
    for name in names:
        results = _load_report(name)
        if results is not None:
            items.append(_summary(name, results))
    # Newest first by the report's own timestamp (an ISO-8601 UTC string); undated reports last.
    items.sort(
        key=lambda i: (i["generated_at_utc"] is not None, i["generated_at_utc"] or "", i["evaluation_id"]), reverse=True
    )
    return {"evaluations": items}


def get_evaluation(evaluation_id: str) -> dict[str, Any]:
    results = _load_report(evaluation_id)
    if results is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown evaluation_id")
    detail: dict[str, Any] = {
        "evaluation_id": evaluation_id,
        "source": SOURCE,
        "origin": ORIGIN,
        "schema_version": results.get("schema_version"),
        "generated_at_utc": _generated_at(results),
    }
    for key in (
        "physics_version",
        "scenario_inputs",
        "carbon",
        "scenario_set_id",
        "scenario_sets",
        "preregistration_sha256",
        "decision",
    ):
        if key in results:
            detail[key] = results[key]
    detail["policies"] = _policies(results)
    if "selection" in results:
        detail["selection"] = results["selection"]
    prereg = _preregistration_for(results)
    if prereg is not None:
        if isinstance(prereg.get("metrics"), dict):
            detail["metrics"] = prereg["metrics"]
        rules = prereg.get("outcome_rules")
        if isinstance(rules, dict):
            detail["outcome_definitions"] = dict(rules)
        config = prereg.get("config")
        if isinstance(config, dict) and "confidence" in config:
            detail["ci_level"] = config["confidence"]
    return detail
