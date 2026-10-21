"""Read-only evidence tools. Each takes the request's ``ToolContext`` and ``EvidenceBook`` and returns a ``ToolResult``.

Allow-listed (``TOOLS``); there is no write tool and no tool takes free text into a query. The tools call EXISTING
services through loaders the plugin injects (``api/plugins/copilot.py`` calls the explanation and passport route
functions and ``data_repository.get_alert``); the rule maths (score vs threshold, range deviation) is not repeated here.
Missing data means evidence is left out and an ``unknowns`` entry is added; nothing is fabricated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import ROOT_CAUSE_UNKNOWN, catalogue, evidence, signal_adapter
from .evidence import EvidenceBook

CLAIMS_PATH = Path(__file__).resolve().parents[2] / "docs" / "CLAIMS.md"
#: Assumption, not a measurement: a live sample older than this is reported stale. Task 16 owns the real per-signal value.
DEFAULT_STALE_AFTER_S = 120
MAX_CLAIMS = 3
MAX_MODELS = 3
_CLAIM_ROW = re.compile(r"^\|\s*(C-\d{2})\s*\|")

#: measurand / twin-state names -> the one rule key. Only signals with a documented limit are listed.
SIGNAL_ALIASES = {
    "inlet_temp": "inlet_temp",
    "inlet_temperature": "inlet_temp",
    "server_inlet_temp_c": "inlet_temp",
    "outlet_temp": "outlet_temp",
    "outlet_temperature": "outlet_temp",
    "server_outlet_temp_c": "outlet_temp",
    "pue": "pue",
}


class NotFound(LookupError):
    """The entity the question is about does not exist (the plugin answers 404)."""


@dataclass
class ToolContext:
    now: datetime
    load_alert: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None
    load_signal: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None
    load_passport: Callable[[], Awaitable[dict[str, Any] | None]] | None = None
    claims_path: Path = CLAIMS_PATH
    catalogue: list[dict[str, Any]] | None = None
    stale_after_s: int = DEFAULT_STALE_AFTER_S


@dataclass
class ToolResult:
    refs: dict[str, str] = field(default_factory=dict)  # role -> evidence id, for the answer templates
    unknowns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)  # non-evidence facts the templates branch on (booleans, counts)


def _finite_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))


# ----------------------------------------------------------------------------- alerts


async def get_alert_explanation(ctx: ToolContext, book: EvidenceBook, alert_id: str) -> ToolResult:
    """Score, threshold and the largest signal deviation of a stored alert, as the explanation endpoint reports them."""
    loaded = await ctx.load_alert(alert_id) if ctx.load_alert else None
    if loaded is None:
        raise NotFound("alert")
    alert, expl = loaded["alert"], loaded.get("explanation") or {}
    entity = f"alert:{alert['id']}"
    observed = evidence.iso_utc(alert.get("created_at"))
    origin = evidence.origin_from_record(alert.get("origin"))
    res = ToolResult(data={"alert_id": alert["id"]})
    res.unknowns.append(ROOT_CAUSE_UNKNOWN)
    res.unknowns.extend(str(u) for u in expl.get("unavailable") or [])

    def add(
        role: str,
        name: str,
        value: Any,
        *,
        origin_: str = origin,
        observed_at: str | None = observed,
        unit: str | None = None,
    ) -> None:
        res.refs[role] = book.add(
            source="alert_explanation", entity=entity, field=name, value=value, unit=unit,
            observed_at=observed_at, origin=origin_, freshness="static",
        )  # fmt: skip

    svt = expl.get("score_vs_threshold")
    if isinstance(svt, dict) and _finite_number(svt.get("score")) and _finite_number(svt.get("threshold")):
        add("score", "score", float(svt["score"]))
        add("threshold", "threshold", float(svt["threshold"]))
        add("over_threshold", "over_threshold", bool(svt["over_threshold"]))
        res.data["over_threshold"] = bool(svt["over_threshold"])
        if expl.get("threshold_basis"):
            res.warnings.append(
                "The threshold is the currently configured detector's, not necessarily the one in force when the alert was raised."
            )
    elif _finite_number(alert.get("score")):
        add("score", "score", float(alert["score"]))
        res.unknowns.append("No detector threshold is available, so the score cannot be compared with one.")
    else:
        res.unknowns.append("The stored score is not a usable number.")
    if alert.get("severity"):
        add("severity", "severity", str(alert["severity"]))
    features = expl.get("features")
    if isinstance(features, list) and features and isinstance(features[0], dict):
        top = features[0]
        reading_origin = evidence.origin_from_record(expl.get("reading_origin"))
        add("top_feature", "top_feature", str(top.get("feature")), origin_=reading_origin)
        if _finite_number(top.get("centre_distance")):
            add(
                "top_feature_distance",
                "top_feature_centre_distance",
                float(top["centre_distance"]),
                origin_=reading_origin,
            )
        if isinstance(top.get("outside_range"), bool):
            add(
                "top_feature_outside",
                "top_feature_outside_training_range",
                top["outside_range"],
                origin_=reading_origin,
            )
    if alert.get("message"):
        add("message", "message", str(alert["message"]))
    return res


# ----------------------------------------------------------------------------- signals


def _rules() -> dict[str, dict[str, Any]]:
    """The documented limits of the simulator's safety envelope (``src/digital_twin.SAFETY_ENVELOPE``): critical bounds
    only. There are no warning bounds in this repository yet (Task 16)."""
    from src import digital_twin as dt  # lazy: keeps this module importable without the twin's dependencies

    return {
        "inlet_temp": {"rule_id": "safety_envelope:inlet_temp", "unit": "degC", "crit_low": dt.INLET_TEMP_MIN, "crit_high": dt.INLET_TEMP_MAX},
        "outlet_temp": {"rule_id": "safety_envelope:outlet_temp", "unit": "degC", "crit_high": dt.OUTLET_TEMP_MAX},
        "pue": {"rule_id": "safety_envelope:pue", "unit": None, "crit_high": dt.PUE_MAX_SAFE},
    }  # fmt: skip


def rule_for(signal: str, measurand: str | None = None) -> dict[str, Any] | None:
    key = SIGNAL_ALIASES.get(str(signal).strip().lower()) or SIGNAL_ALIASES.get(str(measurand or "").strip().lower())
    try:
        return _rules().get(key) if key else None
    except ImportError:
        return None


async def get_threshold_rule(
    ctx: ToolContext, book: EvidenceBook, signal: str, measurand: str | None = None
) -> ToolResult:
    rule = rule_for(signal, measurand)
    res = ToolResult(data={"rule": rule})
    if rule is None:
        res.unknowns.append(f"No threshold rule is defined for signal {signal}.")
        return res
    for bound in signal_adapter.RULE_FIELDS:
        if rule.get(bound) is not None:
            res.refs[bound] = book.add(
                source="threshold_rule", entity=f"signal:{signal}", field=bound, value=float(rule[bound]),
                unit=rule.get("unit"), origin="assumed", freshness="static",
            )  # fmt: skip
    return res


async def get_signal_status(ctx: ToolContext, book: EvidenceBook, signal: str) -> ToolResult:
    """The latest stored value of a signal and its status under the threshold rule (``unknown`` while no rule engine)."""
    sample = await ctx.load_signal(signal) if ctx.load_signal else None
    res = ToolResult()
    if sample is None:
        res.unknowns.append(f"No stored sample was found for signal {signal}.")
        res.data["status"] = "unknown"
        return res
    observed_at = sample.get("observed_at")
    rule_result = await get_threshold_rule(ctx, book, signal, sample.get("measurand"))
    res.unknowns.extend(rule_result.unknowns)
    res.refs.update(rule_result.refs)
    state = signal_adapter.signal_status(
        value=sample.get("value"), observed_at=observed_at, now=ctx.now, rule=rule_result.data["rule"],
        stale_after_s=ctx.stale_after_s, unit=sample.get("unit"),
    )  # fmt: skip
    origin = evidence.origin_from_record(sample.get("origin"))
    freshness = evidence.freshness_of(observed_at, ctx.now, ctx.stale_after_s)
    if _finite_number(sample.get("value")):
        res.refs["value"] = book.add(
            source="twin_state", entity=f"signal:{signal}", field="value", value=float(sample["value"]),
            unit=sample.get("unit"), observed_at=evidence.iso_utc(observed_at), origin=origin, freshness=freshness,
        )  # fmt: skip
    else:
        res.unknowns.append(f"The latest sample of {signal} has no usable value.")
    for name in ("status", "reason_code"):
        res.refs[name] = book.add(
            source="twin_state", entity=f"signal:{signal}", field=name, value=state[name],
            observed_at=evidence.iso_utc(observed_at), origin=origin, freshness=freshness,
        )  # fmt: skip
    if freshness == "stale":
        res.unknowns.append(f"The latest value of {signal} is stale, so its current state is not known.")
    if state["status"] == "unknown":
        res.unknowns.append(f"The status of {signal} is unknown (reason: {state['reason_code']}).")
    res.data.update(status=state["status"], freshness=freshness)
    return res


# ----------------------------------------------------------------------------- models and claims


async def get_model_passport(ctx: ToolContext, book: EvidenceBook, model_id: str | None = None) -> ToolResult:
    passport = await ctx.load_passport() if ctx.load_passport else None
    res = ToolResult(data={"models": []})
    models = passport.get("models") if isinstance(passport, dict) else None
    if not isinstance(models, list):
        res.unknowns.append("The model passport is not available.")
        return res
    chosen = [m for m in models if isinstance(m, dict) and (model_id is None or m.get("model_id") == model_id)]
    if model_id is not None and not chosen:
        res.unknowns.append(f"No passport entry exists for model {model_id}.")
    for m in chosen[:MAX_MODELS]:
        mid, refs = str(m.get("model_id")), {}
        for name, value in (
            ("status", m.get("status")),
            ("data_origin", m.get("data_origin")),
            ("limitation", (m.get("limitations") or [None])[0]),
            ("claim_boundary", m.get("claim_boundary")),
        ):
            if value is not None and isinstance(value, (str, bool, int, float)):
                refs[name] = book.add(
                    source="model_passport", entity=f"model:{mid}", field=name, value=value,
                    origin="documentation", freshness="static",
                )  # fmt: skip
        res.data["models"].append({"model_id": mid, "kind": m.get("kind"), "refs": refs})
    return res


def parse_claims(path: Path) -> list[dict[str, str]]:
    """Rows of the claims ledger: ``id, claim, status, evidence, boundary``."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not _CLAIM_ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5:
            rows.append(
                {
                    "id": cells[0],
                    "claim": cells[1],
                    "status": cells[2],
                    "evidence": cells[3],
                    "boundary": " | ".join(cells[4:]),
                }
            )
    return rows


