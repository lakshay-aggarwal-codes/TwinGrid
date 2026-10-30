"""Copilot LLM provider configuration (CP-1).

Turns the environment into an ORDERED list of :class:`ProviderConfig`. Pure Python: no FastAPI, no database, no network.
Nothing here calls a provider (``llm._call_provider`` does) and nothing here chooses between providers (the failover
router is CP-2). With only the legacy ``COPILOT_LLM_*`` variables set, the list holds exactly one provider named
``default`` and behaviour is the Task 24 behaviour.

Variables (names only; secrets are read with ``api.secrets.read_secret``, so ``<NAME>_FILE`` works too):

* ``COPILOT_LLM_ENABLED``     global switch. Off (or unset) means no providers at all.
* ``COPILOT_LLM_PROVIDERS``   ordered, comma-separated provider names, e.g. ``ollama,groq``. Empty means just ``default``.
* per provider ``<NAME>`` (upper-cased, ``-`` becomes ``_``): ``COPILOT_LLM_<NAME>_BASE_URL``, ``_MODEL``, ``_API_KEY``,
  ``_TIMEOUT_S``, ``_MAX_OUTPUT_TOKENS``, ``_ENABLED`` (default true), ``_LOCAL`` (default false), ``_DATA_POLICY``.
* the provider named ``default`` reads the legacy names ``COPILOT_LLM_BASE_URL``, ``_MODEL``, ``_API_KEY`` ...
* ``COPILOT_LLM_TIMEOUT_S`` / ``COPILOT_LLM_MAX_OUTPUT_TOKENS`` are the fallback for any provider that sets none.

A bad number, a bad flag, a bad name or a bad data policy never raises: the value falls back to its default or the entry
is skipped.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

DEFAULT_PROVIDER = "default"
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_MAX_OUTPUT_TOKENS = 400
MAX_PROVIDERS = 8
POLICY_LOCAL = "local"
POLICY_CLOUD = "cloud"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


@dataclass(frozen=True)
class ProviderConfig:
    """One OpenAI-compatible provider. ``api_key`` is never shown by ``repr``; ``key_secret`` is only the variable name."""

    name: str = DEFAULT_PROVIDER
    base_url: str = ""
    model: str = ""
    key_secret: str = "COPILOT_LLM_API_KEY"
    api_key: str | None = field(default=None, repr=False)
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    enabled: bool = True
    local: bool = False
    data_policy: str = POLICY_CLOUD  # POLICY_LOCAL exactly when ``local`` is true (see _policy)

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.base_url) and bool(self.model)


def number(raw: Any, default: float, low: float, high: float) -> float:
    """``raw`` as a float inside ``[low, high]``, else ``default``. Never raises."""
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


def flag(raw: Any, default: bool) -> bool:
    text = str(raw).strip().lower() if raw is not None else ""
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return default


def llm_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return flag(env.get("COPILOT_LLM_ENABLED"), False)


def parse_names(raw: Any) -> list[str]:
    """Ordered, de-duplicated, valid provider names. Invalid names are dropped; at most ``MAX_PROVIDERS`` are kept."""
    names: list[str] = []
    for part in str(raw or "").split(","):
        name = part.strip().lower()
        if _NAME.fullmatch(name) and name not in names:
            names.append(name)
    return names[:MAX_PROVIDERS]


def _prefix(name: str) -> str:
    return "COPILOT_LLM_" if name == DEFAULT_PROVIDER else "COPILOT_LLM_" + name.upper().replace("-", "_") + "_"


def _policy(raw: Any, local: bool) -> str:
    """A provider is ``local`` only if flagged local. A cloud provider can never claim the local policy, and a local one
    cannot be downgraded by a typo, so a bad or contradictory value is decided by the ``local`` flag alone."""
    wanted = str(raw or "").strip().lower()
    if wanted == POLICY_CLOUD and local:
        return POLICY_LOCAL
    return POLICY_LOCAL if local else POLICY_CLOUD


def _read_key(env: Mapping[str, str], secret: str, use_secret_reader: bool) -> str | None:
    if not use_secret_reader:
        return env.get(secret) or None
    from api.secrets import read_secret  # lazy: api/ is not imported unless the feature is on

    return read_secret(secret) or None


def load_provider(name: str, environ: Mapping[str, str] | None = None) -> ProviderConfig:
    env = os.environ if environ is None else environ
    p = _prefix(name)
    local = flag(env.get(p + "LOCAL"), False) if name != DEFAULT_PROVIDER else flag(env.get("COPILOT_LLM_LOCAL"), False)
    fallback_t = number(env.get("COPILOT_LLM_TIMEOUT_S"), DEFAULT_TIMEOUT_S, 0.1, 120.0)
    fallback_m = int(number(env.get("COPILOT_LLM_MAX_OUTPUT_TOKENS"), DEFAULT_MAX_OUTPUT_TOKENS, 16, 4000))
    secret = p + "API_KEY"
    return ProviderConfig(
        name=name,
        base_url=str(env.get(p + "BASE_URL", "")).strip().rstrip("/"),
        model=str(env.get(p + "MODEL", "")).strip(),
        key_secret=secret,
        api_key=_read_key(env, secret, environ is None),
        timeout_s=number(env.get(p + "TIMEOUT_S"), fallback_t, 0.1, 120.0),
        max_output_tokens=int(number(env.get(p + "MAX_OUTPUT_TOKENS"), fallback_m, 16, 4000)),
        enabled=flag(env.get(p + "ENABLED"), True) if name != DEFAULT_PROVIDER else True,
        local=local,
        data_policy=_policy(env.get(p + "DATA_POLICY"), local),
    )


def load_providers(environ: Mapping[str, str] | None = None) -> list[ProviderConfig]:
    """All providers in configured order, disabled ones included (see :func:`active_providers`).

    Empty when ``COPILOT_LLM_ENABLED`` is off. With ``COPILOT_LLM_PROVIDERS`` unset or empty, one ``default`` provider
    built from the legacy variables (Task 24 behaviour, even when its URL or model is missing).
    """
    env = os.environ if environ is None else environ
    if not llm_enabled(env):
        return []
    raw = str(env.get("COPILOT_LLM_PROVIDERS", "")).strip()
    names = parse_names(raw) if raw else [DEFAULT_PROVIDER]
    return [load_provider(n, environ) for n in names]


def active_providers(providers: list[ProviderConfig]) -> list[ProviderConfig]:
    """Enabled providers that have a base URL and a model, in order. Disabled or half-configured ones are skipped."""
    return [p for p in providers if p.configured]
