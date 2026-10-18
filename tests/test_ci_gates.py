"""Task 7: guard the CI type-ratchet configuration so it cannot silently drift back to an unmeasured state."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
DEV = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")


def test_pyrefly_ceiling_is_a_recorded_integer():
    m = re.search(r'^\s*PYREFLY_ERROR_CEILING:\s*"(\w+)"', CI, re.M)
    assert m, "PYREFLY_ERROR_CEILING missing from ci.yml"
    assert m.group(1).isdigit(), "ceiling must be a measured integer, not a placeholder"


def test_ceiling_is_recorded_in_the_evidence_file():
    ceiling = re.search(r'^\s*PYREFLY_ERROR_CEILING:\s*"(\d+)"', CI, re.M).group(1)
    record = (ROOT / "reports" / "postT9" / "T11_ci_run.md").read_text(encoding="utf-8")
    assert f"{ceiling} errors" in record or f"| {ceiling} |" in record


def test_pyrefly_is_pinned_exactly():
    assert re.search(r"^pyrefly==\d+\.\d+\.\d+$", DEV, re.M), "a ratchet needs one checker version"


def test_ci_runs_the_audit_regressions_as_a_named_step():
    assert "pytest tests/test_audit_regressions.py" in CI


def test_only_the_two_docker_stack_jobs_are_advisory():
    jobs = re.split(r"^  (?=[a-z][\w-]*:\s*$)", CI.split("\njobs:\n", 1)[1], flags=re.M)
    advisory = {j.split(":", 1)[0] for j in jobs if re.search(r"^    continue-on-error: true", j, re.M)}
    assert advisory == {"frontend-e2e", "frontend-contract"}
