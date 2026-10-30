"""CP-5: the allow-list of documents the Copilot may retrieve from, and a loader that enforces it.

Default is *closed*: a file is in the corpus only if it is a Markdown file named by ``ALLOWED_FILES`` or sits under
one of ``ALLOWED_DIRS``. Two exclusion tiers sit on top:

* **Always excluded** (cannot be lifted): any path part starting with ``.env``; any directory named ``secrets``,
  ``secret``, ``data``, ``logs``, ``log``, ``.git``, ``node_modules`` or ``__pycache__``.
* **Excluded unless explicitly allowed**: any directory named ``security``. A caller must pass the file or folder in
  ``extra_allow`` to include it.

Symlinks are never followed and files over ``MAX_DOC_BYTES`` are skipped (reported, not silently dropped). Retrieved
text is data: this module never interprets it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP, Chunk, chunk_markdown, normalize_text, sha256_hex

ALLOWED_FILES: tuple[str, ...] = (
    "docs/CLAIMS.md",
    "docs/OPERATIONS.md",
    "docs/PHYSICS_V2.md",
    "docs/SENSITIVITY.md",
    "docs/SLO.md",
)
ALLOWED_DIRS: tuple[str, ...] = (
    "docs/model_cards",
    "docs/runbooks",
    "docs/copilot",
)
ALWAYS_EXCLUDED_DIRS = frozenset({"secrets", "secret", "data", "logs", "log", ".git", "node_modules", "__pycache__"})
EXPLICIT_ONLY_DIRS = frozenset({"security"})
MAX_DOC_BYTES = 512 * 1024
SUFFIX = ".md"


class CorpusError(ValueError):
    """A path or file the corpus refuses."""


@dataclass(frozen=True)
class SourceDoc:
    source_path: str
    text: str
    doc_hash: str
    size_bytes: int


@dataclass(frozen=True)
class Scan:
    paths: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class Corpus:
    documents: tuple[SourceDoc, ...]
    chunks: tuple[Chunk, ...]
    skipped: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]


def default_root() -> Path:
    """The repository root (this file is ``<root>/src/copilot/rag/corpus.py``)."""
    return Path(__file__).resolve().parents[3]


def normalize_rel(path: str) -> str:
    """A repo-relative POSIX path with no ``..``, no drive, no leading slash. Raises :class:`CorpusError` otherwise."""
    text = path.strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if not text or pure.is_absolute() or ".." in pure.parts or (len(text) > 1 and text[1] == ":"):
        raise CorpusError(f"not a safe repo-relative path: {path!r}")
    return pure.as_posix().rstrip("/")


def _extra(extra_allow: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(normalize_rel(entry) for entry in extra_allow)


def _covers(entry: str, rel: str) -> bool:
    return rel == entry or rel.startswith(entry + "/")


def exclusion_reason(rel: str, extra_allow: tuple[str, ...] = ()) -> str | None:
    """Why ``rel`` may never be retrieved from, or ``None``. ``extra_allow`` lifts only the ``security`` tier."""
    parts = rel.lower().split("/")
    if any(part.startswith(".env") for part in parts):
        return "environment file"
    for part in parts[:-1]:
        if part in ALWAYS_EXCLUDED_DIRS:
            return f"excluded directory '{part}'"
    for part in parts[:-1]:
        if part in EXPLICIT_ONLY_DIRS and not any(_covers(e, rel) for e in _extra(extra_allow)):
            return f"directory '{part}' needs an explicit allow"
    return None


def is_allowed(rel: str, extra_allow: tuple[str, ...] = ()) -> bool:
    """True when ``rel`` is Markdown, on the allow-list and not excluded."""
    try:
        rel = normalize_rel(rel)
        extra = _extra(extra_allow)
    except CorpusError:
        return False
    if not rel.lower().endswith(SUFFIX):
        return False
    listed = rel in ALLOWED_FILES or any(_covers(d, rel) for d in ALLOWED_DIRS) or any(_covers(e, rel) for e in extra)
    return listed and exclusion_reason(rel, extra_allow) is None


def _file_problem(root: Path, rel: str) -> str | None:
    path = root / rel
    if path.is_symlink():
        return "symbolic link"
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return "resolves outside the repository"
    if not resolved.is_file():
        return "not a regular file"
    if resolved.stat().st_size > MAX_DOC_BYTES:
        return f"larger than {MAX_DOC_BYTES} bytes"
    return None


def scan(root: Path | None = None, extra_allow: tuple[str, ...] = ()) -> Scan:
    """List what the corpus would read, what it refused (with a reason) and which listed files are absent."""
    root = Path(root) if root is not None else default_root()
    extra = _extra(extra_allow)
    candidates: set[str] = set()
    missing: list[str] = []
    for entry in (*ALLOWED_FILES, *ALLOWED_DIRS, *extra):
        target = root / entry
        if entry.lower().endswith(SUFFIX):
            if target.is_symlink() or target.is_file():
                candidates.add(entry)
            else:
                missing.append(entry)
        elif target.is_dir() and not target.is_symlink():
            candidates.update(p.relative_to(root).as_posix() for p in target.rglob(f"*{SUFFIX}"))
        else:
            missing.append(entry)

    paths: list[str] = []
    skipped: list[tuple[str, str]] = []
    for rel in sorted(candidates):
        reason = exclusion_reason(rel, extra)
        if reason is not None:
            skipped.append((rel, reason))
            continue
        problem = _file_problem(root, rel)
        if problem is not None:
            skipped.append((rel, problem))
            continue
        paths.append(rel)
    return Scan(tuple(paths), tuple(skipped), tuple(sorted(missing)))


def discover(root: Path | None = None, extra_allow: tuple[str, ...] = ()) -> list[str]:
    """Sorted repo-relative paths of every document the corpus will read."""
    return list(scan(root, extra_allow).paths)


def missing_allowed(root: Path | None = None, extra_allow: tuple[str, ...] = ()) -> list[str]:
    """Allow-list entries that do not exist in this checkout (repo drift)."""
    return list(scan(root, extra_allow).missing)


def load_document(root: Path | None, rel: str, extra_allow: tuple[str, ...] = ()) -> SourceDoc:
    """Read one allowed document. Raises :class:`CorpusError` for anything the corpus refuses."""
    root = Path(root) if root is not None else default_root()
    rel = normalize_rel(rel)
    if not is_allowed(rel, extra_allow):
        raise CorpusError(f"not in the Copilot corpus: {rel}")
    problem = _file_problem(root, rel)
    if problem is not None:
        raise CorpusError(f"{rel}: {problem}")
    raw = (root / rel).read_bytes()
    text = normalize_text(raw.decode("utf-8", errors="replace"))
    return SourceDoc(source_path=rel, text=text, doc_hash=sha256_hex(text), size_bytes=len(raw))


def build_corpus(
    root: Path | None = None,
    extra_allow: tuple[str, ...] = (),
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> Corpus:
    """Discover, load and chunk every allowed document. Chunk ids are unique across the corpus or this raises."""
    found = scan(root, extra_allow)
    documents = tuple(load_document(root, rel, extra_allow) for rel in found.paths)
    chunks: list[Chunk] = []
    for doc in documents:
        chunks.extend(chunk_markdown(doc.text, doc.source_path, doc.doc_hash, max_chars=max_chars, overlap=overlap))
    ids = [c.chunk_id for c in chunks]
    if len(ids) != len(set(ids)):
        raise CorpusError("duplicate chunk ids")
    return Corpus(documents, tuple(chunks), found.skipped, found.missing)
