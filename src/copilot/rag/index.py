"""CP-6: build and load the docs index (a SQLite file) and say whether it is stale.

The index is a *build artifact*: ``scripts/build_copilot_index.py`` writes it, it is never committed (``*.sqlite`` is
git-ignored; the default location is ``data/copilot/docs_index.sqlite``, overridable with
``COPILOT_DOCS_INDEX_PATH``). SQLite is only the storage format: :func:`load_index` reads the whole file into memory
once and closes it, and :mod:`.search` then works on plain Python structures. No query text ever reaches SQL.

Why not FTS5: the corpus is a few hundred chunks, and an own BM25 gives the same answer on every SQLite build, can
name the matched terms, needs no MATCH query syntax, and lets CP-9 retune field weights without rebuilding.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP, Chunk, sha256_hex
from .corpus import CorpusError, build_corpus, default_root, load_document, scan
from .tokenize import TOKENIZER_VERSION, tokenize

SCHEMA_VERSION = 1
ENV_INDEX_PATH = "COPILOT_DOCS_INDEX_PATH"
DEFAULT_RELATIVE_PATH = "data/copilot/docs_index.sqlite"

STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_MISSING = "missing"
STATUS_INCOMPATIBLE = "incompatible"

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE docs (source_path TEXT PRIMARY KEY, doc_hash TEXT NOT NULL);
CREATE TABLE chunks (
    idx INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL UNIQUE, source_path TEXT NOT NULL, heading_path TEXT NOT NULL,
    doc_hash TEXT NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL, text_hash TEXT NOT NULL,
    len_text INTEGER NOT NULL, len_head INTEGER NOT NULL, len_path INTEGER NOT NULL
);
CREATE TABLE postings (
    term TEXT NOT NULL, idx INTEGER NOT NULL, tf_text INTEGER NOT NULL, tf_head INTEGER NOT NULL,
    tf_path INTEGER NOT NULL, PRIMARY KEY (term, idx)
);
"""


class IndexUnavailable(Exception):
    """The index file is missing, unreadable, or built by an incompatible version. Callers fall back, never crash."""

    def __init__(self, status: str, reason: str) -> None:
        super().__init__(f"{status}: {reason}")
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class BuildResult:
    path: Path
    documents: int
    chunks: int
    terms: int
    fingerprint: str
    skipped: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class DocsIndex:
    """An immutable in-memory snapshot of an index file. Safe to share between threads."""

    chunks: tuple[Chunk, ...]
    postings: dict[str, tuple[tuple[int, int, int, int], ...]]
    lengths: tuple[tuple[int, int, int], ...]
    doc_hashes: dict[str, str]
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def vocabulary_size(self) -> int:
        return len(self.postings)

    @property
    def fingerprint(self) -> str:
        return self.meta.get("corpus_fingerprint", "")

    @property
    def extra_allow(self) -> tuple[str, ...]:
        return tuple(json.loads(self.meta.get("extra_allow", "[]")))


@dataclass(frozen=True)
class Freshness:
    status: str
    reason: str = ""
    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status == STATUS_FRESH


def default_index_path(environ: dict[str, str] | None = None) -> Path:
    """``COPILOT_DOCS_INDEX_PATH`` (relative paths are relative to the repo root) or the default location."""
    env = os.environ if environ is None else environ
    configured = str(env.get(ENV_INDEX_PATH, "")).strip()
    path = Path(configured) if configured else Path(DEFAULT_RELATIVE_PATH)
    return path if path.is_absolute() else default_root() / path


def corpus_fingerprint(doc_hashes: dict[str, str]) -> str:
    """One hash over every ``(source_path, doc_hash)`` pair, so any document change changes it."""
    return sha256_hex("\n".join(f"{p}\x1f{h}" for p, h in sorted(doc_hashes.items())))


def _field_tokens(chunk: Chunk) -> tuple[list[str], list[str], list[str]]:
    stem_path = chunk.source_path[:-3] if chunk.source_path.lower().endswith(".md") else chunk.source_path
    return tokenize(chunk.text), tokenize(chunk.heading_path), tokenize(stem_path)


