"""Raw-data immutability.

The original Danish dataset must remain byte-for-byte unchanged. Two layers:

  1. ``open_raw_bytes`` is the ONLY way harness code reads a raw file: read-only, and refuses a path outside the
     raw directory (no ``..`` escapes).
  2. ``RawDataGuard`` fingerprints the raw directory (relative path, size, mtime_ns) before and after a run and
     raises ``RawDataModified`` if anything was added, removed or changed. It detects accidental writes; it is a
     tripwire, not a sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO


class RawDataModified(RuntimeError):
    """A file under the raw dataset directory was added, removed or modified during a run."""

    def __init__(self, diff: dict[str, list[str]]):
        self.diff = diff
        super().__init__(
            "raw dataset directory changed during the run: "
            + ", ".join(f"{k}={len(v)}" for k, v in diff.items() if v)
            + " (first: "
            + next((v[0] for v in diff.values() if v), "?")
            + ")"
        )


@dataclass(frozen=True)
class FileStamp:
    size: int
    mtime_ns: int


def snapshot(raw_dir: Path) -> dict[str, FileStamp]:
    """{posix relative path: FileStamp} for every file under ``raw_dir`` (empty if it does not exist)."""
    root = Path(raw_dir)
    if not root.is_dir():
        return {}
    out: dict[str, FileStamp] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(root).as_posix()] = FileStamp(st.st_size, st.st_mtime_ns)
    return out


def diff_snapshots(before: dict[str, FileStamp], after: dict[str, FileStamp]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
    }


class RawDataGuard:
    """Context manager: ``with RawDataGuard(raw_dir): ...`` raises RawDataModified on exit if anything changed."""

    def __init__(self, raw_dir: Path):
        self.raw_dir = Path(raw_dir)
        self.before: dict[str, FileStamp] = {}
        self.diff: dict[str, list[str]] = {"added": [], "removed": [], "modified": []}

    def __enter__(self) -> RawDataGuard:
        self.before = snapshot(self.raw_dir)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.diff = diff_snapshots(self.before, snapshot(self.raw_dir))
        if any(self.diff.values()) and exc_type is None:
            raise RawDataModified(self.diff)


def open_raw_bytes(path: Path, raw_dir: Path) -> BinaryIO:
    """Open a raw file for BINARY READING only. Refuses a path that is not inside ``raw_dir``."""
    resolved = Path(path).resolve()
    root = Path(raw_dir).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise PermissionError(f"{resolved.name!r} is outside the raw dataset directory") from None
    return resolved.open("rb")
