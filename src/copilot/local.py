"""Local LLM support for the Copilot (CP-3): Ollama preset, quick health check, local timeout.

Pure Python: no FastAPI, no database, no import of ``llm.py`` or ``router.py``. Nothing here talks to a model; it only asks
the local server "are you up, and do you have the model?" so a missing Ollama costs about a second once, not a full
timeout on every question.

* **Preset.** If ``COPILOT_LLM_PROVIDERS`` contains ``ollama`` and ``COPILOT_LLM_OLLAMA_BASE_URL`` is empty, the base URL
  defaults to ``http://localhost:11434/v1``. ``COPILOT_LLM_OLLAMA_LOCAL`` defaults to ``true`` only when the host is this
  machine (localhost, 127.0.0.1, ::1, ``host.docker.internal`` or the compose service ``ollama``); a remote host never
  gets the "no data leaves this machine" flag by default. The model is never defaulted: set it in ``.env``.
* **Health check.** For a provider flagged local, ``GET <root>/api/tags`` (Ollama) with a 1 s timeout; the model must be
  listed. A server without ``/api/tags`` (llama.cpp server) is checked with ``GET <base>/models`` instead. The result is
  cached (up 30 s, down 15 s) and thread-safe.
* **Timeout.** A local provider that keeps the default timeout gets ``COPILOT_LLM_LOCAL_TIMEOUT_S`` (default 30 s).

Logging: our own outcome words only. Never a prompt, an answer, a question or telemetry.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

PRESET_NAME = "ollama"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DOCKER_HOST_BASE_URL = "http://host.docker.internal:11434/v1"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"})

DEFAULT_LOCAL_TIMEOUT_S = 30.0
HEALTH_TIMEOUT_S = 1.0
UP_TTL_S = 30.0
DOWN_TTL_S = 15.0
MAX_HEALTH_BYTES = 256 * 1024

REASON_UP = "up"
REASON_DOWN = "local_down"
REASON_MODEL_MISSING = "local_model_missing"
REASON_BAD_RESPONSE = "local_bad_response"


@dataclass(frozen=True)
class Health:
    ok: bool
    reason: str  # one of the REASON_* words


# ----------------------------------------------------------------------------- preset and numbers


def _number(raw: Any, default: float, low: float, high: float) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value == value and low <= value <= high else default  # NaN and out of range -> default


def local_timeout_s(environ: Mapping[str, str] | None = None) -> float:
    """``COPILOT_LLM_LOCAL_TIMEOUT_S`` in [1, 300]; anything else gives 30. Never raises."""
    env = os.environ if environ is None else environ
    return _number(env.get("COPILOT_LLM_LOCAL_TIMEOUT_S"), DEFAULT_LOCAL_TIMEOUT_S, 1.0, 300.0)


def host_of(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return ""


def is_local_host(base_url: str) -> bool:
    return host_of(base_url) in LOCAL_HOSTS


def with_ollama_preset(environ: Mapping[str, str] | None = None) -> Mapping[str, str] | None:
    """Return ``environ`` with the Ollama preset filled in, or ``environ`` itself when there is nothing to add.

    The input is never modified. ``None`` (meaning ``os.environ``) comes back as ``None`` when the preset is not used.
    """
    env = os.environ if environ is None else environ
    names = [n.strip().lower() for n in str(env.get("COPILOT_LLM_PROVIDERS") or "").split(",")]
    if PRESET_NAME not in names:
        return environ
    prefix = f"COPILOT_LLM_{PRESET_NAME.upper()}_"
    out = dict(env)
    if not str(out.get(prefix + "BASE_URL") or "").strip():
        out[prefix + "BASE_URL"] = DEFAULT_OLLAMA_BASE_URL
    if not str(out.get(prefix + "LOCAL") or "").strip() and is_local_host(out[prefix + "BASE_URL"].strip()):
        out[prefix + "LOCAL"] = "true"
    return out


def prepare(settings: Any, environ: Mapping[str, str] | None, default_timeout_s: float) -> Any:
    """For a local provider on the default timeout, use the longer local timeout. Others are returned unchanged."""
    from dataclasses import replace

    if getattr(settings, "local", False) and getattr(settings, "timeout_s", None) == default_timeout_s:
        return replace(settings, timeout_s=local_timeout_s(environ))
    return settings


# ----------------------------------------------------------------------------- health check


def ollama_root(base_url: str) -> str:
    """``http://host:11434/v1`` -> ``http://host:11434`` (the part Ollama's own ``/api`` lives under)."""
    root = base_url.strip().rstrip("/")
    return root[: -len("/v1")] if root.endswith("/v1") else root


