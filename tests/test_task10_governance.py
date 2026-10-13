"""Task 10: governance and supply-chain files are well-formed and agree with each other. No network."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
NEW_WORKFLOWS = ("codeql.yml", "secret-scan.yml", "sbom.yml")


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    return wf.get("on", wf.get(True)) or {}  # PyYAML parses a bare `on:` key as True


def test_dependabot_covers_four_ecosystems_weekly_and_grouped():
    cfg = _yaml(ROOT / ".github" / "dependabot.yml")
    assert cfg["version"] == 2
    by_eco = {u["package-ecosystem"]: u for u in cfg["updates"]}
    assert set(by_eco) == {"pip", "npm", "github-actions", "docker"}
    for update in by_eco.values():
        assert update["schedule"]["interval"] == "weekly"
        assert update["groups"], "updates must be grouped"
    assert by_eco["npm"]["directory"] == "/twin-stream-insight-main"
    assert (ROOT / "twin-stream-insight-main" / "package-lock.json").exists()
    assert (ROOT / "Dockerfile").exists() and (ROOT / "requirements.txt").exists()


def test_new_workflows_are_least_privilege_and_safe():
    for name in NEW_WORKFLOWS:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        wf = yaml.safe_load(text)
        assert wf["permissions"] == {"contents": "read"}, name
        assert "pull_request_target" not in _triggers(wf), name
        assert "pull_request_target" not in text
        assert set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) <= {"GITHUB_TOKEN"}, name
        for block in re.findall(r"run: \|\n((?:\s{10}.*\n)+)", text):
            assert "${{" not in block, f"{name}: use env: for context values inside run:"
    codeql = _yaml(WORKFLOWS / "codeql.yml")["jobs"]["analyze"]
    assert codeql["permissions"]["security-events"] == "write"
    assert set(codeql["strategy"]["matrix"]["language"]) == {"python", "javascript-typescript"}


def test_ci_yml_was_not_touched_by_task10_names():
    jobs = set(_yaml(WORKFLOWS / "ci.yml")["jobs"])
    assert {"lint", "test", "test-postgres", "audit", "frontend", "docker"} <= jobs


def test_gitleaks_config_parses_and_allowlist_is_only_documented_placeholders():
    cfg = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert cfg["extend"]["useDefault"] is True
    regexes = cfg["allowlist"]["regexes"]
    assert regexes
    for pattern in regexes:
        re.compile(pattern)
        assert re.search(r"not|change-me|your[-_]|placeholder|ci[-_]|test[-_]", pattern), pattern
    assert "paths" not in cfg["allowlist"], "allowlist by regex only; no blanket path exclusions"


def test_every_workflow_action_is_listed_in_unpinned_actions():
    doc = (ROOT / "docs" / "governance" / "UNPINNED_ACTIONS.md").read_text(encoding="utf-8")
    used = set()
    for path in WORKFLOWS.glob("*.yml"):
        used |= set(re.findall(r"uses:\s*([\w./-]+)@", path.read_text(encoding="utf-8")))
    assert used
    for action in sorted(used):
        assert f"`{action}@" in doc, f"{action} missing from UNPINNED_ACTIONS.md"


def test_branch_protection_doc_names_real_ci_jobs_and_is_not_applied():
    doc = (ROOT / "docs" / "governance" / "BRANCH_PROTECTION.md").read_text(encoding="utf-8")
    jobs = set(_yaml(WORKFLOWS / "ci.yml")["jobs"])
    for name in re.findall(r'"contexts": \[(.*?)\]', doc, re.S)[0].replace('"', "").split(","):
        assert name.strip() in jobs
    assert "NOT applied" in doc
    assert "gh api --method PUT" in doc and "&&" not in doc


def test_security_md_is_truthful_about_scanning():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "<OWNER MUST FILL>" in text
    assert "NOT VERIFIED" in text and "Scanning configured" in text
    lowered = text.lower()
    for phrase in (
        "scanning passing",
        "no vulnerabilities",
        "fully secure",
        "production-ready",
        "penetration test passed",
    ):
        assert phrase not in lowered
    for needle in ("pip-audit", "npm audit", "dependabot.yml", "codeql.yml", "secret-scan.yml", "sbom.yml"):
        assert needle in text
    assert "Dependabot is not configured" not in text


def test_templates_and_codeowners_exist_and_parse():
    github = ROOT / ".github"
    assert (github / "pull_request_template.md").read_text(encoding="utf-8").count("- [ ]") >= 5
    for name in ("bug_report.yml", "feature_request.yml", "config.yml"):
        assert isinstance(_yaml(github / "ISSUE_TEMPLATE" / name), dict)
    for name in ("bug_report.yml", "feature_request.yml"):
        cfg = _yaml(github / "ISSUE_TEMPLATE" / name)
        assert cfg["name"] and cfg["body"]
    codeowners = (github / "CODEOWNERS").read_text(encoding="utf-8")
    assert "<OWNER MUST FILL>" in codeowners
    assert not [ln for ln in codeowners.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_contributing_points_at_the_gates():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for needle in ("npm run verify", "gen_api_reference.py", "SECURITY.md", "UNPINNED_ACTIONS.md"):
        assert needle in text
