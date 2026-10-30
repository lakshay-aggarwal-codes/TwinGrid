"""CP-6: one tokenizer for documents and queries, so both sides always agree.

Deterministic and dependency-free: Unicode decomposed and accents dropped, lower-cased, split into ``[a-z0-9]+``
tokens, one-letter tokens and a small stop-word list removed, then a deliberately crude stemmer applied. The stemmer
is not linguistically correct (``rotate`` and ``rotating`` both become ``rotat``); it only has to map related forms
to the same string on both sides. Any change here must bump ``TOKENIZER_VERSION``, which makes old indexes
``incompatible`` instead of silently wrong.

A query is normalised and length-capped *before* it is tokenised, and only ``[a-z0-9]+`` terms ever leave this
module, so no raw query text can reach SQL or anything else downstream.
"""

from __future__ import annotations

import re
import unicodedata

TOKENIZER_VERSION = 1
MAX_QUERY_CHARS = 300
MAX_QUERY_TERMS = 32

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

STOPWORDS = frozenset(
    """a an the of to in on at by for from with without and or but if then else so as is are was were be been being
    it its this that these those there here i me my we our you your he she they them their what which who whom how
    why when where do does did done can could should would will shall may might must have has had not no yes also
    about into than too very just any some all each more most such only own same please tell show give""".split()
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def normalize_query(query: object) -> str:
    """A bounded, control-free, single-spaced version of the query. Anything that is not text becomes ``""``."""
    if not isinstance(query, str):
        return ""
    cleaned = _CONTROL_RE.sub(" ", _fold(query))
    return " ".join(cleaned.split())[:MAX_QUERY_CHARS].strip()


def stem(token: str) -> str:
    """Crude suffix stripping. Tokens containing a digit (``v2``, ``p95``, ``2026``) are left alone."""
    if len(token) <= 3 or any(ch.isdigit() for ch in token):
        return token
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("sses"):
        token = token[:-2]
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    if token.endswith("e") and len(token) > 4:
        token = token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Index terms of ``text`` in order, repeats kept (term frequency needs them)."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(_fold(text)):
        if len(raw) < 2 or raw in STOPWORDS:
            continue
        out.append(stem(raw))
    return out


def query_terms(query: object) -> list[str]:
    """Distinct search terms of a query, in first-seen order, at most ``MAX_QUERY_TERMS``."""
    seen: dict[str, None] = {}
    for term in tokenize(normalize_query(query)):
        seen.setdefault(term)
        if len(seen) >= MAX_QUERY_TERMS:
            break
    return list(seen)
