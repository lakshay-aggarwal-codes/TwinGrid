"""CP-5: cut one Markdown document into stable, citable chunks.

Rules (all deterministic, no randomness, no clock, no locale):

* A chunk never crosses a heading. ``heading_path`` is the chain of headings above it, joined by `` > ``.
  Text before the first heading has the heading path ``(preamble)``.
* ``#`` lines inside fenced code blocks are code, not headings.
* A section longer than ``max_chars`` is split on blank lines (fenced blocks and tables stay whole when they fit),
  then on lines, then on whitespace, then hard. Every chunk, overlap included, is at most ``max_chars`` characters.
* When a section is split, each following chunk starts with up to ``overlap`` characters from the end of the
  previous one, cut on a word boundary.
* ``chunk_id`` depends only on ``source_path``, ``heading_path``, which repeat of that heading it is, and the part
  number inside the section. It does not depend on the text, so a citation survives a rebuild and survives an edit
  that does not move headings. ``text_hash`` changes when the text changes; ``doc_hash`` when the document does.
* Text is normalised first (BOM removed, CRLF and CR become LF, control characters dropped), so a Windows checkout
  and a Linux checkout give identical ids and hashes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP = 120
MIN_MAX_CHARS = 200
PREAMBLE = "(preamble)"
HEADING_SEP = " > "
_JOIN = "\n\n"
_JOIN_COST = len(_JOIN)

_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class Chunk:
    """One citable piece of one document."""

    chunk_id: str
    source_path: str
    heading_path: str
    doc_hash: str
    ordinal: int
    text: str
    text_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_text(raw: str) -> str:
    """BOM off, line endings to LF, control characters (except newline and tab) dropped."""
    text = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_hash_of(text: str) -> str:
    """Hash of the *normalised* text, the value stored on every chunk of a document."""
    return sha256_hex(normalize_text(text))


def _chunk_id(source_path: str, heading_path: str, occurrence: int, part: int) -> str:
    return sha256_hex("\x1f".join((source_path, heading_path, str(occurrence), str(part))))[:16]


def _split_sections(text: str) -> list[tuple[str, int, str]]:
    """Return ``(heading_path, occurrence, body)`` for each section that has a non-blank body, in document order."""
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    sections: list[tuple[str, int, list[str]]] = []
    current_path, current_occ, current_lines = PREAMBLE, 0, []
    seen[PREAMBLE] = 1
    fence: tuple[str, int] | None = None

    for line in text.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and not line.strip().strip(marker[0]):
                fence = None
        heading = None if fence is not None or fence_match else _HEADING_RE.match(line)
        if heading is None:
            current_lines.append(line)
            continue
        sections.append((current_path, current_occ, current_lines))
        level = len(heading.group(1))
        title = " ".join(heading.group(2).split())
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_path = HEADING_SEP.join(t for _, t in stack)
        current_occ = seen.get(current_path, 0)
        seen[current_path] = current_occ + 1
        current_lines = []
    sections.append((current_path, current_occ, current_lines))

    out: list[tuple[str, int, str]] = []
    for path, occ, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            out.append((path, occ, body))
    return out


def _blocks(body: str) -> list[str]:
    """Split a section body on blank lines, keeping a fenced block in one piece."""
    blocks: list[str] = []
    cur: list[str] = []
    fence: tuple[str, int] | None = None
    for line in body.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and not line.strip().strip(marker[0]):
                fence = None
        if fence is None and not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def _cut_line(line: str, limit: int) -> list[str]:
    """Cut one over-long line into pieces of at most ``limit`` characters, on whitespace when possible."""
    pieces: list[str] = []
    rest = line
    while len(rest) > limit:
        window = rest[:limit]
        cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        piece = window[:cut].rstrip()
        pieces.append(piece if piece else window)
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def _fit_block(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]
    pieces: list[str] = []
    cur = ""
    for line in block.split("\n"):
        for seg in _cut_line(line, limit):
            if cur and len(cur) + 1 + len(seg) > limit:
                pieces.append(cur)
                cur = seg
            else:
                cur = f"{cur}\n{seg}" if cur else seg
    if cur:
        pieces.append(cur)
    return pieces


def _tail(text: str, overlap: int) -> str:
    """The last ``overlap`` characters of ``text``, starting on a word boundary (empty when ``overlap`` is 0)."""
    if overlap <= 0:
        return ""
    if len(text) <= overlap:
        return text.strip()
    tail = text[-overlap:]
    for i, ch in enumerate(tail):
        if ch.isspace():
            tail = tail[i + 1 :]
            break
    return tail.strip()


def _pack(body: str, max_chars: int, overlap: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    unit_limit = max_chars - overlap - _JOIN_COST
    units = [piece for block in _blocks(body) for piece in _fit_block(block, unit_limit)]
    chunks: list[str] = []
    prefix = ""
    cur = ""
    for unit in units:
        room = max_chars - ((len(prefix) + _JOIN_COST) if prefix else 0)
        if cur and len(cur) + _JOIN_COST + len(unit) > room:
            chunks.append(f"{prefix}{_JOIN}{cur}" if prefix else cur)
            prefix = _tail(cur, overlap)
            cur = unit
        else:
            cur = f"{cur}{_JOIN}{unit}" if cur else unit
    if cur:
        chunks.append(f"{prefix}{_JOIN}{cur}" if prefix else cur)
    return chunks


def chunk_markdown(
    text: str,
    source_path: str,
    doc_hash: str | None = None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Chunk one document. ``source_path`` is the repo-relative POSIX path; it is part of every chunk id."""
    if not source_path or "\\" in source_path or source_path.startswith("/"):
        raise ValueError("source_path must be a relative POSIX path")
    if max_chars < MIN_MAX_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_MAX_CHARS}")
    if overlap < 0 or overlap > max_chars // 4:
        raise ValueError("overlap must be between 0 and max_chars // 4")

    normalised = normalize_text(text)
    digest = doc_hash if doc_hash is not None else sha256_hex(normalised)
    chunks: list[Chunk] = []
    for heading_path, occurrence, body in _split_sections(normalised):
        for part, piece in enumerate(_pack(body, max_chars, overlap)):
            chunks.append(
                Chunk(
                    chunk_id=_chunk_id(source_path, heading_path, occurrence, part),
                    source_path=source_path,
                    heading_path=heading_path,
                    doc_hash=digest,
                    ordinal=len(chunks),
                    text=piece,
                    text_hash=sha256_hex(piece)[:16],
                )
            )
    return chunks