def build_index(
    out_path: Path | str | None = None,
    root: Path | None = None,
    extra_allow: tuple[str, ...] = (),
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> BuildResult:
    """Build the index from the corpus into ``out_path`` (written to a temporary file, then moved into place)."""
    out = Path(out_path) if out_path is not None else default_index_path()
    built = build_corpus(root, extra_allow, max_chars=max_chars, overlap=overlap)
    if not built.chunks:
        raise IndexUnavailable(STATUS_MISSING, "the corpus is empty, nothing to index")
    doc_hashes = {d.source_path: d.doc_hash for d in built.documents}
    fingerprint = corpus_fingerprint(doc_hashes)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    tmp.unlink(missing_ok=True)
    terms: set[str] = set()
    con = sqlite3.connect(tmp)
    try:
        con.executescript(_SCHEMA)
        for idx, chunk in enumerate(built.chunks):
            text_t, head_t, path_t = _field_tokens(chunk)
            con.execute(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (idx, chunk.chunk_id, chunk.source_path, chunk.heading_path, chunk.doc_hash, chunk.ordinal,
                 chunk.text, chunk.text_hash, len(text_t), len(head_t), len(path_t)),
            )  # fmt: skip
            tf_text, tf_head, tf_path = Counter(text_t), Counter(head_t), Counter(path_t)
            for term in sorted(set(tf_text) | set(tf_head) | set(tf_path)):
                con.execute(
                    "INSERT INTO postings VALUES (?,?,?,?,?)", (term, idx, tf_text[term], tf_head[term], tf_path[term])
                )
                terms.add(term)
        con.executemany("INSERT INTO docs VALUES (?,?)", sorted(doc_hashes.items()))
        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "tokenizer_version": str(TOKENIZER_VERSION),
            "max_chars": str(max_chars),
            "overlap": str(overlap),
            "extra_allow": json.dumps(sorted(extra_allow)),
            "corpus_fingerprint": fingerprint,
            "doc_count": str(len(built.documents)),
            "chunk_count": str(len(built.chunks)),
        }
        con.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
        con.commit()
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(tmp, out)
    return BuildResult(
        out, len(built.documents), len(built.chunks), len(terms), fingerprint, built.skipped, built.missing
    )


def load_index(path: Path | str | None = None) -> DocsIndex:
    """Read an index file fully into memory. Raises :class:`IndexUnavailable` (never a raw SQLite error)."""
    target = Path(path) if path is not None else default_index_path()
    if not target.is_file():
        raise IndexUnavailable(STATUS_MISSING, f"no index file at {target.name}")
    uri = f"{target.resolve().as_uri()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise IndexUnavailable(STATUS_INCOMPATIBLE, f"cannot open index: {exc.__class__.__name__}") from exc
    try:
        meta = dict(con.execute("SELECT key, value FROM meta"))
        if meta.get("schema_version") != str(SCHEMA_VERSION):
            raise IndexUnavailable(
                STATUS_INCOMPATIBLE, f"index schema {meta.get('schema_version')!r}, need {SCHEMA_VERSION}"
            )
        if meta.get("tokenizer_version") != str(TOKENIZER_VERSION):
            raise IndexUnavailable(
                STATUS_INCOMPATIBLE, f"index tokenizer {meta.get('tokenizer_version')!r}, need {TOKENIZER_VERSION}"
            )
        rows = con.execute(
            "SELECT chunk_id, source_path, heading_path, doc_hash, ordinal, text, text_hash, len_text, len_head, len_path "
            "FROM chunks ORDER BY idx"
        ).fetchall()
        postings: dict[str, list[tuple[int, int, int, int]]] = {}
        for term, idx, tf_text, tf_head, tf_path in con.execute(
            "SELECT term, idx, tf_text, tf_head, tf_path FROM postings ORDER BY term, idx"
        ):
            postings.setdefault(term, []).append((idx, tf_text, tf_head, tf_path))
        doc_hashes = dict(con.execute("SELECT source_path, doc_hash FROM docs"))
    except sqlite3.Error as exc:
        raise IndexUnavailable(STATUS_INCOMPATIBLE, f"index is unreadable: {exc.__class__.__name__}") from exc
    finally:
        con.close()
    chunks = tuple(Chunk(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows)
    lengths = tuple((r[7], r[8], r[9]) for r in rows)
    if not chunks:
        raise IndexUnavailable(STATUS_INCOMPATIBLE, "index holds no chunks")
    return DocsIndex(chunks, {t: tuple(v) for t, v in postings.items()}, lengths, doc_hashes, meta)


def check_freshness(
    path: Path | str | None = None,
    root: Path | None = None,
    extra_allow: tuple[str, ...] | None = None,
) -> Freshness:
    """Compare the index with the documents on disk by ``doc_hash``. Reads files, so call it at startup or on demand."""
    try:
        index = load_index(path)
    except IndexUnavailable as exc:
        return Freshness(exc.status, exc.reason)
    return compare_with_disk(index, root, extra_allow)


def compare_with_disk(
    index: DocsIndex, root: Path | None = None, extra_allow: tuple[str, ...] | None = None
) -> Freshness:
    extra = index.extra_allow if extra_allow is None else extra_allow
    found = scan(root, extra)
    on_disk: dict[str, str] = {}
    for rel in found.paths:
        try:
            on_disk[rel] = load_document(root, rel, extra).doc_hash
        except CorpusError:
            continue
    changed = tuple(sorted(p for p, h in on_disk.items() if p in index.doc_hashes and index.doc_hashes[p] != h))
    added = tuple(sorted(set(on_disk) - set(index.doc_hashes)))
    removed = tuple(sorted(set(index.doc_hashes) - set(on_disk)))
    if changed or added or removed:
        parts = [f"{len(changed)} changed", f"{len(added)} added", f"{len(removed)} removed"]
        return Freshness(STATUS_STALE, ", ".join(parts), changed, added, removed)
    return Freshness(STATUS_FRESH)
