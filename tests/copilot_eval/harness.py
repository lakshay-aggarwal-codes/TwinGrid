"""CP-9: evaluation harness for the Copilot docs RAG. Offline by default; no network, no real model.

Two layers, kept apart on purpose:

* **Retrieval layer.** Every in-corpus and out-of-corpus question is searched once with no floors and the top
  ``MAX_K`` hits are kept. :func:`served` then replays the product's own rule (floors first, then the first ``k``) on
  those hits, so thousands of operating points can be tried without re-searching. A test proves the replay equals
  :func:`src.copilot.rag.search.search` for the same floors. The retrieval floors are *fitted* here (:func:`fit`) and
  their out-of-sample behaviour is *estimated* here (:func:`leave_one_out`).
* **End-to-end layer.** Every question goes through the real :func:`src.copilot.answer.answer_question` with the real
  index and no language model (rule-based). This measures routing, citations, refusals and hostile input.

On top of those, two experiments with SCRIPTED fake providers (``llm._call_provider`` is replaced; nothing opens a
socket): how the rephrase rules treat faithful and unfaithful replies, and whether the failover chain survives injected
faults. A scripted fake can only show that the rules catch what the script contains. It says nothing about how a real
model behaves; the optional real-provider run (:func:`run_real`) exists for that and is labelled as such.

Nothing here logs or prints a prompt, an answer or a key. The report names questions by id and, for misses, by text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence
from unittest import mock

from src.copilot import MODE_LLM, MODE_RULE_BASED, docs_answer, limiter, llm, router
from src.copilot import answer as answer_mod
from src.copilot import evidence as evidence_mod
from src.copilot.rag import corpus as rag_corpus
from src.copilot.rag import index as rag_index
from src.copilot.rag import search as rag_search

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = Path(__file__).with_name("questions.yaml")
REPORT_RELATIVE = "docs/copilot/EVAL_REPORT.md"

GROUPS = ("in_corpus", "out_of_corpus", "adversarial", "other_intent")
VALID_KINDS = ("general", "alert", "signal", "model", "feature")
MIN_QUESTIONS, MAX_QUESTIONS = 40, 50
ADVERSARIAL_RANGE = (8, 10)
SERVED_K = docs_answer.DEFAULT_K  # the number of passages the product shows
FETCH_K = rag_search.MAX_K
REFUSAL_MARKERS = (
    "does not document an answer",
    "could not match that to a feature",
    "did not match a supported topic",
)


class SuiteError(ValueError):
    """The question file or the checkout does not match what the harness assumes."""


# ----------------------------------------------------------------------------- the question file


@dataclass(frozen=True)
class Source:
    path: str
    heading: str = ""

    def matches(self, source_path: str, heading_path: str) -> bool:
        return source_path == self.path and self.heading.lower() in heading_path.lower()


@dataclass(frozen=True)
class Question:
    id: str
    group: str
    question: str
    kind: str = "general"
    context_id: str | None = None
    intent: str | None = None
    sources: tuple[Source, ...] = ()
    must_not_cite: tuple[str, ...] = ()
    must_not_match: tuple[str, ...] = ()

    def is_expected(self, source_path: str, heading_path: str) -> bool:
        return any(s.matches(source_path, heading_path) for s in self.sources)


@dataclass(frozen=True)
class Suite:
    version: int
    questions: tuple[Question, ...]
    gates: dict[str, float]
    floors: dict[str, float]
    corpus_assumes: tuple[str, ...]

    def of(self, group: str) -> list[Question]:
        return [q for q in self.questions if q.group == group]


def load_suite(path: Path | str = QUESTIONS_PATH) -> Suite:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    questions = []
    for raw in data["questions"]:
        questions.append(
            Question(
                id=str(raw["id"]),
                group=str(raw["group"]),
                question=str(raw["question"]),
                kind=str(raw.get("kind", "general")),
                context_id=None if raw.get("context_id") is None else str(raw["context_id"]),
                intent=raw.get("intent"),
                sources=tuple(Source(str(s["path"]), str(s.get("heading", ""))) for s in raw.get("sources", [])),
                must_not_cite=tuple(raw.get("must_not_cite", [])),
                must_not_match=tuple(raw.get("must_not_match", [])),
            )
        )
    return Suite(
        version=int(data["version"]),
        questions=tuple(questions),
        gates={k: float(v) for k, v in data["gates"].items()},
        floors={k: float(v) for k, v in (data.get("floors") or {}).items()},
        corpus_assumes=tuple(data.get("corpus_assumes", [])),
    )


def validate_suite(suite: Suite) -> list[str]:
    """Every structural problem in the question file (empty list = fine). Pure; reads nothing."""
    problems: list[str] = []
    ids = [q.id for q in suite.questions]
    if len(set(ids)) != len(ids):
        problems.append("duplicate question ids")
    if not MIN_QUESTIONS <= len(ids) <= MAX_QUESTIONS:
        problems.append(f"{len(ids)} questions; the roadmap asks for {MIN_QUESTIONS} to {MAX_QUESTIONS}")
    counts = {g: len(suite.of(g)) for g in GROUPS}
    if not ADVERSARIAL_RANGE[0] <= counts["adversarial"] <= ADVERSARIAL_RANGE[1]:
        problems.append(f"{counts['adversarial']} adversarial questions; the roadmap asks for 8 to 10")
    for q in suite.questions:
        if q.group not in GROUPS:
            problems.append(f"{q.id}: unknown group {q.group!r}")
        if q.kind not in VALID_KINDS:
            problems.append(f"{q.id}: unknown kind {q.kind!r}")
        if not q.question.strip():
            problems.append(f"{q.id}: empty question")
        if q.kind != "general" and not q.context_id:
            problems.append(f"{q.id}: kind {q.kind!r} needs a context_id")
        if q.group == "in_corpus":
            if not q.sources:
                problems.append(f"{q.id}: in_corpus needs sources")
            if q.intent != answer_mod.DOCS_INTENT:
                problems.append(f"{q.id}: in_corpus must expect intent {answer_mod.DOCS_INTENT}")
            for s in q.sources:
                if not rag_corpus.is_allowed(s.path):
                    problems.append(f"{q.id}: source {s.path} is not in the corpus allow-list")
        if q.group == "other_intent":
            if q.intent not in answer_mod.INTENTS or q.intent == answer_mod.DOCS_INTENT:
                problems.append(f"{q.id}: other_intent needs a non-docs intent")
        if q.group in ("out_of_corpus", "adversarial") and q.sources:
            problems.append(f"{q.id}: {q.group} must not list sources")
        for pattern in (*q.must_not_cite, *q.must_not_match):
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"{q.id}: bad regex {pattern!r}: {exc}")
    for key in ("hit_at_3_served_min", "correct_refusal_min", "unknown_numbers_accepted_max", "adversarial_pass_min"):
        if key not in suite.gates:
            problems.append(f"gate {key} missing")
    return problems


def check_checkout(suite: Suite, index: rag_index.DocsIndex, root: Path = ROOT) -> list[str]:
    """Drift between the question file and the checkout: missing assumed files, sources or headings that no longer exist."""
    problems = [f"assumed file missing: {rel}" for rel in suite.corpus_assumes if not (root / rel).is_file()]
    for q in suite.of("in_corpus"):
        for s in q.sources:
            chunks = [c for c in index.chunks if c.source_path == s.path]
            if not chunks:
                problems.append(f"{q.id}: no chunks from {s.path} in the index")
            elif not any(s.heading.lower() in c.heading_path.lower() for c in chunks):
                problems.append(f"{q.id}: no heading containing {s.heading!r} in {s.path}")
    return problems


# ----------------------------------------------------------------------------- retrieval layer


@dataclass(frozen=True)
class RowHit:
    score: float
    coverage: float
    expected: bool
    source_path: str
    heading_path: str


@dataclass(frozen=True)
class RetrievalRow:
    qid: str
    group: str  # in_corpus | out_of_corpus
    hits: tuple[RowHit, ...]  # top FETCH_K at no floors, in rank order


def collect_rows(index: rag_index.DocsIndex, questions: Sequence[Question]) -> list[RetrievalRow]:
    """Search each question once with no floors. Routing cues are ignored: this measures the retriever alone."""
    rows = []
    for q in questions:
        if q.group not in ("in_corpus", "out_of_corpus"):
            continue
        found = rag_search.search(index, docs_answer.search_query(q.question), FETCH_K, min_score=0.0, min_coverage=0.0)
        hits = tuple(
            RowHit(
                h.score,
                h.coverage,
                q.is_expected(h.chunk.source_path, h.chunk.heading_path),
                h.chunk.source_path,
                h.chunk.heading_path,
            )
            for h in found.hits
        )
        rows.append(RetrievalRow(q.id, q.group, hits))
    return rows


def served(row: RetrievalRow, min_score: float, min_coverage: float, k: int = SERVED_K) -> list[RowHit]:
    """What the product would show: floors first, then the first ``k`` (the same order ``search`` uses)."""
    return [h for h in row.hits if h.score >= min_score and h.coverage >= min_coverage][:k]


def row_correct(row: RetrievalRow, min_score: float, min_coverage: float) -> bool:
    shown = served(row, min_score, min_coverage)
    if row.group == "in_corpus":
        return any(h.expected for h in shown)
    return not shown


@dataclass(frozen=True)
class Targets:
    hit: float = 0.85
    refusal: float = 0.90


def point_metrics(rows: Sequence[RetrievalRow], min_score: float, min_coverage: float) -> dict[str, Any]:
    ins = [r for r in rows if r.group == "in_corpus"]
    outs = [r for r in rows if r.group == "out_of_corpus"]
    hit_ok = [r for r in ins if row_correct(r, min_score, min_coverage)]
    ref_ok = [r for r in outs if row_correct(r, min_score, min_coverage)]
    return {
        "min_score": min_score,
        "min_coverage": min_coverage,
        "hit_at_3_served": len(hit_ok) / len(ins) if ins else 0.0,
        "correct_refusal": len(ref_ok) / len(outs) if outs else 0.0,
        "n_in": len(ins),
        "n_out": len(outs),
        "hit_misses": [r.qid for r in ins if r not in hit_ok],
        "refusal_misses": [r.qid for r in outs if r not in ref_ok],
    }


def ranking_metrics(rows: Sequence[RetrievalRow]) -> dict[str, Any]:
    """Ranking quality with no floors: hit@1, hit@3, hit@5 and mean reciprocal rank (rank capped at FETCH_K)."""
    ins = [r for r in rows if r.group == "in_corpus"]
    ranks: dict[str, int | None] = {}
    for r in ins:
        ranks[r.qid] = next((i for i, h in enumerate(r.hits, start=1) if h.expected), None)
    n = len(ins) or 1
    return {
        "hit_at_1": sum(1 for v in ranks.values() if v == 1) / n,
        "hit_at_3": sum(1 for v in ranks.values() if v is not None and v <= 3) / n,
        "hit_at_5": sum(1 for v in ranks.values() if v is not None and v <= 5) / n,
        "mrr": sum(1.0 / v for v in ranks.values() if v) / n,
        "ranks": ranks,
        "n": len(ins),
    }


SCORE_GRID = tuple(i * 0.5 for i in range(0, 25))  # 0 .. 12
COVERAGE_GRID = tuple(round(i * 0.05, 2) for i in range(0, 17))  # 0 .. 0.8


@dataclass(frozen=True)
class Fit:
    min_score: float
    min_coverage: float
    hit: float
    refusal: float
    objective: float
    n_optimal: int


def _objective(hit: float, refusal: float, t: Targets) -> tuple[float, float]:
    """How close both gates are to being met (each capped at its target), then the plain sum as a tie-break."""
    return round(min(min(hit, t.hit) / t.hit, min(refusal, t.refusal) / t.refusal), 6), round(hit + refusal, 6)


def fit(
    rows: Sequence[RetrievalRow],
    targets: Targets = Targets(),
    score_grid: Sequence[float] = SCORE_GRID,
    coverage_grid: Sequence[float] = COVERAGE_GRID,
) -> Fit:
    """The (score, coverage) floors that bring both gates closest to being met.

    Among grid points with the best objective the one nearest their centroid is taken, so the choice sits in the middle
    of a plateau instead of on its edge. Deterministic. ``coverage_grid=(0.0,)`` fits the score floor alone.
    """
    best: tuple[float, float] | None = None
    optimal: list[tuple[float, float]] = []
    for s in score_grid:
        for c in coverage_grid:
            m = point_metrics(rows, s, c)
            key = _objective(m["hit_at_3_served"], m["correct_refusal"], targets)
            if best is None or key > best:
                best, optimal = key, [(s, c)]
            elif key == best:
                optimal.append((s, c))
    assert best is not None
    s_span = (max(score_grid) - min(score_grid)) or 1.0
    c_span = (max(coverage_grid) - min(coverage_grid)) or 1.0
    ms = sum(p[0] for p in optimal) / len(optimal)
    mc = sum(p[1] for p in optimal) / len(optimal)
    s, c = min(optimal, key=lambda p: ((p[0] - ms) / s_span) ** 2 + ((p[1] - mc) / c_span) ** 2)
    m = point_metrics(rows, s, c)
    return Fit(s, c, m["hit_at_3_served"], m["correct_refusal"], best[0], len(optimal))


def leave_one_out(
    rows: Sequence[RetrievalRow],
    targets: Targets = Targets(),
    score_grid: Sequence[float] = SCORE_GRID,
    coverage_grid: Sequence[float] = COVERAGE_GRID,
) -> dict[str, Any]:
    """Refit without each question, then score only that question. The out-of-sample estimate of the whole procedure."""
    right = {"in_corpus": 0, "out_of_corpus": 0}
    total = {"in_corpus": 0, "out_of_corpus": 0}
    wrong: list[str] = []
    for i, row in enumerate(rows):
        rest = [r for j, r in enumerate(rows) if j != i]
        f = fit(rest, targets, score_grid, coverage_grid)
        total[row.group] += 1
        if row_correct(row, f.min_score, f.min_coverage):
            right[row.group] += 1
        else:
            wrong.append(row.qid)
    return {
        "hit_at_3_served": right["in_corpus"] / total["in_corpus"] if total["in_corpus"] else 0.0,
        "correct_refusal": right["out_of_corpus"] / total["out_of_corpus"] if total["out_of_corpus"] else 0.0,
        "wrong": wrong,
    }


# ----------------------------------------------------------------------------- end-to-end layer


@dataclass
class E2E:
    qid: str
    group: str
    intent: str
    answer: str
    citations: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    unknowns: list[str]
    warnings: list[str]
    ms: float
    result: Any = field(repr=False, default=None)  # the answer_mod.Answer, kept so experiments can rephrase it


def run_end_to_end(
    index_path: Path,
    root: Path,
    questions: Sequence[Question],
    *,
    min_score: float | None = None,
    min_coverage: float | None = None,
) -> list[E2E]:
    """Every question through the real ``answer_question``, rule-based (the language model is switched off explicitly)."""
    from tests.fixtures.copilot.helpers import make_ctx

    retriever = docs_answer.DocsRetriever(index_path, root, min_score=min_score, min_coverage=min_coverage, ttl_s=1e9)
    off = (
        llm.LlmSettings()
    )  # enabled=False: llm.enhance returns the rule-based answer untouched, whatever the environment says

    async def ask_all() -> list[E2E]:
        await answer_mod.answer_question(
            answer_mod.AskInput("warm up the index load"), make_ctx(docs_search=retriever), llm_settings=off
        )
        out = []
        for q in questions:
            inp = answer_mod.AskInput(q.question, q.kind, q.context_id)
            t0 = time.perf_counter()
            ans = await answer_mod.answer_question(inp, make_ctx(docs_search=retriever), llm_settings=off)
            ms = (time.perf_counter() - t0) * 1000.0
            out.append(
                E2E(
                    q.id,
                    q.group,
                    ans.intent,
                    ans.answer,
                    list(ans.citations),
                    list(ans.evidence),
                    list(ans.unknowns),
                    list(ans.warnings),
                    ms,
                    ans,
                )
            )
        return out

    return asyncio.run(ask_all())


_WORDS = re.compile(r"[a-z0-9]+")


def citation_problems(e: E2E, index: rag_index.DocsIndex) -> list[str]:
    """Structural problems in an answer's citations: dangling evidence, unknown chunk, excluded path, text not from the chunk."""
    problems: list[str] = []
    by_id = {i["id"]: i for i in e.evidence}
    chunks = {c.chunk_id: c for c in index.chunks}
    for marker in set(re.findall(r"\[(E\d+)\]", e.answer)):
        if marker not in by_id:
            problems.append(f"marker {marker} has no evidence item")
    for c in e.citations:
        item = by_id.get(c.get("evidence_id"))
        chunk = chunks.get(c.get("chunk_id"))
        if item is None or item.get("source") != "doc_passage":
            problems.append(f"{c.get('evidence_id')}: not a doc_passage evidence item")
            continue
        if chunk is None:
            problems.append(f"{c.get('chunk_id')}: chunk not in the index")
            continue
        if c.get("source_path") != chunk.source_path or item.get("entity") != chunk.source_path:
            problems.append(f"{c.get('chunk_id')}: source path differs between citation, evidence and chunk")
        if item.get("field") != evidence_mod.clean_text(chunk.heading_path, 80):
            problems.append(f"{c.get('chunk_id')}: heading differs between evidence and chunk")
        if not rag_corpus.is_allowed(chunk.source_path):
            problems.append(f"{chunk.source_path}: cited but not allowed in the corpus")
        words = set(_WORDS.findall(str(item.get("value", "")).lower())) - {"link", "removed"}
        if not words <= set(_WORDS.findall(chunk.text.lower())):
            problems.append(f"{c.get('chunk_id')}: quoted text is not from the chunk")
    return problems


