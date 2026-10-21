"""Copilot v1 (Task 14, playbook section 8.4): a rule-based assistant with NO language model.

Every sentence of an answer is a template filled from *evidence* the read-only tools in ``tools.py`` collected from
existing services; numbers and names appear in the answer only as ``[E#]`` markers that point at an evidence item.
What is not known is listed in ``unknowns``; nothing is guessed. ``api/plugins/copilot.py`` is the only HTTP surface.

Pure Python on purpose (no FastAPI, no database, no pydantic outside ``schemas.py``): the plugin injects the loaders.
"""

MODE_RULE_BASED = "rule_based"
MODE_LLM = "llm"
ROOT_CAUSE_UNKNOWN = "Root cause is not determined by available evidence."
HISTORY_UNAVAILABLE = "Stored history comparison is not available in this version."