def model_listed(model: str, names: list[str]) -> bool:
    """``llama3.2`` matches ``llama3.2:latest``; a model given with a tag must match exactly."""
    wanted = model.strip()
    if not wanted:
        return False
    if wanted in names:
        return True
    return ":" not in wanted and f"{wanted}:latest" in names


Fetch = Callable[
    [str, float], "tuple[int, bytes]"
]  # (url, timeout) -> (status, body); raises OSError-like on no connect


def _requests_fetch(url: str, timeout_s: float) -> tuple[int, bytes]:
    import requests

    resp = requests.get(url, timeout=timeout_s, allow_redirects=False, stream=True)
    try:
        raw = bytearray()
        for chunk in resp.iter_content(chunk_size=8192):
            raw += chunk
            if len(raw) > MAX_HEALTH_BYTES:
                break
        return resp.status_code, bytes(raw)
    finally:
        resp.close()


def _probe(base_url: str, model: str, fetch: Fetch) -> Health:
    import json

    try:
        status, body = fetch(f"{ollama_root(base_url)}/api/tags", HEALTH_TIMEOUT_S)
        if status == 404:  # not Ollama (e.g. llama.cpp server): the OpenAI-style list is the only thing to ask
            status, body = fetch(f"{base_url.strip().rstrip('/')}/models", HEALTH_TIMEOUT_S)
            return Health(status == 200, REASON_UP if status == 200 else REASON_BAD_RESPONSE)
    except Exception:  # noqa: BLE001 - connection refused, timeout, DNS, TLS: all mean "not reachable"
        return Health(False, REASON_DOWN)
    if status != 200:
        return Health(False, REASON_BAD_RESPONSE)
    try:
        data = json.loads(body.decode("utf-8"))
        names = [str(m["name"]) for m in data["models"] if isinstance(m, dict) and "name" in m]
    except (ValueError, KeyError, TypeError):
        return Health(False, REASON_BAD_RESPONSE)
    return Health(True, REASON_UP) if model_listed(model, names) else Health(False, REASON_MODEL_MISSING)


class HealthCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: dict[str, tuple[float, Health]] = {}

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {k: h.reason for k, (_, h) in self._seen.items()}

    def check(self, base_url: str, model: str, fetch: Fetch | None = None) -> Health:
        key = f"{base_url.strip()}|{model.strip()}"
        now = self._clock()
        with self._lock:
            hit = self._seen.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]
        health = _probe(base_url, model, fetch or _requests_fetch)  # outside the lock: it may take up to ~2 s
        ttl = UP_TTL_S if health.ok else DOWN_TTL_S
        with self._lock:
            self._seen[key] = (self._clock() + ttl, health)
        return health


HEALTH = HealthCache()


def check(settings: Any, fetch: Fetch | None = None) -> Health:
    """Health of one local provider (``settings`` has ``base_url`` and ``model``). Never raises."""
    try:
        return HEALTH.check(str(settings.base_url), str(settings.model), fetch)
    except Exception:  # noqa: BLE001
        return Health(False, REASON_DOWN)


def reset() -> None:
    HEALTH.reset()


def main() -> int:
    """``python -m src.copilot.local``: one line per local provider, outcome words only (no keys, no prompts)."""
    from . import llm

    chain = [s for s in llm.load_chain() if s.enabled]
    local = [s for s in chain if s.local]
    if not chain:
        print("COPILOT_LLM_ENABLED is not true: the Copilot answers from rules only.")
        return 1
    if not local:
        print("No provider is flagged local (COPILOT_LLM_<NAME>_LOCAL=true).")
        return 1
    worst = 0
    for s in local:
        if not s.configured:
            print(f"{s.name}: not_configured (needs a base URL and COPILOT_LLM_{s.name.upper()}_MODEL)")
            worst = 1
            continue
        h = check(s)
        print(f"{s.name}: {h.reason} model={s.model} timeout_s={prepare(s, None, llm.DEFAULT_TIMEOUT_S).timeout_s:g}")
        worst = worst or (0 if h.ok else 1)
    return worst


__all__ = [
    "DEFAULT_OLLAMA_BASE_URL",
    "DOCKER_HOST_BASE_URL",
    "HEALTH",
    "Health",
    "HealthCache",
    "check",
    "is_local_host",
    "local_timeout_s",
    "main",
    "model_listed",
    "ollama_root",
    "prepare",
    "reset",
    "with_ollama_preset",
]

if __name__ == "__main__":
    raise SystemExit(main())