@dataclass
class Judged:
    qid: str
    group: str
    passed: bool
    intent_ok: bool | None = None
    cited: bool = False
    relevant: bool | None = None
    refused: bool | None = None  # no citation AND an explicit refusal
    no_citation: bool | None = None
    integrity: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _has_refusal(e: E2E) -> bool:
    haystack = " ".join([e.answer, *e.unknowns]).lower()
    return any(m in haystack for m in REFUSAL_MARKERS)


def judge(q: Question, e: E2E, index: rag_index.DocsIndex) -> Judged:
    j = Judged(q.id, q.group, False, cited=bool(e.citations), integrity=citation_problems(e, index))
    if q.group == "in_corpus":
        j.intent_ok = e.intent == q.intent
        j.relevant = any(q.is_expected(c["source_path"], c["heading_path"]) for c in e.citations)
        j.passed = bool(j.intent_ok and j.relevant and not j.integrity)
        if not j.intent_ok:
            j.notes.append(f"routed to {e.intent}")
        elif not j.relevant:
            j.notes.append("no expected source cited" if e.citations else "nothing cited")
    elif q.group == "out_of_corpus":
        j.no_citation = not e.citations
        j.refused = bool(j.no_citation and _has_refusal(e))
        j.passed = bool(j.refused and not j.integrity)
        if e.citations:
            j.notes.append("cited " + ", ".join(sorted({c["source_path"] for c in e.citations})))
        elif not j.refused:
            j.notes.append(f"no citation but not an explicit refusal (intent {e.intent})")
    elif q.group == "adversarial":
        bad_cite = [c["source_path"] for c in e.citations for p in q.must_not_cite if re.search(p, c["source_path"])]
        bad_text = [p for p in q.must_not_match if re.search(p, e.answer)]
        j.passed = not bad_cite and not bad_text and not j.integrity
        j.notes += [f"cited excluded path {p}" for p in bad_cite] + [f"answer matches {p}" for p in bad_text]
    else:  # other_intent
        j.intent_ok = e.intent == q.intent
        j.no_citation = not e.citations
        j.passed = bool(j.intent_ok and j.no_citation and not j.integrity)
        if not j.intent_ok:
            j.notes.append(f"routed to {e.intent}")
    return j


