"""CP-8: which providers may see which question, what a remote provider is shown, and how many slow calls may run at once.

Pure Python: no FastAPI, no database, no network, no import of ``llm.py`` (the dependency runs the other way).

* **Local-only mode.** ``COPILOT_LLM_LOCAL_ONLY=true`` removes every provider that is not flagged ``local`` from the chain.
* **Per-intent data policy.** A provider that is not flagged ``local`` is a *cloud* provider. It may only serve the intents
  in ``COPILOT_LLM_CLOUD_INTENTS``. Default: ``docs_question`` only. ``why_red`` (alert explanations) and
  ``current_status`` (a live signal) can be added; ``model_limits`` and ``what_is_this`` carry only project data.
  ``*`` means every configurable intent; ``none`` means no intent. A blocked intent is answered by a local provider if
  one is configured, else rule-based. Whatever is allowed, a cloud provider is shown only the reduced request below.
* **What a cloud provider is shown** (:func:`cloud_view`): the question with identifiers and numbers scrubbed, the
  evidence without alert ids, timestamps or alert text, the draft without those either. Numbers were already withheld
  (``llm.build_messages``). :func:`leaks` then checks the final request text for anything that was removed and the caller
  refuses to send if it finds one (fail closed).
* **Concurrency.** A model call can take many seconds and a thread cannot be cancelled, so at most
  ``COPILOT_LLM_MAX_CONCURRENT`` (default 4) chains run per process; the next question is answered rule-based at once.

Nothing here logs a question, an answer, a passage or telemetry.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import sanitize

ENV_LOCAL_ONLY = "COPILOT_LLM_LOCAL_ONLY"
ENV_CLOUD_INTENTS = "COPILOT_LLM_CLOUD_INTENTS"
ENV_MAX_CONCURRENT = "COPILOT_LLM_MAX_CONCURRENT"

INTENT_DOCS = "docs_question"
DEFAULT_CLOUD_INTENTS: tuple[str, ...] = (INTENT_DOCS,)
CONFIGURABLE_INTENTS: tuple[str, ...] = (INTENT_DOCS, "model_limits", "what_is_this", "why_red", "current_status")

DEFAULT_MAX_CONCURRENT = 4
MAX_CONCURRENT_LIMIT = 64

REASON_LOCAL_ONLY = "local_only"
REASON_INTENT = "intent_not_allowed_for_cloud"

_TRUE = {"1", "true", "yes", "on"}
_ALERT_SOURCES = ("alert_explanation",)
_PRIVATE_FIELDS = ("message",)  # the stored alert text


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def local_only(environ: Mapping[str, str] | None = None) -> bool:
    return str(_env(environ).get(ENV_LOCAL_ONLY, "")).strip().lower() in _TRUE


def cloud_intents(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The intents a cloud provider may serve. Unset or blank: the default. Unknown names are ignored. Never raises."""
    raw = str(_env(environ).get(ENV_CLOUD_INTENTS, "")).strip().lower()
    if not raw:
        return DEFAULT_CLOUD_INTENTS
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if "*" in names or "all" in names:
        return CONFIGURABLE_INTENTS
    if names == ["none"]:
        return ()
    return tuple(n for n in CONFIGURABLE_INTENTS if n in names)  # fixed order; unknown names are dropped


def max_concurrent(environ: Mapping[str, str] | None = None) -> int:
    try:
        value = int(str(_env(environ).get(ENV_MAX_CONCURRENT, "")).strip())
    except ValueError:
        return DEFAULT_MAX_CONCURRENT
    return value if 1 <= value <= MAX_CONCURRENT_LIMIT else DEFAULT_MAX_CONCURRENT


@dataclass(frozen=True)
class Filtered:
    providers: list[Any]  # the providers that may serve this intent, in their original order
    dropped: int
    reason: str | None  # why providers were dropped (None when none were)

    @property
    def blocked(self) -> bool:
        return not self.providers


def filter_chain(chain: Sequence[Any], intent: str, environ: Mapping[str, str] | None = None) -> Filtered:
    """Apply local-only mode and the per-intent cloud rule. ``chain`` items need a boolean ``local`` attribute."""
    if local_only(environ):
        kept, reason = [s for s in chain if getattr(s, "local", False)], REASON_LOCAL_ONLY
    elif intent in cloud_intents(environ):
        return Filtered(list(chain), 0, None)
    else:
        kept, reason = [s for s in chain if getattr(s, "local", False)], REASON_INTENT
    dropped = len(chain) - len(kept)
    return Filtered(kept, dropped, reason if dropped else None)


# ----------------------------------------------------------------------------- what a cloud provider is shown


