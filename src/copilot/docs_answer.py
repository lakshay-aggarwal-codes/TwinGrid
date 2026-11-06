"""CP-7: answering "what do the docs say" questions from retrieved passages. Pure Python; no model, no network.

Three jobs, all deterministic:

* **Routing cues** (:func:`docs_cue`): keyword rules that say whether a question may be a documentation question. A
  *strong* cue ("the runbook", "documentation") is an explicit request for the docs. A *weak* cue ("how do I ...")
  only counts on a general question. A question about *live state* ("current", "right now", "is it healthy") is never
  routed here, whatever else it says: live state comes from the existing tools, never from documents.
* **Retrieval** (:class:`DocsRetriever`): loads the CP-6 index once, re-checks it against the documents on disk at most
  every ``ttl_s`` seconds, and searches it. A missing, incompatible or stale index is *unavailable*: the Copilot never
  cites passages from an index that no longer matches the documents.
* **Passages as data** (:func:`excerpt`, :func:`defang`): the text of a passage that enters an answer is shortened to
  the sentences that matched, and made inert (links, markup, ``{{ }}`` and ``[E#]`` lookalikes removed). CP-8 hardens
  this further; this is the minimum so a passage cannot forge a marker, a link or a placeholder.

Logs: status, reason, hit count and best score. Never the question or a passage.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import sanitize
from .rag import index as rag_index
from .rag import search as rag_search
from .rag.tokenize import tokenize

logger = logging.getLogger(__name__)

STATUS_OK = "ok"  # the index is fresh and was searched (there may still be no hit)
STATUS_UNAVAILABLE = "unavailable"  # no usable index (missing or incompatible)
STATUS_STALE = "stale"  # the documents changed since the index was built

CUE_STRONG = "strong"
CUE_WEAK = "weak"

WARN_INDEX_UNAVAILABLE = "docs_index_unavailable"
WARN_INDEX_STALE = "docs_index_stale"

DEFAULT_K = 3
DEFAULT_TTL_S = 60.0
EXCERPT_CHARS = 350  # per passage; a doc_passage evidence value is capped at evidence.MAX_PASSAGE

_STRONG = re.compile(
    r"\b(?:docs?|documentation|documented|runbooks?|readme|handbook|playbook|procedures?|model cards?)\b", re.IGNORECASE
)
_WEAK = re.compile(
    r"\bhow (?:do|can|should|would|could) (?:i|we|you)\b|\bhow to\b|\bsteps? (?:to|for)\b|\bset ?up\b|\bconfigure\b"
    r"|\binstall\b|\benable\b|\bdisable\b|\brotate\b|\brotating\b|\brebuild\b|\brestore\b|\brecover\b|\btroubleshoot\b",
    re.IGNORECASE,
)
_NAVIGATION = re.compile(r"\b(?:find|open|page|navigate|where can)\b", re.IGNORECASE)  # the feature catalogue's job
_LIVE = re.compile(
    r"\b(?:right now|currently|current|latest|at the moment|as of now|just now)\b"
    r"|\bis (?:it|this|that|the [\w .-]{1,30}?) (?:ok|okay|normal|healthy|fine|up|down|red|stale)\b",
    re.IGNORECASE,
)


_CUE_ONLY = re.compile(r"\b(?:docs?|documentation|documented)\b", re.IGNORECASE)


def search_query(question: str) -> str:
    """The question without the words that only ask for the docs ("docs", "documentation"), which would match every file."""
    return _CUE_ONLY.sub(" ", question)


def docs_cue(question: str, kind: str) -> str | None:
    """``"strong"``, ``"weak"`` or ``None``. Never routes a live-state question; never overrides a selected alert/signal."""
    if _LIVE.search(question):
        return None
    if _STRONG.search(question):
        return CUE_STRONG
    if kind == "general" and _WEAK.search(question) and not _NAVIGATION.search(question):
        return CUE_WEAK
    return None


# ----------------------------------------------------------------------------- passages as inert data

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def defang(text: str) -> str:
    """Make quoted documentation inert (CP-8: ``sanitize.neutralize``: Unicode normalised; no link, markup, placeholder,
    ``[E#]`` lookalike, prompt delimiter, chat token or role label)."""
    return sanitize.neutralize(text)


def _heading(path: str) -> str:
    """A heading path (``A > B``) with each part neutralised; the `` > `` separator is ours and stays."""
    return " > ".join(sanitize.neutralize(part) for part in str(path).split(" > "))


def excerpt(text: str, terms: tuple[str, ...], cap: int = EXCERPT_CHARS) -> str:
    """The sentences of ``text`` around the best match for ``terms`` (stemmed), at most ``cap`` characters, defanged."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return ""
    wanted = set(terms)
    scores = [len(wanted & set(tokenize(s))) for s in sentences]
    start = max(range(len(sentences)), key=lambda i: (scores[i], -i))  # earliest sentence among the best
    out = ""
    for sentence in sentences[start:]:
        candidate = f"{out} {sentence}".strip()
        if out and len(candidate) > cap:
            break
        out = candidate
    out = defang(out)
    if len(out) > cap:
        out = out[: cap - 1].rstrip() + "…"
    return out


# ----------------------------------------------------------------------------- retrieval


@dataclass(frozen=True)
class DocsPassage:
    chunk_id: str
    source_path: str
    heading_path: str
    excerpt: str
    score: float
    matched_terms: tuple[str, ...]
    flags: tuple[str, ...] = ()  # CP-8: instruction-like cues found in the whole chunk (sanitize.injection_cues)


@dataclass(frozen=True)
class DocsResult:
    status: str  # STATUS_*
    reason: str = ""  # search reason (ok, below_threshold, ...) or why the index is unusable
    passages: tuple[DocsPassage, ...] = ()
    best_score: float = 0.0

    @property
    def found(self) -> bool:
        return self.status == STATUS_OK and bool(self.passages)


class DocsRetriever:
    """Callable ``retriever(question) -> DocsResult``. Thread-safe; never raises."""

    def __init__(
        self,
        index_path: Path | str | None = None,
        root: Path | None = None,
        *,
        k: int = DEFAULT_K,
        min_score: float | None = None,
        min_coverage: float | None = None,
        ttl_s: float = DEFAULT_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = index_path
        self._root = root
        self._k = k
        self._min_score = min_score
        self._min_coverage = min_coverage
        self._ttl = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_at: float | None = None
        self._state: tuple[str, str, rag_index.DocsIndex | None] = (STATUS_UNAVAILABLE, "not loaded", None)

    def _refresh(self) -> tuple[str, str, rag_index.DocsIndex | None]:
        with self._lock:
            now = self._clock()
            if self._checked_at is not None and now - self._checked_at < self._ttl:
                return self._state
            try:
                index = rag_index.load_index(self._path)
                freshness = rag_index.compare_with_disk(index, self._root)
                if freshness.usable:
                    state = (STATUS_OK, "fresh", index)
                else:
                    state = (STATUS_STALE, freshness.reason, None)
            except rag_index.IndexUnavailable as exc:
                state = (STATUS_UNAVAILABLE, f"{exc.status}: {exc.reason}", None)
            except Exception as exc:  # noqa: BLE001 - a broken index must degrade, never raise
                state = (STATUS_UNAVAILABLE, f"error: {exc.__class__.__name__}", None)
            self._state, self._checked_at = state, now
            return state

    def __call__(self, question: str) -> DocsResult:
        status, reason, index = self._refresh()
        if index is None:
            logger.info("copilot_docs status=%s hits=0", status)
            return DocsResult(status, reason)
        try:
            found = rag_search.search(
                index, search_query(question), self._k, min_score=self._min_score, min_coverage=self._min_coverage
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("copilot_docs search_error=%s", exc.__class__.__name__)
            return DocsResult(STATUS_UNAVAILABLE, f"error: {exc.__class__.__name__}")
        passages = tuple(
            DocsPassage(
                h.chunk.chunk_id, sanitize.neutralize(h.chunk.source_path), _heading(h.chunk.heading_path),
                excerpt(h.chunk.text, h.matched_terms), h.score, h.matched_terms,
                sanitize.injection_cues(f"{h.chunk.heading_path}\n{h.chunk.text}"),
            )
            for h in found.hits
        )  # fmt: skip
        passages = tuple(p for p in passages if p.excerpt)
        logger.info("copilot_docs status=ok reason=%s hits=%d best=%.2f", found.reason, len(passages), found.best_score)
        return DocsResult(STATUS_OK, found.reason, passages, found.best_score)


_SHARED: DocsRetriever | None = None
_SHARED_LOCK = threading.Lock()


def shared_retriever() -> DocsRetriever:
    """The one retriever the API route shares across requests (default index location, repo root), so the index is
    loaded once and re-checked at most every ``DEFAULT_TTL_S`` seconds."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = DocsRetriever()
        return _SHARED