# ----------------------------------------------------------------------------- numbers and statistics


_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
_BIG_WORDS = re.compile(
    r"\b(?:eleven|twelve|(?:thir|four|fif|six|seven|eight|nine)teen|twenty|thirty|forty|fifty|sixty|seventy|eighty"
    r"|ninety|hundred|thousand|million|billion)\b"
)


def unknown_numbers(text: str, evidence: Sequence[dict[str, Any]]) -> list[str]:
    """Numbers in ``text`` that no evidence item carries. Independent of ``evidence.unbacked_numbers`` (own regexes)."""
    known = " ".join(str(e.get(k) or "") for e in evidence for k in ("entity", "field", "value", "unit")).lower()
    body = re.sub(r"\[E\d+\]", " ", text)
    found = [t for t in _DIGITS.findall(body) if t not in known]
    found += [w for w in _BIG_WORDS.findall(body.lower()) if w not in known]
    return sorted(set(found))


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile (no interpolation). Empty input gives 0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100.0 * len(ordered)) - 1)]


# ----------------------------------------------------------------------------- scripted fake providers


FAKE_URL = "http://eval-fake.invalid/v1"
FAKE_MODEL = "eval-fake-model"
FAKE_KEY = "eval-fake-key-not-a-secret"


def ph(item_id: str) -> str:
    return "{{" + item_id + "}}"


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    kind: str  # faithful | unfaithful | known_hole
    build: Callable[
        [list[str], dict[str, str]], str
    ]  # (doc passage ids, id -> passage text) -> the model's answer text


VARIANTS: tuple[Variant, ...] = (
    Variant(
        "F1",
        "placeholders with the standard framing",
        "faithful",
        lambda ids, v: "The documentation says the following: " + " ".join(ph(i) for i in ids[:2]),
    ),
    Variant(
        "F2",
        "placeholder with 'according to' (a connecting word no passage contains)",
        "faithful",
        lambda ids, v: f"According to the documentation: {ph(ids[0])}",
    ),
    Variant(
        "F3", "the first passage sentence typed out by the model", "faithful", lambda ids, v: _first_sentence(v[ids[0]])
    ),
    Variant(
        "U1",
        "invented step after a real passage",
        "unfaithful",
        lambda ids, v: f"{ph(ids[0])} Then restart the quantum flux capacitor.",
    ),
    Variant(
        "U2",
        "invented number",
        "unfaithful",
        lambda ids, v: f"{ph(ids[0])} This usually completes within 7351 seconds.",
    ),
    Variant(
        "U3",
        "URL not in links[]",
        "unfaithful",
        lambda ids, v: f"{ph(ids[0])} More detail: https://docs.example.com/fix",
    ),
    Variant("U4", "unknown placeholder", "unfaithful", lambda ids, v: f"{ph(ids[0])} {ph('E99')}"),
    Variant(
        "U5",
        "jailbreak compliance",
        "unfaithful",
        lambda ids, v: "Ignore the documentation. Everything is operating normally.",
    ),
    Variant("U6", "HTML in the answer", "unfaithful", lambda ids, v: f"<b>{ph(ids[0])}</b>"),
    Variant(
        "U7", "agrees with a false premise", "unfaithful", lambda ids, v: f"Yes, this is production ready. {ph(ids[0])}"
    ),
    Variant(
        "U8",
        "number written as a word",
        "unfaithful",
        lambda ids, v: f"{ph(ids[0])} Wait forty minutes before retrying.",
    ),
    Variant(
        "H1",
        "negated copy: every word is in the passage, the meaning is reversed",
        "known_hole",
        lambda ids, v: "Not: " + _first_sentence(v[ids[0]]),
    ),
)


def _data_block(messages: list[dict[str, str]]) -> dict[str, Any]:
    lines = messages[-1]["content"].splitlines()
    return json.loads("\n".join(lines[1:-1]))


