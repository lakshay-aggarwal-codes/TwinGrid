"""Reuse of existing TwinGrid helpers WITHOUT importing the ``src`` package.

``src/__init__.py`` imports the whole digital twin and calls ``setup_logging()`` (root-logger rewiring plus a
rotating file under ``logs/``). The reproducibility helpers we want to reuse (``src/repro/canonical.py`` for
canonical JSON/hashing, ``src/repro/env.py`` for code-revision/platform capture) are stdlib-only, so they are
loaded by FILE PATH. If either ever gains a package-relative import, loading fails loudly and the isolation test
(test_eval_isolation.py) fails in CI, which is the intended signal.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .paths import REPO_ROOT


class ReuseError(RuntimeError):
    """A reused TwinGrid helper could not be loaded standalone."""


def _load_by_path(alias: str, relative: str, repo_root: Path = REPO_ROOT) -> ModuleType:
    path = Path(repo_root) / relative
    if not path.is_file():
        raise ReuseError(
            f"{relative} not found under {repo_root.name!r}; the harness must live inside the TwinGrid repo"
        )
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise ReuseError(f"cannot build an import spec for {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - re-raised with context
        sys.modules.pop(alias, None)
        raise ReuseError(f"{relative} could not be loaded standalone: {exc}") from exc
    return module


@lru_cache(maxsize=None)
def canonical() -> ModuleType:
    """``src/repro/canonical.py``: canonical_dumps, canonical_bytes, sha256_json, sha256_raw_file, ..."""
    return _load_by_path("_twingrid_repro_canonical", "src/repro/canonical.py")


@lru_cache(maxsize=None)
def repro_env() -> ModuleType:
    """``src/repro/env.py``: code_state, platform_info, scrub_argv, to_relative, ..."""
    return _load_by_path("_twingrid_repro_env", "src/repro/env.py")
