"""CP-6: BM25 search over a loaded :class:`~.index.DocsIndex`, with a score threshold and explainable hits.

Scoring is BM25 over three weighted fields of a chunk: its text (weight 1), its heading path (``HEADING_WEIGHT``) and
its file name (``PATH_WEIGHT``). Every hit names the query terms that matched. Hits scoring below ``min_score`` are
dropped, so an unrelated question returns nothing and the Copilot can say there is no documented answer.

``DEFAULT_MIN_SCORE`` is a PLACEHOLDER chosen from a handful of hand-checked questions (see ``docs/tasks/CP6_REPORT.md``);
on this small corpus no single score separates every in-corpus question from every unrelated one, and the placeholder
leans towards saying "not documented". CP-9 replaces it with a value fitted on the golden question set. Ordering is deterministic: score (rounded to six
places), then source path, then position in the document.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .chunker import Chunk
from .index import DocsIndex
from .tokenize import normalize_query, query_terms

DEFAULT_K = 5
MAX_K = 20
DEFAULT_MIN_SCORE = 6.0  # PLACEHOLDER until CP-9 fits it
BM25_K1 = 1.2
BM25_B = 0.75
HEADING_WEIGHT = 3.0
PATH_WEIGHT = 2.0

REASON_OK = "ok"
REASON_NO_TERMS = "no_query_terms"
REASON_NO_MATCH = "no_match"
REASON_BELOW_THRESHOLD = "below_threshold"


@dataclass(frozen=True)
class Hit:
    rank: int
    chunk: Chunk
    score: float
    matched_terms: tuple[str, ...]
    coverage: float = 0.0  # share of the query's idf mass this chunk matched (reported for CP-9, never used to gate)


@dataclass(frozen=True)
class SearchResult:
    query: str
    terms: tuple[str, ...]
    hits: tuple[Hit, ...]
    best_score: float
    min_score: float
    reason: str

    @property
    def found(self) -> bool:
        return bool(self.hits)


def search(
    index: DocsIndex,
    query: object,
    k: int = DEFAULT_K,
    *,
    min_score: float | None = None,
    heading_weight: float = HEADING_WEIGHT,
    path_weight: float = PATH_WEIGHT,
) -> SearchResult:
    """Return up to ``k`` chunks for ``query``. Never raises on odd input; a non-text or empty query finds nothing."""
    k = max(1, min(int(k), MAX_K))
    threshold = DEFAULT_MIN_SCORE if min_score is None else float(min_score)
    normalised = normalize_query(query)
    terms = tuple(query_terms(normalised))
    if not terms:
        return SearchResult(normalised, terms, (), 0.0, threshold, REASON_NO_TERMS)

    n = index.chunk_count
    weighted_len = [lt + heading_weight * lh + path_weight * lp for lt, lh, lp in index.lengths]
    avg_len = (sum(weighted_len) / n) or 1.0
    scores: dict[int, float] = {}
    matched: dict[int, list[str]] = {}
    idf_of: dict[str, float] = {}
    for term in terms:
        df = len(index.postings.get(term, ()))
        idf_of[term] = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
    idf_total = sum(idf_of.values()) or 1.0
    for term in terms:
        plist = index.postings.get(term)
        if not plist:
            continue
        idf = idf_of[term]
        for idx, tf_text, tf_head, tf_path in plist:
            tf = tf_text + heading_weight * tf_head + path_weight * tf_path
            norm = BM25_K1 * (1.0 - BM25_B + BM25_B * weighted_len[idx] / avg_len)
            scores[idx] = scores.get(idx, 0.0) + idf * (tf * (BM25_K1 + 1.0)) / (tf + norm)
            matched.setdefault(idx, []).append(term)
    if not scores:
        return SearchResult(normalised, terms, (), 0.0, threshold, REASON_NO_MATCH)

    ranked = sorted(
        scores,
        key=lambda i: (-round(scores[i], 6), index.chunks[i].source_path, index.chunks[i].ordinal),
    )
    best = round(scores[ranked[0]], 6)
    kept = [i for i in ranked if round(scores[i], 6) >= threshold][:k]
    hits = tuple(
        Hit(
            rank,
            index.chunks[i],
            round(scores[i], 6),
            tuple(matched[i]),
            round(sum(idf_of[t] for t in matched[i]) / idf_total, 4),
        )
        for rank, i in enumerate(kept, start=1)
    )
    return SearchResult(normalised, terms, hits, best, threshold, REASON_OK if hits else REASON_BELOW_THRESHOLD)