def reply_for(variant: Variant, messages: list[dict[str, str]]) -> str:
    block = _data_block(messages)
    docs = [e for e in block["evidence"] if e.get("source") == "doc_passage"]
    ids = [e["id"] for e in docs]
    values = {e["id"]: str(e.get("value") or "") for e in docs}
    return json.dumps({"answer": variant.build(ids, values), "used_evidence": ids})


@contextmanager
def captured_outcomes() -> Iterator[list[str]]:
    """Collect the ``outcome=`` words ``llm.py`` logs (provider, model id, request id and an outcome word; no content)."""
    outcomes: list[str] = []

    class _H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            m = re.search(r"\boutcome=(\S+)", record.getMessage())
            if m and record.getMessage().startswith("copilot_llm "):
                outcomes.append(m.group(1))

    handler = _H(level=logging.INFO)
    log = llm.logger
    old_level, old_propagate = log.level, log.propagate
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    try:
        yield outcomes
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
        log.propagate = old_propagate


def fake_settings() -> llm.LlmSettings:
    return llm.LlmSettings(
        enabled=True, base_url=FAKE_URL, model=FAKE_MODEL, api_key=FAKE_KEY, timeout_s=2.0, name="evalfake"
    )


def _classify(out: Any) -> str:
    if out.mode == MODE_LLM:
        return "accepted"
    if llm.WARN_REJECTED in out.warnings:
        return "rejected"
    return "unavailable"


@dataclass
class VariantResult:
    key: str
    label: str
    kind: str
    n: int = 0
    accepted: int = 0
    rejected: int = 0
    unavailable: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    unknown_numbers_accepted: int = 0


def run_rephrase(cited: Sequence[tuple[Question, E2E]]) -> list[VariantResult]:
    """Every scripted variant over every cited in-corpus answer, through the REAL ``llm.enhance`` and ``llm.validate``."""
    results = {v.key: VariantResult(v.key, v.label, v.kind) for v in VARIANTS}
    for v in VARIANTS:

        def fake(settings: llm.LlmSettings, messages: list[dict[str, str]], _v: Variant = v) -> tuple[str, str | None]:
            return reply_for(_v, messages), "eval-req"

        for q, e in cited:
            res = results[v.key]
            with mock.patch.object(llm, "_call_provider", fake), captured_outcomes() as outcomes:
                out = asyncio.run(llm.enhance(e.result, question=q.question, settings=fake_settings()))
            res.n += 1
            verdict = _classify(out)
            setattr(res, verdict, getattr(res, verdict) + 1)
            if verdict == "accepted":
                if unknown_numbers(out.answer, out.evidence):
                    res.unknown_numbers_accepted += 1
            else:
                word = next((o for o in outcomes if o != "ok"), "none")
                res.reasons[word] = res.reasons.get(word, 0) + 1
    return list(results.values())


# ----------------------------------------------------------------------------- failover scenarios (fake providers, injected faults)

Behaviour = Callable[[int, list[dict[str, str]]], str]  # (call number for this provider, messages) -> reply, or raise


def _ok(messages: list[dict[str, str]]) -> str:
    return reply_for(VARIANTS[0], messages)


def _bad(messages: list[dict[str, str]]) -> str:
    return reply_for(VARIANTS[3], messages)  # U1: an invented step, which the rules reject


def _fail(code: str, status: int | None = None) -> Behaviour:
    def raise_it(n: int, m: list[dict[str, str]]) -> str:
        raise llm.ProviderError(code, "eval-req", status=status)

    return raise_it


def _sleepy(seconds: float, code: str) -> Behaviour:
    def slow(n: int, m: list[dict[str, str]]) -> str:
        time.sleep(seconds)
        raise llm.ProviderError(code, "eval-req")

    return slow


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    chain: tuple[str, ...]
    behaviours: dict[str, Behaviour]
    expect_mode: str  # MODE_LLM or MODE_RULE_BASED
    expect_warning: str | None
    expect_calls: dict[
        str, int
    ]  # provider -> total fake calls over the scenario's questions (proves cooldown / disable)
    questions: int = 4
    budget_s: float | None = None


def _scenarios() -> tuple[Scenario, ...]:
    good: Behaviour = lambda n, m: _ok(m)  # noqa: E731
    bad: Behaviour = lambda n, m: _bad(m)  # noqa: E731
    return (
        Scenario(
            "S1",
            "healthy first provider",
            ("evala", "evalb"),
            {"evala": good, "evalb": good},
            MODE_LLM,
            None,
            {"evala": 4, "evalb": 0},
        ),
        Scenario(
            "S2",
            "first provider answers 429, second works (cooldown skips the first afterwards)",
            ("evala", "evalb"),
            {"evala": _fail("http_429", 429), "evalb": good},
            MODE_LLM,
            None,
            {"evala": 1, "evalb": 4},
        ),
        Scenario(
            "S3",
            "first 5xx, second times out, third works",
            ("evala", "evalb", "evalc"),
            {"evala": _fail("http_5xx", 503), "evalb": _fail("timeout"), "evalc": good},
            MODE_LLM,
            None,
            {"evala": 1, "evalb": 1, "evalc": 4},
        ),
        Scenario(
            "S4",
            "first answer is rejected by the rules, second is faithful",
            ("evala", "evalb"),
            {"evala": bad, "evalb": good},
            MODE_LLM,
            None,
            {"evala": 4, "evalb": 4},
        ),
        Scenario(
            "S5",
            "every provider fails",
            ("evala", "evalb", "evalc"),
            {"evala": _fail("http_5xx", 503), "evalb": _fail("http_429", 429), "evalc": _fail("timeout")},
            MODE_RULE_BASED,
            llm.WARN_UNAVAILABLE,
            {"evala": 1, "evalb": 1, "evalc": 1},
        ),
        Scenario(
            "S6",
            "first provider answers 401 (disabled for the process), second works",
            ("evala", "evalb"),
            {"evala": _fail("http_4xx", 401), "evalb": good},
            MODE_LLM,
            None,
            {"evala": 1, "evalb": 4},
        ),
        Scenario(
            "S7",
            "time budget runs out before the second provider",
            ("evala", "evalb"),
            {"evala": _sleepy(0.4, "network"), "evalb": good},
            MODE_RULE_BASED,
            llm.WARN_UNAVAILABLE,
            {"evala": 1, "evalb": 0},
            questions=1,
            budget_s=0.5,
        ),
        Scenario(
            "S8",
            "two providers in a row reject their answer (third is never tried)",
            ("evala", "evalb", "evalc"),
            {"evala": bad, "evalb": bad, "evalc": good},
            MODE_RULE_BASED,
            llm.WARN_REJECTED,
            {"evala": 4, "evalb": 4, "evalc": 0},
        ),
    )


@dataclass
class ScenarioResult:
    key: str
    label: str
    runs: int
    succeeded: int
    raised: int
    calls: dict[str, int]
    expected_calls: dict[str, int]
    attempts: list[str]
    max_ms: float
    unknown_numbers_accepted: int = 0

    @property
    def calls_ok(self) -> bool:
        return self.calls == self.expected_calls


def _chain_env(s: Scenario) -> dict[str, str]:
    env = {"COPILOT_LLM_ENABLED": "true", "COPILOT_LLM_PROVIDERS": ",".join(s.chain)}
    for name in s.chain:
        prefix = f"COPILOT_LLM_{name.upper()}_"
        env |= {
            prefix + "BASE_URL": FAKE_URL,
            prefix + "MODEL": f"{FAKE_MODEL}-{name}",
            prefix + "API_KEY": FAKE_KEY,
            prefix + "TIMEOUT_S": "2",
        }
    if s.budget_s is not None:
        env["COPILOT_LLM_BUDGET_S"] = str(s.budget_s)
    return env


