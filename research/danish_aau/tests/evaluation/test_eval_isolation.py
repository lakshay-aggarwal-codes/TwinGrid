"""Isolation contract: the harness does not touch production code, and production code does not touch the harness."""

import ast
import json
import subprocess
import sys

from research.danish_aau.evaluation.paths import DANISH_AAU_DIR, REPO_ROOT

PACKAGE = DANISH_AAU_DIR / "evaluation"
FORBIDDEN_TOP_LEVEL = {
    "src", "api", "models", "database", "db_url", "alembic",
    "sqlalchemy", "fastapi", "redis", "psycopg2", "asyncpg", "torch", "tensorflow", "keras", "paho",
}  # fmt: skip
# Only these harness files may import production code (none exist in Phase 1; Phase 3 adds twin_adapter.py).
SRC_IMPORT_ALLOWLIST = {"twin_adapter.py"}


def _imported_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_harness_modules_import_no_production_or_database_code():
    offenders = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name in SRC_IMPORT_ALLOWLIST:
            continue
        bad = _imported_roots(path) & FORBIDDEN_TOP_LEVEL
        if bad:
            offenders[path.relative_to(REPO_ROOT).as_posix()] = sorted(bad)
    assert offenders == {}


def test_nothing_in_production_imports_the_research_package():
    offenders = []
    candidates = [p for d in ("src", "api", "models", "alembic", "scripts") for p in (REPO_ROOT / d).rglob("*.py")]
    candidates += list(REPO_ROOT.glob("*.py"))
    for path in candidates:
        try:
            if "research" in _imported_roots(path):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
        except SyntaxError:
            continue
    assert offenders == []
    assert len(candidates) > 50  # the scan really looked at the codebase


def test_importing_the_harness_does_not_load_src_or_rewire_logging():
    code = (
        "import logging, sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "before = list(logging.getLogger().handlers)\n"
        "import research.danish_aau.evaluation.cli, research.danish_aau.evaluation.stages\n"
        "src_modules = [m for m in sys.modules if m == 'src' or m.startswith('src.')]\n"
        "print(__import__('json').dumps({'src_modules': src_modules, 'handlers_changed': before != list(logging.getLogger().handlers)}))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"src_modules": [], "handlers_changed": False}


def test_reused_twingrid_helpers_load_standalone():
    from research.danish_aau.evaluation import _reuse

    canonical = _reuse.canonical()
    assert canonical.canonical_dumps({"b": 1, "a": 0.0}).startswith('{\n  "a"')
    assert callable(_reuse.repro_env().code_state)


def test_raw_data_and_outputs_are_git_ignored():
    root_ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "realData/" in root_ignore
    assert "outputs/" in (DANISH_AAU_DIR / ".gitignore").read_text(encoding="utf-8")
