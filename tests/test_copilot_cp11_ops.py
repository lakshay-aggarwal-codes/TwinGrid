"""CP-11: the operations documents, runbooks, claims rows and perf specs agree with the code. No network, no server.

Each test fails when a document and the code drift apart (a new environment name nobody documented, a warning code the
runbook never mentions, a runbook nobody links, a claims row the README never uses).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESET_NAMES = "OLLAMA|GROQ|OPENROUTER|GEMINI|GITHUB"


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _copilot_sources() -> list[Path]:
    return [*sorted((ROOT / "src" / "copilot").rglob("*.py")), ROOT / "api" / "plugins" / "copilot.py"]


def test_env_example_names_every_copilot_variable_the_code_reads():
    env = _text(".env.example")
    found: set[str] = set()
    for path in _copilot_sources():
        found |= set(re.findall(r"COPILOT_[A-Z][A-Z0-9_]*[A-Z0-9]", path.read_text(encoding="utf-8")))
    found -= {"COPILOT_LLM", "COPILOT_THREATS"}  # a prefix and a document name, not variables
    assert "COPILOT_LLM_ENABLED" in found and "COPILOT_DOCS_INDEX_PATH" in found, "scanner found nothing"
    missing = []
    for name in sorted(found):
        generic = re.sub(rf"^COPILOT_LLM_({PRESET_NAMES})_", "COPILOT_LLM_<NAME>_", name)
        if generic not in env:
            missing.append(name)
    assert missing == [], f"not in .env.example: {missing}"


def test_env_example_holds_names_only_for_copilot_secrets():
    for line in _text(".env.example").splitlines():
        if re.match(r"^COPILOT_[A-Z0-9_]*_API_KEY(?:_FILE)?=", line):
            assert line.split("=", 1)[1].strip() == "", line


def test_operations_guide_covers_every_runtime_warning_code():
    ops = _text("docs/OPERATIONS.md")
    codes: set[str] = set()
    for rel in ("src/copilot/llm.py", "src/copilot/docs_answer.py"):
        codes |= set(re.findall(r'^WARN_[A-Z_]+ = "([a-z_]+)"', _text(rel), flags=re.M))
    assert {"llm_unavailable", "llm_rejected", "docs_index_stale"} <= codes, "scanner found nothing"
    assert sorted(c for c in codes if c not in ops) == []


def test_operations_guide_has_the_cp11_sections():
    ops = _text("docs/OPERATIONS.md")
    for heading in (
        "### Local-only mode",
        "### Cloud failover chain",
        "### Replace a provider key",
        "### What an outage looks like",
        "### Rebuild the docs index",
        "### Docker note",
    ):
        assert heading in ops, heading
    assert "`COPILOT_LLM_<NAME>_API_KEY`" in ops  # the secrets inventory lists the provider key


def test_every_runbook_is_linked_from_the_runbook_index_and_every_link_resolves():
    index = _text("docs/runbooks/README.md")
    linked = set(re.findall(r"\]\(([a-z0-9-]+\.md)\)", index))
    on_disk = {p.name for p in (ROOT / "docs" / "runbooks").glob("*.md")} - {"README.md"}
    assert linked == on_disk
    assert {"copilot-providers-down.md", "copilot-index-stale.md"} <= on_disk


def test_runbooks_name_commands_that_exist():
    stale = _text("docs/runbooks/copilot-index-stale.md")
    assert "scripts/build_copilot_index.py" in stale and (ROOT / "scripts" / "build_copilot_index.py").is_file()
    assert "scripts/copilot_eval.py" in stale and (ROOT / "scripts" / "copilot_eval.py").is_file()
    down = _text("docs/runbooks/copilot-providers-down.md")
    assert "src.copilot.local" in down and (ROOT / "src" / "copilot" / "local.py").is_file()


def test_perf_script_has_a_docs_question_and_a_model_chain_question():
    from src.copilot import docs_answer
    from src.copilot.answer import classify

    spec = importlib.util.spec_from_file_location("perf_endpoints_cp11", ROOT / "scripts" / "perf_endpoints.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = _text("scripts/perf_endpoints.py")
    assert 'specs["copilot_ask_rag"]' in source and 'specs["copilot_ask_failover"]' in source
    assert docs_answer.docs_cue(module.COPILOT_RAG_QUESTION, "general") == "strong"
    assert docs_answer.docs_cue(module.COPILOT_FAILOVER_QUESTION, "general") is None
    assert classify(module.COPILOT_FAILOVER_QUESTION, "general") != "docs_question"


def test_new_claims_rows_are_in_the_ledger_and_used_by_the_readme():
    claims, readme = _text("docs/CLAIMS.md"), _text("README.md")
    for cid in ("C-36", "C-37", "C-38", "C-39"):
        assert f"| {cid} |" in claims, cid
        assert f"[{cid}]" in readme, cid


def test_model_card_does_not_hide_a_failing_gate():
    report = _text("docs/copilot/EVAL_REPORT.md")
    card = _text("docs/model_cards/copilot.md").lower()
    if re.search(r"\|\s*FAIL\s*\|", report):
        assert "fail" in card, "EVAL_REPORT has a failing gate; the model card must say so"
    assert "docs/copilot/eval_report.md" in card
    for section in ("## intended use", "## data flow", "## evaluation", "## limitations", "## provider terms caveat"):
        assert section in card, section


def test_readme_and_judges_no_longer_say_there_is_no_language_model():
    for rel in ("README.md", "docs/JUDGES.md"):
        text = _text(rel).lower()
        assert "no language model is connected" not in text, rel
        assert "no language model in the tree" not in text, rel
        assert "it has no language model" not in text, rel
