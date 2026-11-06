"""Path anchoring.

Every path is resolved against the REPOSITORY ROOT, which is derived from this file's location -- never from the
current working directory. (A cwd-relative ``research/danish_aau`` join breaks as soon as the process starts inside
``research/``, producing ``research/research/...``; that is the failure the earlier audit tests hit.)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PACKAGE_DIR = Path(__file__).resolve().parent  # .../research/danish_aau/evaluation
DANISH_AAU_DIR = PACKAGE_DIR.parent  # .../research/danish_aau
REPO_ROOT = DANISH_AAU_DIR.parent.parent  # repository root

DEFAULT_CONFIG_PATH = DANISH_AAU_DIR / "config" / "default.toml"
DEFAULT_RAW_RELATIVE = "realData/danish-server-room-v5/raw"
DEFAULT_OUTPUT_RELATIVE = "research/danish_aau/outputs"
ENV_RAW_DIR = "TWINGRID_AAU_RAW_DIR"

# First path component (relative to the repo root) under which the harness refuses to write.
PRODUCTION_ROOTS: tuple[str, ...] = (
    "src",
    "api",
    "models",
    "data",
    "tests",
    "alembic",
    "deploy",
    "configs",
    "scripts",
    "docs",
    "reports",
    "notebooks",
    "artifacts_training",
    "twin-stream-insight-main",
    "realData",
    ".github",
)


class UnsafeOutputPath(ValueError):
    """The requested output directory could overwrite raw data or production files."""


@dataclass(frozen=True)
class ResolvedPath:
    path: Path
    source: str  # "cli" | "env" | "config" | "default"


def resolve_against_root(value: str | os.PathLike[str], repo_root: Path = REPO_ROOT) -> Path:
    """Absolute path of ``value``; a relative value is taken relative to ``repo_root``, not to the cwd."""
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (Path(repo_root) / p).resolve()


def resolve_raw_dir(
    cli_value: str | None = None,
    config_value: str = "",
    *,
    repo_root: Path = REPO_ROOT,
    environ: Mapping[str, str] | None = None,
) -> ResolvedPath:
    """Raw dataset directory. Precedence: CLI flag > $TWINGRID_AAU_RAW_DIR > config > repo default."""
    env = os.environ if environ is None else environ
    if cli_value:
        return ResolvedPath(resolve_against_root(cli_value, repo_root), "cli")
    if env.get(ENV_RAW_DIR):
        return ResolvedPath(resolve_against_root(env[ENV_RAW_DIR], repo_root), "env")
    if config_value:
        return ResolvedPath(resolve_against_root(config_value, repo_root), "config")
    return ResolvedPath(resolve_against_root(DEFAULT_RAW_RELATIVE, repo_root), "default")


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def ensure_output_dir_safe(out_dir: Path, raw_dir: Path, repo_root: Path = REPO_ROOT) -> Path:
    """Return the resolved output dir, or raise UnsafeOutputPath.

    Refused: inside (or equal to) the raw dataset directory; a parent of it; or under a production root of the repo.
    A location outside the repository (for example a temp directory) is allowed.
    """
    out = Path(out_dir).resolve()
    raw = Path(raw_dir).resolve()
    root = Path(repo_root).resolve()
    if out == raw or _is_within(out, raw):
        raise UnsafeOutputPath(f"output directory {out.name!r} is inside the raw dataset directory")
    if _is_within(raw, out):
        raise UnsafeOutputPath(f"output directory {out.name!r} contains the raw dataset directory")
    if out == root:
        raise UnsafeOutputPath("output directory is the repository root")
    if _is_within(out, root):
        first = out.relative_to(root).parts[:1]
        if first and first[0] in PRODUCTION_ROOTS:
            raise UnsafeOutputPath(
                f"output directory is under the production path {first[0]!r}; research outputs go under research/"
            )
    return out
