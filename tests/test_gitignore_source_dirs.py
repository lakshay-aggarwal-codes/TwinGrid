"""A source or doc directory must never be swallowed by a generic .gitignore pattern.

`runs/` (TensorBoard output) and `env/` (virtualenv) were unanchored, so they also ignored `twin-stream-insight-main/src/runs`,
`src/components/runs`, `reports/runs` and `docs/env`: files that were on disk but never committed, so a clean clone could not
build. Skips if git is not available.
"""

from __future__ import annotations

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


def _ignored(path: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT, capture_output=True)
    return r.returncode == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_source_and_doc_directories_are_not_ignored():
    assert [p for p in MUST_BE_TRACKABLE if _ignored(p)] == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_the_generic_output_directories_are_still_ignored_at_the_repository_root():
    assert [p for p in MUST_STAY_IGNORED if not _ignored(p)] == []
