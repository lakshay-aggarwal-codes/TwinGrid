"""Deterministic, content-sensitive fingerprint of the evaluation SOURCE.

Why: ``src/repro/env.py::code_state`` digests tracked changes only; the CONTENT of untracked files is not in its
dirty-tree digest, so editing an untracked evaluation file can leave a manifest's hash unchanged. This fingerprint
reads the filesystem directly (git is not involved), so tracked and untracked files are treated identically.

Covered (paths relative to the repository root, POSIX separators):
  * research/danish_aau/evaluation/**/*.py      evaluation source
  * research/danish_aau/config/*.toml           evaluation configuration
  * research/danish_aau/run_evaluation.py       entry point
  * research/danish_aau/docs/EVALUATION_*.md    evaluation documentation
  * src/repro/canonical.py, src/repro/env.py    the reused TwinGrid helpers (read-only dependencies)

Excluded: generated outputs, caches, VCS data and anything under the raw dataset folder. Bytecode (``*.pyc``) is never
matched because only ``*.py`` / ``*.toml`` / ``EVALUATION_*.md`` patterns are collected; ``EXCLUDED_PARTS`` additionally
keeps out a matching-named file that sits inside an excluded directory. Tests are not part of the source
being fingerprinted.

Line endings are normalised (CRLF/CR -> LF) and a UTF-8 BOM is dropped, so a Windows checkout with
``core.autocrlf`` fingerprints the same as a Linux one. The fingerprint covers each file's relative path AND content.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import _reuse

SCHEME = "aau-eval-source/1"

GLOB_PATTERNS: tuple[str, ...] = (
    "research/danish_aau/evaluation/**/*.py",
    "research/danish_aau/config/*.toml",
    "research/danish_aau/docs/EVALUATION_*.md",
)
REQUIRED_FILES: tuple[str, ...] = (
    "research/danish_aau/run_evaluation.py",
    "src/repro/canonical.py",
    "src/repro/env.py",
)
EXCLUDED_PARTS = frozenset({"__pycache__", "outputs", ".pytest_cache", ".git", "realData"})


class FingerprintError(RuntimeError):
    """A required source file is missing, so a trustworthy fingerprint cannot be produced."""


def _normalise(data: bytes) -> bytes:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _excluded(rel: Path) -> bool:
    return bool(EXCLUDED_PARTS & set(rel.parts))


def list_source_files(repo_root: Path) -> list[str]:
    """Sorted relative POSIX paths of every covered file that exists. Raises FingerprintError if a required one is absent."""
    root = Path(repo_root)
    found: set[str] = set()
    for pattern in GLOB_PATTERNS:
        for p in root.glob(pattern):
            rel = p.relative_to(root)
            if p.is_file() and not _excluded(rel):
                found.add(rel.as_posix())
    missing = [r for r in REQUIRED_FILES if not (root / r).is_file()]
    if missing:
        raise FingerprintError(f"required source file(s) missing: {', '.join(missing)}")
    found.update(REQUIRED_FILES)
    return sorted(found)


def hash_source_files(repo_root: Path) -> list[dict[str, str]]:
    root = Path(repo_root)
    return [
        {"path": rel, "sha256": hashlib.sha256(_normalise((root / rel).read_bytes())).hexdigest()}
        for rel in list_source_files(root)
    ]


def fingerprint_of(files: list[dict[str, str]]) -> str:
    """SHA-256 over canonical JSON of the (path, content-hash) list, in sorted path order."""
    ordered = sorted(({"path": f["path"], "sha256": f["sha256"]} for f in files), key=lambda f: f["path"])
    return str(_reuse.canonical().sha256_json({"scheme": SCHEME, "files": ordered}))


def compute(repo_root: Path) -> dict[str, Any]:
    files = hash_source_files(repo_root)
    return {"scheme": SCHEME, "sha256": fingerprint_of(files), "files": files}


def diff_files(stored: list[dict[str, str]], current: list[dict[str, str]]) -> dict[str, list[str]]:
    a = {f["path"]: f["sha256"] for f in stored}
    b = {f["path"]: f["sha256"] for f in current}
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "modified": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
    }
