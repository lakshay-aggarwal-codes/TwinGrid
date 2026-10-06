"""Code revision (+dirty), platform and path helpers for the run manifest (contract 11.1)."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_SUBDIR = "reports/runs"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_TRUE = {"1", "true", "yes", "on"}


class PathOutsideRoot(ValueError):
    """A recorded input path resolves outside the project root."""


def _is_absolute_text(text: str) -> bool:
    return PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute()


def to_relative(path: str | Path, root: Path) -> str:
    """POSIX path of ``path`` relative to ``root``; raises PathOutsideRoot if it is not inside."""
    root = Path(root).resolve()
    p = Path(path)
    p = p if p.is_absolute() else root / p
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        raise PathOutsideRoot(f"{Path(str(path)).name} is outside the project root") from None


def resolve_in_root(rel: str, root: Path) -> Path:
    """The file for a recorded relative path; refuses absolute paths and ``..`` escapes."""
    if _is_absolute_text(rel) or ".." in PurePosixPath(rel).parts:
        raise PathOutsideRoot(f"recorded path {rel!r} is not a project-relative path")
    resolved = (Path(root).resolve() / rel).resolve()
    try:
        resolved.relative_to(Path(root).resolve())
    except ValueError:
        raise PathOutsideRoot(f"recorded path {rel!r} escapes the project root") from None
    return resolved


def scrub_argv(argv: list[str], root: Path) -> list[str]:
    """Command line for the manifest: arguments that are paths inside ``root`` become relative, and any
    other absolute path is reduced to its file name, so the manifest carries no machine-specific path."""
    out = []
    for arg in argv:
        if _is_absolute_text(arg):
            try:
                out.append(to_relative(arg, root))
            except PathOutsideRoot:
                out.append(PureWindowsPath(arg).name if "\\" in arg else PurePosixPath(arg).name)
        else:
            out.append(arg)
    return out


# ----------------------------------------------------------------------------- code revision


def _git(root: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=timeout, check=False)


def code_state(root: Path) -> dict[str, Any]:
    """The code revision of the tree at ``root``.

    ``code_revision`` is the 40-hex commit or ``"unknown"``; ``dirty`` is true when tracked files differ
    from HEAD or there are untracked, non-ignored files (``reports/runs`` itself is excluded, otherwise
    every run would dirty the tree it is recorded in). Rules:

    * a git checkout: both values come from git (``code_revision_source = "git"``);
    * no git, ``GIT_SHA`` set (container build arg): the revision is ``GIT_SHA``; the tree cannot be
      inspected, so ``dirty`` is false unless ``GIT_DIRTY`` is truthy (``code_revision_source =
      "GIT_SHA"``). This trusts the image build;
    * neither: revision ``"unknown"`` and ``dirty = true``, because a tree that cannot be shown to be
      clean must not be promoted.
    """
    env_sha = os.getenv("GIT_SHA", "").strip().lower()
    env_dirty = os.getenv("GIT_DIRTY", "").strip().lower() in _TRUE
    try:
        head = _git(root, "rev-parse", "--verify", "HEAD")
        inside = _git(root, "rev-parse", "--show-toplevel")
        top = Path(inside.stdout.decode().strip()).resolve() if inside.returncode == 0 else None
    except (OSError, Exception):  # noqa: BLE001 - git missing or hung: fall through to the build arg
        head, top = None, None
    if head is not None and head.returncode == 0 and top == Path(root).resolve():
        sha = head.stdout.decode().strip()
        status = _git(root, "status", "--porcelain", "--untracked-files=normal", "--", ".", f":(exclude){RUNS_SUBDIR}")
        diff = _git(root, "diff", "HEAD", "--", ".", f":(exclude){RUNS_SUBDIR}")
        if status.returncode == 0 and diff.returncode == 0:
            changed = status.stdout.strip() != b""
            digest = hashlib.sha256(status.stdout + b"\0" + diff.stdout).hexdigest() if changed else None
            return {"code_revision": sha, "dirty": changed, "dirty_diff_sha256": digest, "code_revision_source": "git"}
    if _SHA40.match(env_sha):
        return {
            "code_revision": env_sha,
            "dirty": env_dirty,
            "dirty_diff_sha256": None,
            "code_revision_source": "GIT_SHA",
        }
    return {"code_revision": "unknown", "dirty": True, "dirty_diff_sha256": None, "code_revision_source": "unknown"}


# ----------------------------------------------------------------------------- platform


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def platform_info() -> dict[str, Any]:
    """OS, architecture, Python and the numeric libraries that decide bit-level results.
    Packages are looked up in the installed metadata, never imported (importing torch/tensorflow is slow)."""
    return {
        "os": platform.system(),
        "os_release": platform.release(),  # informational: not compared by verify
        "arch": platform.machine(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "numpy": _version("numpy"),
        "torch": _version("torch"),
        "tensorflow": _version("tensorflow"),
    }


def running_python() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