async def get_claims(ctx: ToolContext, book: EvidenceBook, topic: str) -> ToolResult:
    res = ToolResult(data={"claims": []})
    try:
        rows = parse_claims(ctx.claims_path)
    except OSError:
        res.unknowns.append("The claims ledger could not be read.")
        return res
    words = catalogue._words(topic)
    hits = [r for r in rows if words and words & catalogue._words(r["claim"])][:MAX_CLAIMS]
    if not hits:
        res.unknowns.append(f"No claims-ledger row matches {topic}.")
    for r in hits:
        refs = {
            name: book.add(
                source="claims_ledger",
                entity=f"claim:{r['id']}",
                field=name,
                value=r[name],
                origin="documentation",
                freshness="static",
            )  # fmt: skip
            for name in ("claim", "status", "boundary")
        }
        res.data["claims"].append({"id": r["id"], "refs": refs})
    return res


# ----------------------------------------------------------------------------- features


async def find_feature(ctx: ToolContext, book: EvidenceBook, query: str, feature_id: str | None = None) -> ToolResult:
    entries = ctx.catalogue if ctx.catalogue is not None else catalogue.load_catalogue()
    exact = catalogue.get_feature(feature_id, entries) if feature_id else None
    found = [exact] if exact else catalogue.find_feature(query, entries)
    res = ToolResult(data={"features": found})
    if not found:
        res.unknowns.append("No catalogue entry matches the question.")
        return res
    best = found[0]
    for name in ("title", "description"):
        res.refs[name] = book.add(
            source="capability_catalogue", entity=f"feature:{best['id']}", field=name, value=best[name],
            origin="documentation", freshness="static",
        )  # fmt: skip
    return res


#: The allow-list. Every entry only reads; ``tests/test_copilot_tools.py`` fails if a name suggests a write.
TOOLS: dict[str, Callable[..., Awaitable[ToolResult]]] = {
    "get_alert_explanation": get_alert_explanation,
    "get_signal_status": get_signal_status,
    "get_threshold_rule": get_threshold_rule,
    "get_model_passport": get_model_passport,
    "get_claims": get_claims,
    "find_feature": find_feature,
}
