"""Hash helpers. Text sources are LF-normalised so the value is the same on Windows and Linux checkouts."""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: Path, *, chunk: int = 1 << 22) -> tuple[str, int]:
    """(SHA-256 hex, size in bytes) of a file, streamed."""
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def lf_file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r", b"")).hexdigest()


def package_sha256(directory: Path) -> str:
    """Same recipe as ``cleaning.l1.code_sha256``: *.py of one directory, sorted by name, LF-normalised."""
    h = hashlib.sha256()
    for p in sorted(Path(directory).glob("*.py")):
        h.update(p.name.encode() + b"\x00" + p.read_bytes().replace(b"\r\n", b"\n") + b"\x00")
    return h.hexdigest()


def tree_sha256(items: dict[str, str]) -> str:
    return hashlib.sha256("\n".join(f"{k}\t{items[k]}" for k in sorted(items)).encode()).hexdigest()
