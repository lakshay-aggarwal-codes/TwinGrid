"""Free-tier provider presets for the Copilot (CP-4). Data only plus two pure functions; no network, no keys.

A preset fills in a provider's *base URL* when ``COPILOT_LLM_PROVIDERS`` names it and ``COPILOT_LLM_<NAME>_BASE_URL``
is empty, and supplies conservative client-side request limits (``COPILOT_LLM_<NAME>_RPM`` / ``_RPD`` override them,
``0`` switches that limit off). Models are never defaulted: free model ids rotate, so set ``_MODEL`` yourself.
Keys come from ``COPILOT_LLM_<NAME>_API_KEY`` (or ``_API_KEY_FILE``) exactly as in CP-1.

All four providers take ``Authorization: Bearer <key>`` on an OpenAI-style ``/chat/completions``, which is what
``llm._call_provider`` sends, so no per-provider header code is needed.

The values below were read from provider pages and third-party summaries on ``VERIFIED``; free tiers change without
notice. See ``docs/copilot/PROVIDERS.md`` for sources and what is NOT verified.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

VERIFIED = "2026-10-31"
MAX_LIMIT = 1_000_000


@dataclass(frozen=True)
class Preset:
    name: str
    base_url: str  # no trailing slash; llm appends /chat/completions
    rpm: int  # conservative client-side default; 0 = none
    rpd: int
    docs_url: str


PRESETS: dict[str, Preset] = {
    "gemini": Preset(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        5,  # placeholder: Gemini free limits vary by model and were NOT verified
        100,
        "https://ai.google.dev/gemini-api/docs/openai",
    ),
    "groq": Preset(
        "groq",
        "https://api.groq.com/openai/v1",  # the /openai segment is required
        24,  # published free limit is 30 requests/min for chat models; 80% margin
        900,  # per-model daily caps differ (reported 1,000 for a 70B model); stay under
        "https://console.groq.com/docs/rate-limits",
    ),
    "openrouter": Preset(
        "openrouter",
        "https://openrouter.ai/api/v1",
        16,  # published: 20 requests/min on :free models; 80% margin
        50,  # published: 50/day until $10 of credits were ever bought, then 1,000/day (set _RPD=1000)
        "https://openrouter.ai/docs/api-reference/limits",
    ),
    "github": Preset(
        "github",
        "https://models.github.ai/inference",
        5,  # placeholder: GitHub Models limits are per model class and were NOT verified
        50,
        "https://docs.github.com/en/rest/models/inference",
    ),
}


def _names(env: Mapping[str, str]) -> list[str]:
    return [n.strip().lower() for n in str(env.get("COPILOT_LLM_PROVIDERS") or "").split(",") if n.strip()]


def env_prefix(name: str) -> str:
    return f"COPILOT_LLM_{name.upper()}_"


def with_presets(environ: Mapping[str, str] | None = None) -> Mapping[str, str] | None:
    """Return ``environ`` with preset base URLs filled in, or ``environ`` itself when nothing applies. Never mutates."""
    env = os.environ if environ is None else environ
    wanted = [n for n in _names(env) if n in PRESETS]
    missing = [n for n in wanted if not str(env.get(env_prefix(n) + "BASE_URL") or "").strip()]
    if not missing:
        return environ
    out = dict(env)
    for n in missing:
        out[env_prefix(n) + "BASE_URL"] = PRESETS[n].base_url
    return out


def _limit(raw: object, default: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if 0 <= value <= MAX_LIMIT else default


def limits_for(name: str, environ: Mapping[str, str] | None = None) -> tuple[int, int]:
    """``(requests per minute, requests per day)`` for a provider; 0 means no client-side limit. Never raises."""
    env = os.environ if environ is None else environ
    preset = PRESETS.get(str(name).strip().lower())
    rpm, rpd = (preset.rpm, preset.rpd) if preset else (0, 0)
    prefix = env_prefix(str(name).strip())
    return _limit(env.get(prefix + "RPM"), rpm), _limit(env.get(prefix + "RPD"), rpd)


__all__ = ["PRESETS", "Preset", "VERIFIED", "env_prefix", "limits_for", "with_presets"]
