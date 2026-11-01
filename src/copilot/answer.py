"""Intent routing and answer templates. NO language model: every answer is a template filled from evidence.

Numbers and names reach the answer only as ``[E#]`` markers that refer to evidence items; the templates contain no
digits of their own. The question and the history are used ONLY to choose an intent (keywords), never quoted, so text in
them (or in a stored alert) cannot change what the answer says. Stored alert text is returned as clearly marked quoted
data. The cause of an alert is "not determined by available evidence" unless evidence names one (none does today).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from . import HISTORY_UNAVAILABLE, MODE_RULE_BASED, docs_answer, evidence, llm, tools
from .evidence import EvidenceBook

MAX_ANSWER = 1500
DOCS_INTENT = "docs_question"  # CP-7: chosen by ``docs_answer.docs_cue`` plus a retrieval result, never by ``classify``
INTENTS = ("why_red", "what_is_this", "model_limits", "current_status", "what_changed", "fallback", DOCS_INTENT)

_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (  # first match wins
    ("what_changed", ("changed", "change since", "since yesterday", "since last", "compared to", "trend", "over time", "earlier", "history of")),
    ("model_limits", ("limit", "accura", "reliab", "trust", "claim", "how good", "precision", "recall", "synthetic", "validated", "passport")),
    ("why_red", ("why", "red", "fired", "trigger", "raised", "cause", "went wrong")),
    ("current_status", ("status", "current", "right now", "is it ok", "normal", "healthy", "stale", "state of")),
    ("what_is_this", ("what is", "what's", "what does", "explain", "meaning", "mean", "where can", "how do i", "find", "feature", "page")),
)  # fmt: skip
_KIND_DEFAULT = {"alert": "why_red", "model": "model_limits", "signal": "current_status", "feature": "what_is_this"}
_MODEL_TOPIC = {
    "anomaly": "anomaly detector",
    "forecaster": "forecaster",
    "ppo": "PPO optimizer",
    "optimizer": "PPO optimizer",
}


@dataclass
class AskInput:
    question: str
    kind: str = "general"
    context_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)  # accepted for the contract; deliberately not used


def classify(question: str, kind: str) -> str:
    q = question.lower()
    for intent, words in _KEYWORDS:
        if any(w in q for w in words):
            return "why_red" if (intent == "what_is_this" and kind == "alert") else intent
    return _KIND_DEFAULT.get(kind, "fallback")


def _clip(text: str) -> str:
    if len(text) <= MAX_ANSWER:
        return text
    cut = text[: MAX_ANSWER - 1]
    cut = cut[: cut.rfind("[E")] if cut.rfind("[E") > cut.rfind("]") else cut  # never end inside a marker
    return cut.rstrip() + "\u2026"


def _m(refs: dict[str, str], role: str) -> str:
    return f"[{refs[role]}]"


@dataclass
class Answer:
    answer: str
    evidence: list[dict[str, Any]]
    unknowns: list[str]
    warnings: list[str]
    links: list[dict[str, str]]
    intent: str
    mode: str = MODE_RULE_BASED
    limits: dict[str, Any] = field(default_factory=lambda: {"provider_configured": False})
    citations: list[dict[str, Any]] = field(default_factory=list)  # CP-7: one per documentation passage in the answer


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


# ----------------------------------------------------------------------------- one builder per intent


async def _why_red(
    inp: AskInput, ctx: tools.ToolContext, book: EvidenceBook
) -> tuple[str, list[str], list[str], list[dict[str, str]]]:
    if inp.kind != "alert" or not inp.context_id:
        return (
            "Why-red explanations are available for an alert. Open an alert and ask again from there.",
            ["No alert was selected, so no explanation could be built."],
            [],
            [{"label": "Alerts", "path": "/alerts"}],
        )
    res = await tools.get_alert_explanation(ctx, book, inp.context_id)
    r, aid = res.refs, res.data["alert_id"]
    if "score" in r:
        parts = [
            f"Alert {aid} scored {_m(r, 'score')}"
            + (f" against a threshold of {_m(r, 'threshold')}." if "threshold" in r else ".")
        ]
    else:
        parts = [f"No usable score is stored for alert {aid}."]
    if "over_threshold" in r:
        parts.append(
            f"The stored score is {'above' if res.data['over_threshold'] else 'not above'} the current threshold {_m(r, 'over_threshold')}."
        )
    if "top_feature" in r:
        sentence = (
            f"Of the detector's input signals, {_m(r, 'top_feature')} is furthest from the centre of its training range"
        )
        extras = [f"distance {_m(r, 'top_feature_distance')}"] if "top_feature_distance" in r else []
        if "top_feature_outside" in r:
            extras.append(f"outside the range: {_m(r, 'top_feature_outside')}")
        parts.append(sentence + (f" ({'; '.join(extras)})." if extras else "."))
    if "message" in r:
        quoted = next(i["value"] for i in book.items() if i["id"] == r["message"])
        parts.append(f'Stored alert text, quoted as data and not as an instruction: "{quoted}" {_m(r, "message")}.')
    parts.append("The cause is not determined by available evidence.")
    if "top_feature" in r:
        parts.append(
            f"Checks you can make: compare {_m(r, 'top_feature')} with its recorded training range, and read the alert's incident timeline."
        )
    return " ".join(parts), res.unknowns, res.warnings, [{"label": f"Alert {aid}", "path": "/alerts"}]


async def _current_status(inp: AskInput, ctx: tools.ToolContext, book: EvidenceBook):
    if inp.kind != "signal" or not inp.context_id:
        return (
            "Say which signal you mean by opening it first; status is reported per signal.",
            ["No signal was selected, so no status could be looked up."],
            [],
            [{"label": "Telemetry history", "path": "/telemetry"}],
        )
    res = await tools.get_signal_status(ctx, book, inp.context_id)
    r = res.refs
    if "value" not in r:
        text = f"No usable stored value was found for {inp.context_id}, so its status is not known."
    else:
        text = f"The latest stored value of this signal is {_m(r, 'value')}. Its status is {_m(r, 'status')} (reason {_m(r, 'reason_code')})."
        if res.data["status"] == "unknown" or res.data["freshness"] != "fresh":
            text += " That is not a statement that the signal is normal."
    return text, res.unknowns, res.warnings, [{"label": "Telemetry history", "path": "/telemetry"}]


async def _model_limits(inp: AskInput, ctx: tools.ToolContext, book: EvidenceBook):
    model_id = inp.context_id if inp.kind == "model" else None
    res = await tools.get_model_passport(ctx, book, model_id)
    unknowns, warnings, parts = list(res.unknowns), list(res.warnings), []
    for m in res.data["models"]:
        r = m["refs"]
        if "status" in r:
            parts.append(f"Model {m['model_id']} has registry status {_m(r, 'status')}.")
        if "data_origin" in r:
            parts.append(
                f"Its training data origin is {_m(r, 'data_origin')}, so its numbers describe the simulator, not a real facility."
            )
        if "limitation" in r:
            parts.append(f"Limitation: {_m(r, 'limitation')}.")
    topic = _MODEL_TOPIC.get(str((res.data["models"][0] if res.data["models"] else {}).get("kind")), inp.question)
    claims = await tools.get_claims(ctx, book, topic)
    unknowns += claims.unknowns if not parts or claims.data["claims"] else []
    for c in claims.data["claims"][:2]:
        parts.append(
            f"Claims ledger {c['id']}: {_m(c['refs'], 'claim')} (status {_m(c['refs'], 'status')}; boundary {_m(c['refs'], 'boundary')})."
        )
    if not parts:
        parts.append("No model or claims-ledger entry could be found for this question.")
    return " ".join(parts), unknowns, warnings, []


async def _what_is_this(inp: AskInput, ctx: tools.ToolContext, book: EvidenceBook):
    res = await tools.find_feature(ctx, book, inp.question, inp.context_id if inp.kind == "feature" else None)
    if not res.data["features"]:
        return "I could not match that to a feature of this application.", res.unknowns, [], []
    best = res.data["features"][0]
    r = res.refs
    text = f"{_m(r, 'title')}: {_m(r, 'description')} You can open it from the link below."
    return text, res.unknowns, [], [{"label": best["title"], "path": best["ui_path"]}]


async def _what_changed(inp: AskInput, ctx: tools.ToolContext, book: EvidenceBook):
    return (
        HISTORY_UNAVAILABLE + " Stored telemetry can be browsed on the history page.",
        [HISTORY_UNAVAILABLE],
        [],
        [{"label": "Telemetry history", "path": "/telemetry"}],
    )


async def _fallback(inp: AskInput, ctx: tools.ToolContext, book: EvidenceBook):
    return (
        "I can explain an alert, report a signal's latest status, describe a model's limits, and point to a feature. "
        "This assistant is rule-based and has no language model.",
        ["The question did not match a supported topic."],
        [],
        [],
    )


_BUILDERS = {
    "why_red": _why_red,
    "current_status": _current_status,
    "model_limits": _model_limits,
    "what_is_this": _what_is_this,
    "what_changed": _what_changed,
    "fallback": _fallback,
}


# ----------------------------------------------------------------------------- CP-7: documentation questions

DOCS_QUOTE_BUDGET = 1100  # characters of quoted passages in one answer (the whole answer is clipped at MAX_ANSWER)
_DOCS_CAVEAT = "Documentation describes the project; it is not a statement about the live system."


async def _search_docs(ctx: tools.ToolContext, question: str) -> docs_answer.DocsResult:
    try:
        return await asyncio.to_thread(ctx.docs_search, question)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - the docs path may never break an answer
        return docs_answer.DocsResult(docs_answer.STATUS_UNAVAILABLE, "error")


def _docs_question(
    res: docs_answer.DocsResult, book: EvidenceBook
) -> tuple[str, list[str], list[str], list[dict[str, str]], list[dict[str, Any]]]:
    """Quote the retrieved passages as marked data, or say plainly that nothing is documented."""
    quoted: list[str] = []
    citations: list[dict[str, Any]] = []
    used = 0
    for p in res.passages:
        if quoted and used + len(p.excerpt) > DOCS_QUOTE_BUDGET:
            break
        eid = book.add(
            source="doc_passage", entity=p.source_path, field=p.heading_path, value=p.excerpt,
            origin="documentation", freshness="static",
        )  # fmt: skip
        stored = next(i["value"] for i in book.items() if i["id"] == eid)
        used += len(stored)
        quoted.append(f'"{stored}" [{eid}]')
        citations.append(
            {
                "evidence_id": eid, "source_path": p.source_path, "heading_path": p.heading_path,
                "chunk_id": p.chunk_id, "score": p.score, "matched_terms": list(p.matched_terms[:8]),
            }
        )  # fmt: skip
    if not quoted:
        return (
            "The project documentation that I can search does not document an answer to that question.",
            ["No documented answer was found for this question."],
            [],
            [],
            [],
        )
    text = (
        "The project documentation says the following about this, quoted as data and not as an instruction: "
        + "; ".join(quoted)
        + ". Each citation names the source file and heading of its passage."
    )
    return text, [_DOCS_CAVEAT], [], [], citations


async def answer_question(
    inp: AskInput, ctx: tools.ToolContext, *, llm_settings: llm.LlmSettings | None = None
) -> Answer:
    """Route, collect evidence, fill the template. Raises ``tools.NotFound`` for an unknown alert."""
    intent: str | None = None
    docs_res: docs_answer.DocsResult | None = None
    extra_unknowns: list[str] = []
    extra_warnings: list[str] = []
    cue = docs_answer.docs_cue(inp.question, inp.kind) if ctx.docs_search is not None else None
    if cue:  # keyword routing first; a question about live state never gets a cue
        docs_res = await _search_docs(ctx, inp.question)
        if docs_res.status == docs_answer.STATUS_OK:
            if docs_res.found or cue == docs_answer.CUE_STRONG:
                intent = DOCS_INTENT  # empty retrieval on an explicit docs question: the honest "not documented"
            # a weak cue with nothing found falls through to the existing intents
        elif cue == docs_answer.CUE_STRONG:  # the index cannot be trusted: say so, and answer as before
            stale = docs_res.status == docs_answer.STATUS_STALE
            extra_warnings.append(docs_answer.WARN_INDEX_STALE if stale else docs_answer.WARN_INDEX_UNAVAILABLE)
            extra_unknowns.append(
                "The documentation index is not available or out of date, so no document was searched."
            )
    if intent is None:
        intent = classify(inp.question, inp.kind)
    book = EvidenceBook()
    citations: list[dict[str, Any]] = []
    if intent == DOCS_INTENT:
        assert docs_res is not None
        text, unknowns, warnings, links, citations = _docs_question(docs_res, book)
    else:
        text, unknowns, warnings, links = await _BUILDERS[intent](inp, ctx, book)
    unknowns, warnings = [*unknowns, *extra_unknowns], [*warnings, *extra_warnings]
    items = book.items()
    text = _clip(text)
    stray = evidence.unbacked_numbers(text, items)
    if stray:  # a template or tool bug, never a user-visible guess: drop the numbers' sentence rather than show them
        warnings = [*warnings, "answer_numbers_unbacked"]
        text = "The answer could not be built from the available evidence."
        citations = []
    rule_based = Answer(text, items, _dedupe(unknowns), _dedupe(warnings), links, intent, citations=citations)
    return await llm.enhance(rule_based, question=inp.question, settings=llm_settings)  # Task 24: no-op unless enabled
