"""CP-0: the repo-drift check (roadmap section 0, "Repo drift").

The CP tasks were written against one snapshot of the repo. If the checkout lacks a file or name they assume, this test
fails with the list of what is missing, instead of a later task silently guessing. It checks that files and names
EXIST; it does not pin their contents (later tasks legitimately edit them).
"""

from __future__ import annotations

import importlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

ASSUMED_FILES = [
    "src/copilot/__init__.py",
    "src/copilot/answer.py",
    "src/copilot/evidence.py",
    "src/copilot/llm.py",
    "src/copilot/schemas.py",
    "src/copilot/tools.py",
    "src/copilot/catalogue.py",
    "api/plugins/copilot.py",
    "api/secrets.py",
    "tests/copilot_conftest_plugin.py",
    "tests/fixtures/copilot/helpers.py",
    "docs/CLAIMS.md",
    "docs/copilot/capabilities.json",
    "docs/copilot/LIMITS.md",
    "docs/env/T24.md",
    ".env.example",
    "pytest.ini",
    "twin-stream-insight-main/src/features/assistant/AnswerView.tsx",
    "twin-stream-insight-main/src/features/assistant/schema.ts",
    "twin-stream-insight-main/src/features/assistant/api.ts",
    "twin-stream-insight-main/e2e/assistant.spec.ts",
]

ASSUMED_NAMES = {
    "src.copilot": ["MODE_RULE_BASED", "MODE_LLM", "ROOT_CAUSE_UNKNOWN", "HISTORY_UNAVAILABLE"],
    "src.copilot.answer": ["INTENTS", "AskInput", "Answer", "classify", "answer_question"],
    "src.copilot.llm": [
        "LlmSettings",
        "load_settings",
        "enhance",
        "validate",
        "build_messages",
        "format_evidence",
        "ProviderError",
        "Rejected",
        "SYSTEM_POLICY",
        "WARN_UNAVAILABLE",
        "WARN_REJECTED",
    ],
    "src.copilot.evidence": ["EvidenceBook", "unbacked_numbers"],
    "src.copilot.tools": ["ToolContext", "NotFound"],
}


def test_every_assumed_file_exists():
    missing = [p for p in ASSUMED_FILES if not (REPO / p).exists()]
    assert not missing, f"the checkout differs from the CP roadmap's assumptions; missing files: {missing}"


def test_every_assumed_name_exists():
    missing = []
    for module, names in ASSUMED_NAMES.items():
        mod = importlib.import_module(module)
        missing += [f"{module}.{n}" for n in names if not hasattr(mod, n)]
    assert not missing, f"the checkout differs from the CP roadmap's assumptions; missing names: {missing}"


def test_the_ask_route_and_llm_variables_are_where_the_roadmap_says():
    route = (REPO / "api/plugins/copilot.py").read_text(encoding="utf-8")
    assert '"/api/copilot/ask"' in route and "answer_question" in route
    env = (REPO / ".env.example").read_text(encoding="utf-8")
    for name in (
        "COPILOT_LLM_ENABLED",
        "COPILOT_LLM_BASE_URL",
        "COPILOT_LLM_MODEL",
        "COPILOT_LLM_API_KEY",
        "COPILOT_LLM_TIMEOUT_S",
        "COPILOT_LLM_MAX_OUTPUT_TOKENS",
    ):
        assert name in env, f"{name} missing from .env.example"