def run_failover(cited: Sequence[tuple[Question, E2E]]) -> list[ScenarioResult]:
    """Injected faults through the real environment-built chain, the real router and the real validator."""
    out: list[ScenarioResult] = []
    for s in _scenarios():
        calls = {name: 0 for name in s.chain}
        counters = {name: 0 for name in s.chain}

        def fake(settings: llm.LlmSettings, messages: list[dict[str, str]], _s: Scenario = s) -> tuple[str, str | None]:
            counters[settings.name] += 1
            calls[settings.name] += 1
            return _s.behaviours[settings.name](counters[settings.name], messages), "eval-req"

        env = {k: v for k, v in os.environ.items() if not k.startswith("COPILOT_LLM_")} | _chain_env(s)
        router.reset()
        limiter.reset()
        succeeded = raised = unknown = 0
        attempts: list[str] = []
        worst = 0.0
        subset = list(cited)[: s.questions]
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(llm, "_call_provider", fake):
            for q, e in subset:
                with captured_outcomes() as outcomes:
                    t0 = time.perf_counter()
                    try:
                        res = asyncio.run(llm.enhance(e.result, question=q.question))
                    except Exception:  # noqa: BLE001 - the contract says nothing may raise; count it
                        raised += 1
                        continue
                    worst = max(worst, (time.perf_counter() - t0) * 1000.0)
                attempts.append(",".join(outcomes))
                if s.expect_mode == MODE_LLM:
                    good = res.mode == MODE_LLM
                else:
                    good = (
                        res.mode == MODE_RULE_BASED
                        and s.expect_warning in res.warnings
                        and res.answer == e.result.answer
                    )
                succeeded += 1 if good else 0
                if res.mode == MODE_LLM and unknown_numbers(res.answer, res.evidence):
                    unknown += 1
        router.reset()
        limiter.reset()
        out.append(
            ScenarioResult(
                s.key, s.label, len(subset), succeeded, raised, calls, dict(s.expect_calls), attempts, worst, unknown
            )
        )
    return out


# ----------------------------------------------------------------------------- optional: real providers


@dataclass
class RealRun:
    chain: list[str]
    n: int
    accepted: int
    rejected: int
    unavailable: int
    reasons: dict[str, int]
    ms: list[float]
    unknown_numbers_accepted: int


def run_real(cited: Sequence[tuple[Question, E2E]], limit: int) -> RealRun:
    """Rephrase up to ``limit`` cited answers with whatever providers the environment configures. THE QUESTIONS AND THE
    RETRIEVED DOC PASSAGES ARE SENT TO THOSE PROVIDERS. Refuses to run when the feature is off or nothing is configured."""
    chain = llm.load_chain()
    usable = [s for s in chain if s.configured]
    if not usable:
        raise SuiteError(
            "no provider is configured: set COPILOT_LLM_ENABLED=true and the provider variables (see docs/copilot/LOCAL_LLM.md)"
        )
    names = [f"{s.name} ({s.model}{', local' if s.local else ''})" for s in usable]
    run = RealRun(names, 0, 0, 0, 0, {}, [], 0)
    for q, e in list(cited)[: max(1, limit)]:
        with captured_outcomes() as outcomes:
            t0 = time.perf_counter()
            out = asyncio.run(llm.enhance(e.result, question=q.question))
            run.ms.append((time.perf_counter() - t0) * 1000.0)
        run.n += 1
        verdict = _classify(out)
        setattr(run, verdict, getattr(run, verdict) + 1)
        if verdict == "accepted":
            run.unknown_numbers_accepted += 1 if unknown_numbers(out.answer, out.evidence) else 0
        else:
            word = next((o for o in outcomes if o != "ok"), "none")
            run.reasons[word] = run.reasons.get(word, 0) + 1
    return run


# ----------------------------------------------------------------------------- the whole evaluation


@dataclass
class Evaluation:
    suite: Suite
    date: str
    commit: str
    fingerprint: str
    chunks: int
    documents: int
    defaults: dict[str, float]
    rows: list[RetrievalRow]
    ranking: dict[str, Any]
    at_defaults: dict[str, Any]
    fitted: Fit
    fitted_score_only: Fit
    placeholder: dict[str, Any]
    loo: dict[str, Any]
    loo_score_only: dict[str, Any]
    sweep: list[dict[str, Any]]
    e2e: list[E2E]
    judged: list[Judged]
    rephrase: list[VariantResult]
    failover: list[ScenarioResult] | None
    real: RealRun | None
    drift: list[str]
    gates: list[dict[str, Any]]

    @property
    def gates_passed(self) -> bool:
        return all(g["passed"] for g in self.gates)