@dataclass(frozen=True)
class CloudView:
    question: str
    draft: str
    evidence: list[dict[str, Any]]
    unknowns: list[str]
    links: list[dict[str, str]]  # labels such as "Alert 42" lose the id; the paths (what validate checks) are unchanged
    withheld: tuple[str, ...]  # exact strings that must not appear anywhere in the request (checked by :func:`leaks`)
    private: tuple[str, ...]  # the user's own names: must not appear in the text the user wrote (question, unknowns)

    @property
    def user_text(self) -> str:
        return " ".join([self.question, *self.unknowns])


_ALERT_NUMBER = re.compile(r"(?i)\b(alert)\s*#?\s*\d+\b")


def _alert_ids(evidence: Sequence[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in evidence:
        if item.get("source") in _ALERT_SOURCES:
            match = re.fullmatch(r"alert:(\d+)", str(item.get("entity", "")))
            if match:
                ids.append(match.group(1))
    return list(dict.fromkeys(ids))


def cloud_view(
    question: str,
    draft: str,
    evidence: Sequence[dict[str, Any]],
    unknowns: Sequence[str],
    private_terms: Sequence[str] = (),
    links: Sequence[dict[str, str]] = (),
) -> CloudView:
    """What a remote provider may be shown. The local validator keeps the full evidence; only the request is reduced."""
    withheld: list[str] = []
    shown: list[dict[str, Any]] = []
    clean_draft = draft
    for item in evidence:
        source, field = item.get("source"), item.get("field")
        if source in _ALERT_SOURCES and field in _PRIVATE_FIELDS:
            text = item.get("value")
            if isinstance(text, str) and text:
                withheld.append(text)
                clean_draft = clean_draft.replace(text, "(withheld)")
            continue  # the alert's own text is never part of a cloud request
        entry = dict(item)
        entry["observed_at"] = None  # no timestamp of a stored alert or a live reading leaves the machine
        if source in _ALERT_SOURCES:
            entry["entity"] = "alert"
        shown.append(entry)
    clean_draft = _ALERT_NUMBER.sub(lambda m: m.group(1), clean_draft)
    return CloudView(
        question=sanitize.scrub_for_cloud(question, private_terms),
        draft=clean_draft,
        evidence=shown,
        unknowns=[sanitize.scrub_for_cloud(u, private_terms) for u in unknowns],
        links=[
            {**link, "label": _ALERT_NUMBER.sub(lambda m: m.group(1), str(link.get("label", "")))} for link in links
        ],
        withheld=tuple(dict.fromkeys(w for w in withheld if w)),
        private=tuple(dict.fromkeys(t.strip() for t in private_terms if t and len(t.strip()) >= 2)),
    )


def _contains(folded: str, term: str) -> bool:
    """``term`` occurs in ``folded`` as a whole word where it starts or ends with a letter or digit (so a two-letter
    user name does not match inside \"alert\")."""
    left = r"(?<![a-z0-9_])" if term[:1].isalnum() or term[:1] == "_" else ""
    right = r"(?![a-z0-9_])" if term[-1:].isalnum() or term[-1:] == "_" else ""
    return re.search(f"{left}{re.escape(term)}{right}", folded) is not None


def leaks(
    request_text: str,
    withheld: Sequence[str],
    evidence: Sequence[dict[str, Any]] = (),
    *,
    user_text: str = "",
    private: Sequence[str] = (),
) -> list[str]:
    """Which checks fail for a cloud request (names only, never the values).

    ``withheld`` strings (alert text, a signal's name) may appear nowhere in ``request_text``; an alert id may not appear
    as ``alert <id>``; the user's own names may not appear in ``user_text`` (the question and unknowns). A user name is
    not searched for in documentation passages: a runbook that happens to say \"admin\" is not a leak."""
    found: list[str] = []
    folded = request_text.lower()
    if any(_contains(folded, w.lower()) for w in withheld if w):
        found.append("withheld_text")
    for alert_id in _alert_ids(evidence):
        if re.search(rf"alert\W{{0,3}}{re.escape(alert_id)}\b", folded):
            found.append("alert_id")
            break
    own = user_text.lower()
    if any(_contains(own, t.lower()) for t in private if t):
        found.append("user_name")
    return found


# ----------------------------------------------------------------------------- concurrency


class ConcurrencyGate:
    """A non-blocking counter. ``try_acquire`` never waits; ``release`` is called by the thread that really finished."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0

    def try_acquire(self, limit: int) -> bool:
        with self._lock:
            if self._active >= limit:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def reset(self) -> None:
        with self._lock:
            self._active = 0


GATE = ConcurrencyGate()
