"""Task 24 plugin: ETag/304 and gzip for read-only GETs, and an OPT-IN short-TTL Redis cache for two hot reads.

No routes. ``setup(app)`` adds middleware (see ``docs/env/Task24.md`` for the env vars):

* ``ETagMiddleware`` (inner) then Starlette ``GZipMiddleware`` (outer), so the ETag is computed on the plain body.
* The response cache is OFF unless ``PERF_CACHE_NAMESPACES`` lists ``state`` and/or ``scenarios`` AND ``REDIS_URL`` is
  set. With Redis down or unset every request is computed exactly as before. Only ``live=False`` previews are cached;
  the live twin that the WebSocket stream uses is never touched.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.perf.cache import RedisBackend, ResponseCache
from src.perf.etag import DEFAULT_PATHS, ETagMiddleware

logger = logging.getLogger(__name__)

_cache: ResponseCache | None = None
_originals: dict[str, Any] = {}


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def _float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


def install_cache(
    cache: ResponseCache, namespaces: set[str], *, state_ttl_s: float = 2.0, scenarios_ttl_s: float = 30.0
) -> None:
    """Wrap the two service functions (idempotent). ``uninstall_cache`` restores them (tests)."""
    global _cache
    import hashlib
    import json

    from api.serialization import to_jsonable
    from api.services import scenario_registry, twin_service

    _cache = cache
    if "state" in namespaces and "state" not in _originals:
        original = twin_service.compute_state
        _originals["state"] = original

        def compute_state_cached(utilisation, outside_temp, water_stress, mode, *, live=True):
            if live:
                return original(utilisation, outside_temp, water_stress, mode, live=live)
            parts = ["state", utilisation, outside_temp, water_stress, mode, os.getenv("PHYSICS_VERSION", "")]
            # JSON-safe (every caller passes the result through to_jsonable, which leaves it unchanged).
            return cache.get_or_compute(
                "state",
                parts,
                state_ttl_s,
                lambda: to_jsonable(original(utilisation, outside_temp, water_stress, mode, live=False)),
            )

        twin_service.compute_state = compute_state_cached
    if "scenarios" in namespaces and "scenarios" not in _originals:
        original_list = scenario_registry.list_scenarios
        _originals["scenarios"] = original_list
        fingerprint = hashlib.sha256(json.dumps(original_list(), sort_keys=True).encode()).hexdigest()[:16]

        def list_scenarios_cached():
            # The fingerprint is part of the key, so a changed registry never reads an older entry.
            return cache.get_or_compute("scenarios", ["scenarios", fingerprint], scenarios_ttl_s, original_list)

        scenario_registry.list_scenarios = list_scenarios_cached


def uninstall_cache() -> None:
    global _cache
    from api.services import scenario_registry, twin_service

    if "state" in _originals:
        twin_service.compute_state = _originals.pop("state")
    if "scenarios" in _originals:
        scenario_registry.list_scenarios = _originals.pop("scenarios")
    _cache = None


def setup(app) -> None:
    if _flag("PERF_ETAG"):
        paths = [p.strip() for p in os.getenv("PERF_ETAG_PATHS", "").split(",") if p.strip()] or list(DEFAULT_PATHS)
        app.add_middleware(ETagMiddleware, paths=paths)
    if _flag("PERF_GZIP"):
        from starlette.middleware.gzip import GZipMiddleware

        app.add_middleware(GZipMiddleware, minimum_size=int(_float("PERF_GZIP_MIN_BYTES", 1024)), compresslevel=6)
    wanted = {n.strip() for n in os.getenv("PERF_CACHE_NAMESPACES", "").split(",") if n.strip()}
    namespaces = wanted & {"state", "scenarios"}
    url = os.getenv("REDIS_URL", "").strip()
    if namespaces and url:
        install_cache(
            ResponseCache(RedisBackend(url)),
            namespaces,
            state_ttl_s=_float("PERF_CACHE_STATE_TTL_S", 2.0),
            scenarios_ttl_s=_float("PERF_CACHE_SCENARIOS_TTL_S", 30.0),
        )
        logger.info("perf: response cache on for %s", sorted(namespaces))