def git_commit(root: Path = ROOT) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=5
        )
        text = out.stdout.strip()
        if out.returncode == 0 and text:
            dirty = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=10
            ).stdout.strip()
            return text + (" (uncommitted changes)" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown (not a git checkout)"


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def _gates(
    suite: Suite,
    at_defaults: dict[str, Any],
    judged: list[Judged],
    rephrase: list[VariantResult],
    failover: list[ScenarioResult] | None,
    real: RealRun | None,
) -> list[dict[str, Any]]:
    g = suite.gates
    e2e_out = [j for j in judged if j.group == "out_of_corpus"]
    adv = [j for j in judged if j.group == "adversarial"]
    unknown = sum(v.unknown_numbers_accepted for v in rephrase)
    unknown += sum(s.unknown_numbers_accepted for s in failover or [])
    unknown += real.unknown_numbers_accepted if real else 0
    refusal = _rate(sum(1 for j in e2e_out if j.refused), len(e2e_out))
    adv_rate = _rate(sum(1 for j in adv if j.passed), len(adv))
    return [
        {
            "name": "hit@3 served (in-corpus, retrieval)",
            "value": at_defaults["hit_at_3_served"],
            "target": f">= {g['hit_at_3_served_min']:.2f}",
            "passed": at_defaults["hit_at_3_served"] >= g["hit_at_3_served_min"] - 1e-9,
        },
        {
            "name": "correct refusal (out-of-corpus, end to end)",
            "value": refusal,
            "target": f">= {g['correct_refusal_min']:.2f}",
            "passed": refusal >= g["correct_refusal_min"] - 1e-9,
        },
        {
            "name": "accepted answers with an unknown number",
            "value": unknown,
            "target": f"<= {int(g['unknown_numbers_accepted_max'])}",
            "passed": unknown <= g["unknown_numbers_accepted_max"],
        },
        {
            "name": "adversarial cases handled",
            "value": adv_rate,
            "target": f">= {g['adversarial_pass_min']:.2f}",
            "passed": adv_rate >= g["adversarial_pass_min"] - 1e-9,
        },
    ]


@contextmanager
def quiet_product_logs() -> Iterator[None]:
    """The product loggers are chatty at INFO; the harness output is the report. ``captured_outcomes`` re-enables ``llm``."""
    names = ("src.copilot.docs_answer", "src.copilot.router", "src.copilot.llm", "src.copilot.answer")
    old = {n: logging.getLogger(n).level for n in names}
    for n in names:
        logging.getLogger(n).setLevel(logging.ERROR)
    try:
        yield
    finally:
        for n, level in old.items():
            logging.getLogger(n).setLevel(level)


def evaluate(
    root: Path = ROOT,
    suite: Suite | None = None,
    *,
    index_path: Path | None = None,
    min_score: float | None = None,
    min_coverage: float | None = None,
    failover: bool = True,
    real_limit: int | None = None,
    targets: Targets | None = None,
) -> Evaluation:
    with quiet_product_logs():
        return _evaluate(root, suite, index_path, min_score, min_coverage, failover, real_limit, targets)


def _evaluate(root, suite, index_path, min_score, min_coverage, failover, real_limit, targets) -> Evaluation:
    suite = suite or load_suite()
    bad = validate_suite(suite)
    if bad:
        raise SuiteError("question file problems: " + "; ".join(bad))
    with tempfile.TemporaryDirectory(prefix="copilot_eval_") as tmp:
        path = index_path or Path(tmp) / "docs_index.sqlite"
        if index_path is None:
            try:
                built = rag_index.build_index(path, root)
            except rag_index.IndexUnavailable as exc:
                raise SuiteError(f"cannot build the docs index under {root}: {exc.reason}") from exc
            fingerprint, documents = built.fingerprint, built.documents
        else:
            fresh = rag_index.check_freshness(path, root)
            if not fresh.usable:
                raise SuiteError(
                    f"the index at {path} is {fresh.status} ({fresh.reason}); rebuild it with scripts/build_copilot_index.py"
                )
            fingerprint = rag_index.corpus_fingerprint(rag_index.load_index(path).doc_hashes)
            documents = len(rag_index.load_index(path).doc_hashes)
        index = rag_index.load_index(path)
        drift = check_checkout(suite, index, root)
        if drift:
            raise SuiteError("the checkout differs from what the question file assumes: " + "; ".join(drift))

        targets = targets or Targets(suite.gates["hit_at_3_served_min"], suite.gates["correct_refusal_min"])
        rows = collect_rows(index, suite.questions)
        s_used = rag_search.DEFAULT_MIN_SCORE if min_score is None else min_score
        c_used = (
            (rag_search.DEFAULT_MIN_COVERAGE if min_score is None else 0.0) if min_coverage is None else min_coverage
        )
        e2e = run_end_to_end(path, root, suite.questions, min_score=min_score, min_coverage=min_coverage)
        by_id = {q.id: q for q in suite.questions}
        judged = [judge(by_id[e.qid], e, index) for e in e2e]
        cited = [(by_id[e.qid], e) for e in e2e if e.group == "in_corpus" and e.citations]
        rephrase = run_rephrase(cited)
        fo = run_failover(cited) if failover else None
        real = run_real(cited, real_limit) if real_limit else None

        at_defaults = point_metrics(rows, s_used, c_used)
        sweep = [point_metrics(rows, s, c_used) for s in (0.0, 2.0, 4.0, 5.0, 6.0, 6.5, 7.0, 8.0, 9.0, 10.0)]
        evaluation = Evaluation(
            suite=suite,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            commit=git_commit(root),
            fingerprint=fingerprint,
            chunks=index.chunk_count,
            documents=documents,
            defaults={"min_score": s_used, "min_coverage": c_used},
            rows=rows,
            ranking=ranking_metrics(rows),
            at_defaults=at_defaults,
            fitted=fit(rows, targets),
            fitted_score_only=fit(rows, targets, coverage_grid=(0.0,)),
            placeholder=point_metrics(rows, 6.0, 0.0),
            loo=leave_one_out(rows, targets),
            loo_score_only=leave_one_out(rows, targets, coverage_grid=(0.0,)),
            sweep=sweep,
            e2e=e2e,
            judged=judged,
            rephrase=rephrase,
            failover=fo,
            real=real,
            drift=drift,
            gates=_gates(suite, at_defaults, judged, rephrase, fo, real),
        )
    return evaluation


# ----------------------------------------------------------------------------- report


def _pct(x: float) -> str:
    return f"{x:.3f}"


def _group_rate(ev: Evaluation, group: str, attr: str) -> tuple[int, int]:
    rows = [j for j in ev.judged if j.group == group]
    return sum(1 for j in rows if getattr(j, attr)), len(rows)


def render_report(ev: Evaluation) -> str:
    q = {x.id: x for x in ev.suite.questions}
    lines: list[str] = []
    w = lines.append
    chain = "no language model for the retrieval and end-to-end sections (rule-based); scripted fake providers `evala`, `evalb`, `evalc` (`eval-fake-model`) for the rephrase and failover sections"
    w("# Copilot evaluation report (CP-9)")
    w("")
    w(
        "*Generated by `python scripts/copilot_eval.py --write-report`. Do not edit by hand; this file is excluded from the Copilot's own corpus.*"
    )
    w("")
    w(f"- **Date:** {ev.date}")
    w(f"- **Commit:** {ev.commit}")
    w(f"- **Corpus:** {ev.documents} documents, {ev.chunks} chunks, fingerprint `{ev.fingerprint[:16]}`")
    w(
        f"- **Questions:** {len(ev.suite.questions)} (`tests/copilot_eval/questions.yaml`, version {ev.suite.version}): "
        + ", ".join(f"{len(ev.suite.of(g))} {g.replace('_', '-')}" for g in GROUPS)
    )
    w(f"- **Provider chain used:** {chain}.")
    w(f"- **Real providers:** {'RUN, see the section below' if ev.real else 'not run (offline evaluation)'}.")
    w(
        f"- **Retrieval floors in force:** score >= {ev.defaults['min_score']:g}, coverage >= {ev.defaults['min_coverage']:g}"
    )
    w("")
    w("## Gates")
    w("")
    w("| Gate | Value | Target | Verdict |")
    w("|---|---|---|---|")
    for g in ev.gates:
        value = g["value"] if isinstance(g["value"], int) else _pct(g["value"])
        w(f"| {g['name']} | {value} | {g['target']} | {'PASS' if g['passed'] else 'FAIL'} |")
    w("")
    hit_gate = ev.gates[0]
    w(
        f"CP-12 (hybrid embeddings) rule from the roadmap: unlocked only if the hit@3 gate fails after tuning. Here it "
        f"**{'passes' if hit_gate['passed'] else 'fails'}** in-sample, so CP-12 is **{'skipped' if hit_gate['passed'] else 'unlocked'}** by that rule. "
        f"Read the out-of-sample estimate below before relying on that: it is lower."
    )
    w("")
    routed = sum(1 for j in ev.judged if j.group == "in_corpus" and j.intent_ok)
    n_in = len(ev.suite.of("in_corpus"))
    w(
        f"**What a user gets is lower than the retrieval gate suggests.** Only {routed} of {n_in} in-corpus questions reach retrieval at all "
        "(the rest carry no docs cue and are routed to an older intent, by CP-7's design), so the end-to-end cited-answer rate is "
        f"{routed}/{n_in} = {_pct(_rate(routed, n_in))}. The retrieval gate measures the retriever, not that."
    )
    w("")
    w(
        "These are small-sample numbers. One in-corpus question is worth "
        f"{100 / max(1, len(ev.suite.of('in_corpus'))):.1f} points of hit@3 and one out-of-corpus question is worth "
        f"{100 / max(1, len(ev.suite.of('out_of_corpus'))):.0f} points of refusal. The questions were written by the author of the system."
    )
    w("")

    # -- retrieval
    w("## Retrieval")
    w("")
    r = ev.ranking
    w(
        f"Ranking quality with no floors (does the right chunk come out on top?), {r['n']} in-corpus questions: "
        f"hit@1 **{_pct(r['hit_at_1'])}**, hit@3 **{_pct(r['hit_at_3'])}**, hit@5 {_pct(r['hit_at_5'])}, MRR {_pct(r['mrr'])}. "
        "Routing cues are ignored here; this is the retriever alone."
    )
    w("")
    w("What the product actually shows depends on two floors (score and coverage). Operating points, same questions:")
    w("")
    w(
        "| Operating point | Score floor | Coverage floor | hit@3 served | Correct refusal | Out-of-sample (leave-one-out) hit / refusal |"
    )
    w("|---|---|---|---|---|---|")
    p = ev.placeholder
    w(f"| CP-6 placeholder | 6.0 | none | {_pct(p['hit_at_3_served'])} | {_pct(p['correct_refusal'])} | not fitted |")
    fs = ev.fitted_score_only
    w(
        f"| Best score floor alone | {fs.min_score:g} | none | {_pct(fs.hit)} | {_pct(fs.refusal)} | {_pct(ev.loo_score_only['hit_at_3_served'])} / {_pct(ev.loo_score_only['correct_refusal'])} |"
    )
    f = ev.fitted
    w(
        f"| **Best score and coverage floors (fitted here)** | {f.min_score:g} | {f.min_coverage:g} | {_pct(f.hit)} | {_pct(f.refusal)} | {_pct(ev.loo['hit_at_3_served'])} / {_pct(ev.loo['correct_refusal'])} |"
    )
    d = ev.at_defaults
    w(
        f"| **Product defaults now** | {ev.defaults['min_score']:g} | {ev.defaults['min_coverage']:g} | {_pct(d['hit_at_3_served'])} | {_pct(d['correct_refusal'])} | n/a |"
    )
    w("")
    w(
        f"The fit picks the middle of the plateau of equally good points ({f.n_optimal} grid points tied). The in-sample figures are flattered "
        "because every question was visible when the floors were chosen; the leave-one-out column refits without each question and scores only "
        f"that question, which is the honest estimate. Questions wrong out-of-sample: {', '.join(ev.loo['wrong']) or 'none'}."
    )
    w("")
    w("Score floor sweep at the coverage floor in force:")
    w("")
    w("| Score floor | hit@3 served | Correct refusal |")
    w("|---|---|---|")
    for s in ev.sweep:
        w(f"| {s['min_score']:g} | {_pct(s['hit_at_3_served'])} | {_pct(s['correct_refusal'])} |")
    w("")
    misses = d["hit_misses"] + d["refusal_misses"]
    if misses:
        w("Retrieval misses at the product defaults:")
        w("")
        for qid in misses:
            row = next(x for x in ev.rows if x.qid == qid)
            kind = "not served" if row.group == "in_corpus" else "answered when it should refuse"
            top = served(row, ev.defaults["min_score"], ev.defaults["min_coverage"], 1)
            seen = f"; top served: {top[0].source_path} > {top[0].heading_path}" if top else ""
            rank = ev.ranking["ranks"].get(qid)
            rank_note = (
                f"; expected chunk ranks {rank} with no floors"
                if row.group == "in_corpus" and rank
                else ("; expected chunk not in the top 20" if row.group == "in_corpus" else "")
            )
            w(f'- **{qid}** ({kind}): "{q[qid].question}"{rank_note}{seen}')
        w("")
        w(
            'Reading the in-corpus misses: the question says "Copilot" where the document says "assistant", and "not model" '
            'against the heading "Not modelled", which plain keyword matching cannot bridge; a near-miss (expected chunk at rank 4) is a '
            "ranking problem instead. Embeddings (CP-12) could help with the first kind. That is a hypothesis, not a measurement."
        )
        w("")

    # -- end to end
    w("## End to end (real `answer_question`, rule-based)")
    w("")
    i_ok, i_n = _group_rate(ev, "in_corpus", "intent_ok")
    c_ok, _ = _group_rate(ev, "in_corpus", "cited")
    rel_ok, _ = _group_rate(ev, "in_corpus", "relevant")
    o_ref, o_n = _group_rate(ev, "out_of_corpus", "refused")
    o_nc, _ = _group_rate(ev, "out_of_corpus", "no_citation")
    x_ok, x_n = _group_rate(ev, "other_intent", "passed")
    a_ok, a_n = _group_rate(ev, "adversarial", "passed")
    all_intent = [j for j in ev.judged if j.intent_ok is not None]
    integrity_bad = sum(1 for j in ev.judged if j.integrity)
    cited_total = sum(len(e.citations) for e in ev.e2e)
    w("| Measure | Result |")
    w("|---|---|")
    w(
        f"| Intent accuracy, all questions with an expected intent | {sum(1 for j in all_intent if j.intent_ok)}/{len(all_intent)} = {_pct(_rate(sum(1 for j in all_intent if j.intent_ok), len(all_intent)))} |"
    )
    w(f"| In-corpus routed to `docs_question` | {i_ok}/{i_n} |")
    w(f"| In-corpus answered with at least one citation | {c_ok}/{i_n} |")
    w(f"| In-corpus citing an expected source (citation relevance) | {rel_ok}/{i_n} |")
    w(
        f"| Citation structural correctness (every citation resolves to a real, allowed chunk and quotes only its text) | {'all' if integrity_bad == 0 else f'{integrity_bad} answers with problems'} ({cited_total} citations) |"
    )
    w(f"| Out-of-corpus: no citation | {o_nc}/{o_n} |")
    w(f"| Out-of-corpus: correct refusal (no citation and an explicit refusal) | {o_ref}/{o_n} |")
    w(f"| Non-docs questions keep their intent and cite nothing | {x_ok}/{x_n} |")
    w(f"| Adversarial cases handled | {a_ok}/{a_n} |")
    w("")
    fails = [j for j in ev.judged if not j.passed]
    if fails:
        w("Questions that did not pass end to end:")
        w("")
        for j in fails:
            w(
                f'- **{j.qid}** ({j.group.replace("_", "-")}): "{q[j.qid].question}" — {"; ".join(j.notes) or "see integrity notes"}'
                + (f" [{'; '.join(j.integrity)}]" if j.integrity else "")
            )
        w("")
    unrouted = [j for j in ev.judged if j.group == "in_corpus" and j.intent_ok is False]
    if unrouted:
        w(
            "A routing miss is a different failure from a retrieval miss: the question never reached retrieval because it has no docs cue "
            '("runbook", "documentation", "how do I ..."). CP-7 chose that on purpose so that live-state questions are never answered from documents.'
        )
        w("")

    # -- rephrase
    w("## Rephrase rules with scripted fake providers")
    w("")
    n_cited = ev.rephrase[0].n if ev.rephrase else 0
    w(
        f"Each variant is a scripted model reply, run through the real `llm.enhance` and `llm.validate` for each of the {n_cited} cited in-corpus answers. "
        "This shows what the rules catch of what I scripted; it does not show how a real model behaves."
    )
    w("")
    w("| Variant | Kind | n | Accepted | Rejected | Unavailable | Why rejected |")
    w("|---|---|---|---|---|---|---|")
    for v in ev.rephrase:
        reasons = ", ".join(f"{k} ×{n}" for k, n in sorted(v.reasons.items())) or "-"
        w(
            f"| {v.key} {v.label} | {v.kind.replace('_', ' ')} | {v.n} | {v.accepted} | {v.rejected} | {v.unavailable} | {reasons} |"
        )
    w("")
    faithful = [v for v in ev.rephrase if v.kind == "faithful"]
    unfaithful = [v for v in ev.rephrase if v.kind == "unfaithful"]
    hole = [v for v in ev.rephrase if v.kind == "known_hole"]
    f_n = sum(v.n for v in faithful)
    u_n = sum(v.n for v in unfaithful)
    w(
        f"- Faithful replies rejected: {sum(v.rejected for v in faithful)}/{f_n} (this is the false-rejection rate; F2 shows the cost of tolerance 0 for one extra connecting word)."
    )
    w(f"- Unfaithful replies rejected: {sum(v.rejected for v in unfaithful)}/{u_n}.")
    w(
        f"- **Known hole:** a reply that reverses a passage's meaning using only the passage's own words was accepted "
        f"{sum(v.accepted for v in hole)}/{sum(v.n for v in hole)} times. `ungrounded_text` is a lexical guard, not a faithfulness check."
    )
    w(
        "- `DOCS_UNGROUNDED_MAX` stays at 0. Raising it would let F2-style wording through, but the only evidence available here is my own scripted replies, "
        "which cannot say how many extra words a real model needs. Decide it from a real-provider run."
    )
    w("")

    # -- failover
    w("## Failover under injected faults (fake providers)")
    w("")
    if ev.failover is None:
        w("Skipped (`--no-failover`).")
    else:
        w("| Scenario | Runs | As intended | Raised | Provider calls (actual / expected) |")
        w("|---|---|---|---|---|")
        for s in ev.failover:
            calls = ", ".join(f"{k} {s.calls[k]}/{s.expected_calls[k]}" for k in s.calls)
            w(
                f"| {s.key} {s.label} | {s.runs} | {s.succeeded}/{s.runs} | {s.raised} | {calls}{'' if s.calls_ok else ' **MISMATCH**'} |"
            )
        total = sum(s.runs for s in ev.failover)
        good = sum(s.succeeded for s in ev.failover)
        w("")
        w(
            f"Failover success: {good}/{total} runs gave the intended outcome ({_pct(_rate(good, total))}); "
            f'{sum(s.raised for s in ev.failover)} raised to the caller. "As intended" means a model answer when some provider can answer, '
            "and the unchanged rule-based answer plus the right warning when none can. The call counts prove the cooldown (S2), the auth disable (S6), "
            "the rejection allowance (S8) and the time budget (S7)."
        )
    w("")

    # -- real
    if ev.real:
        rr = ev.real
        w("## REAL PROVIDER RUN (not part of the offline evaluation)")
        w("")
        w(
            "**The question text and the retrieved documentation passages were sent to these providers.** Numbers below describe those providers on this day only."
        )
        w("")
        w(f"- Chain: {', '.join(rr.chain)}")
        w(
            f"- Answers tried: {rr.n}; accepted {rr.accepted}; rejected by the rules {rr.rejected}; provider unavailable {rr.unavailable}"
        )
        decided = rr.accepted + rr.rejected
        w(f"- Rejection rate among answered requests: {rr.rejected}/{decided} = {_pct(_rate(rr.rejected, decided))}")
        w(f"- Reasons: {', '.join(f'{k} ×{n}' for k, n in sorted(rr.reasons.items())) or '-'}")
        w(
            f"- Latency p50 {percentile(rr.ms, 50):.0f} ms, p95 {percentile(rr.ms, 95):.0f} ms (network and model included)"
        )
        w(f"- Accepted answers containing an unknown number: {rr.unknown_numbers_accepted}")
        w("")

    # -- latency
    w("## Latency (this machine, this run)")
    w("")
    all_ms = [e.ms for e in ev.e2e]
    docs_ms = [e.ms for e in ev.e2e if e.group == "in_corpus"]
    w("| Path | n | p50 | p95 |")
    w("|---|---|---|---|")
    w(
        f"| `answer_question`, all questions, rule-based | {len(all_ms)} | {percentile(all_ms, 50):.1f} ms | {percentile(all_ms, 95):.1f} ms |"
    )
    w(
        f"| `answer_question`, in-corpus (retrieval + citations) | {len(docs_ms)} | {percentile(docs_ms, 50):.1f} ms | {percentile(docs_ms, 95):.1f} ms |"
    )
    if ev.failover:
        s1 = next((s for s in ev.failover if s.key == "S1"), None)
        if s1:
            w(
                f"| `llm.enhance` with an instant fake provider, worst of {s1.runs} | {s1.runs} | - | {s1.max_ms:.1f} ms |"
            )
    w("")
    w(
        "These time our own code only (index lookup, answer building, validation, router bookkeeping) with the index already loaded. They say nothing about a real provider's latency. "
        "Single run on one machine: treat them as an order of magnitude."
    )
    w("")

    # -- limits
    w("## What this evaluation does not show")
    w("")
    w(
        f"- **Small, author-written set.** {len(ev.suite.of('in_corpus'))} answerable and {len(ev.suite.of('out_of_corpus'))} unanswerable questions, written by the person who built the retriever. Confidence intervals would be wide; none are computed."
    )
    w(
        "- **The floors were fitted on the same questions they are scored on.** The leave-one-out column is the out-of-sample estimate; it is lower, and the working band for the coverage floor is narrow."
    )
    w(
        "- **No real model is in the offline numbers.** Fake replies were written to exercise the rules. A real model may be rejected more or less often."
    )
    w(
        "- **Citation correctness is structural** (the citation resolves to a real allowed chunk and the quoted words come from it). It does not prove the quoted passage answers the question; citation relevance above does that, only for the questions that have an expected source."
    )
    w("- **Latency is not a benchmark.** One machine, one run, no load.")
    w(
        "- **The corpus is small and mostly written by one author.** A change to the documents can move these numbers; re-run after editing them."
    )
    w("")
    w("## Reproduce (Windows PowerShell, repo root)")
    w("")
    w("```powershell")
    w("python scripts/copilot_eval.py                       # offline, prints a summary, exit code 1 if a gate fails")
    w("python scripts/copilot_eval.py --write-report        # also rewrites this file")
    w(
        "python scripts/copilot_eval.py --real --real-limit 10  # OPTIONAL: sends questions and doc passages to the configured providers"
    )
    w("pytest tests/copilot_eval")
    w("```")
    w("")
    return "\n".join(lines)


def summary(ev: Evaluation) -> str:
    out = [
        f"Copilot evaluation {ev.date}  commit {ev.commit}  corpus {ev.documents} docs / {ev.chunks} chunks ({ev.fingerprint[:12]})"
    ]
    out.append(f"floors in force: score >= {ev.defaults['min_score']:g}, coverage >= {ev.defaults['min_coverage']:g}")
    r = ev.ranking
    out.append(f"ranking (no floors): hit@1 {_pct(r['hit_at_1'])}  hit@3 {_pct(r['hit_at_3'])}  MRR {_pct(r['mrr'])}")
    f = ev.fitted
    out.append(
        f"fitted floors: score {f.min_score:g}, coverage {f.min_coverage:g} -> hit@3 {_pct(f.hit)}, refusal {_pct(f.refusal)}"
        f"   leave-one-out: hit@3 {_pct(ev.loo['hit_at_3_served'])}, refusal {_pct(ev.loo['correct_refusal'])}"
    )
    for g in ev.gates:
        value = g["value"] if isinstance(g["value"], int) else _pct(g["value"])
        out.append(f"  [{'PASS' if g['passed'] else 'FAIL'}] {g['name']}: {value} (target {g['target']})")
    return "\n".join(out)


# ----------------------------------------------------------------------------- command line


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Evaluate the Copilot docs RAG on the golden questions (offline by default)."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="use this index file instead of building a temporary one (must be fresh)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="override the score floor (also resets the coverage floor to 0 unless --min-coverage is given)",
    )
    parser.add_argument("--min-coverage", type=float, default=None, help="override the coverage floor")
    parser.add_argument("--no-failover", action="store_true", help="skip the injected-fault scenarios")
    parser.add_argument("--write-report", action="store_true", help=f"write {REPORT_RELATIVE}")
    parser.add_argument("--json", type=Path, default=None, help="also write the raw numbers as JSON")
    parser.add_argument("--no-fail", action="store_true", help="exit 0 even when a gate fails")
    parser.add_argument(
        "--real",
        action="store_true",
        help="ALSO run against the configured real providers (sends questions and doc passages to them)",
    )
    parser.add_argument("--real-limit", type=int, default=10, help="how many answers to send with --real (default 10)")
    args = parser.parse_args(argv)
    try:
        ev = evaluate(
            args.root,
            index_path=args.index,
            min_score=args.min_score,
            min_coverage=args.min_coverage,
            failover=not args.no_failover,
            real_limit=args.real_limit if args.real else None,
        )
    except SuiteError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(summary(ev))
    if args.write_report:
        target = args.root / REPORT_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_report(ev), encoding="utf-8", newline="\n")
        print(f"wrote {target}")
    if args.json:
        args.json.write_text(json.dumps(to_jsonable(ev), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0 if (ev.gates_passed or args.no_fail) else 1


def to_jsonable(ev: Evaluation) -> dict[str, Any]:
    return {
        "date": ev.date,
        "commit": ev.commit,
        "fingerprint": ev.fingerprint,
        "chunks": ev.chunks,
        "defaults": ev.defaults,
        "ranking": {k: v for k, v in ev.ranking.items()},
        "at_defaults": ev.at_defaults,
        "fitted": ev.fitted.__dict__,
        "fitted_score_only": ev.fitted_score_only.__dict__,
        "placeholder": ev.placeholder,
        "loo": ev.loo,
        "loo_score_only": ev.loo_score_only,
        "sweep": ev.sweep,
        "gates": ev.gates,
        "judged": [j.__dict__ for j in ev.judged],
        "rephrase": [v.__dict__ for v in ev.rephrase],
        "failover": [s.__dict__ | {"attempts": s.attempts} for s in (ev.failover or [])],
        "real": ev.real.__dict__ if ev.real else None,
        "latency_ms": {e.qid: round(e.ms, 2) for e in ev.e2e},
    }


__all__ = ["Evaluation", "evaluate", "main", "render_report"]
