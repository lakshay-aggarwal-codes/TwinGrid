"""A source or doc directory must never be swallowed by a generic .gitignore pattern.

`runs/` (TensorBoard output) and `env/` (virtualenv) were unanchored, so they also ignored `twin-stream-insight-main/src/runs`,
`src/components/runs`, `reports/runs` and `docs/env`: files that were on disk but never committed, so a clean clone could not
build. Skips if git is not available.

The check is hermetic: it copies the repository's own ``.gitignore`` files into a throw-away repository and asks git
there, with the user's global ignore file, ``~/.config/git/ignore`` and ``.git/info/exclude`` out of the picture. A
developer's personal ignore rule (for example a template that ignores ``env/``) says nothing about what a clean clone
tracks, so it must neither fail nor satisfy this test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MUST_BE_TRACKABLE = (
    "twin-stream-insight-main/src/runs/schema.ts",
    "twin-stream-insight-main/src/components/runs/placeholder.tsx",
    "reports/runs/baselines-v2/manifest.json",
    "docs/env/Task1.md",
)
MUST_STAY_IGNORED = ("runs/events.out", "env/pyvenv.cfg", ".env")


_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


@pytest.fixture(scope="module")
def is_ignored(tmp_path_factory):
    """``is_ignored(path)``: would git ignore ``path`` according to this repository's own ``.gitignore`` files only?

    Builds a throw-away repository holding copies of every ``.gitignore`` at the same relative paths.
    """
    repo = tmp_path_factory.mktemp("ignore_rules")
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if ".gitignore" in filenames:
            target = repo / Path(dirpath).relative_to(ROOT) / ".gitignore"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(dirpath) / ".gitignore", target)
    home = repo / "_home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True, capture_output=True)
    (repo / ".git" / "info" / "exclude").write_text("", encoding="utf-8")
    # Windows and macOS checkouts are case-insensitive: an unanchored ``ENV/`` there also ignores ``docs/env``. Force that
    # mode so the test fails on every platform for a rule that would only bite on some.
    subprocess.run(["git", "config", "core.ignorecase", "true"], cwd=repo, env=env, check=True, capture_output=True)

    def check(path: str) -> bool:
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=repo, env=env, capture_output=True)
        return r.returncode == 0

    return check


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_source_and_doc_directories_are_not_ignored(is_ignored):
    assert [p for p in MUST_BE_TRACKABLE if is_ignored(p)] == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_the_generic_output_directories_are_still_ignored_at_the_repository_root(is_ignored):
    assert [p for p in MUST_STAY_IGNORED if not is_ignored(p)] == []
