"""Backend extension point: drop a module into ``api/plugins/`` and it is loaded at startup.

A plugin module may export either or both of:

* ``router`` -- an ``fastapi.APIRouter``; it is included in the app with the same default dependencies as the
  core routers (the "general" request-rate window and the log context), so a plugin route can never be the one
  route without a limit.
* ``setup(app)`` -- a callable run once with the FastAPI app (for middleware, event hooks, ``app.state`` wiring).

Rules the loader enforces (see ``docs/env/Task1.md`` for the operator-facing summary):

* Modules are imported in name order. Names starting with ``_`` are ignored (private helpers, ``__init__``).
* A broken plugin (import error, bad ``router`` type, ``setup`` raising, route collision) is logged and skipped;
  nothing about it reaches an API client, and the rest of the application starts normally. The log level is
  ERROR when ``ENVIRONMENT=production`` and WARNING otherwise.
* A plugin whose ``setup`` raises contributes no router (``setup`` runs before the router is included).
* A router is never registered twice: if any ``(path, method)`` it declares already exists on the app -- including
  because the plugin re-exports a core router -- the plugin is skipped.
* ``load_plugins`` runs once per app; a second call returns the first call's results and changes nothing.

Note: it is called after the core routers and before the core middleware are added in ``api/main.py``, so
middleware added by a plugin's ``setup`` sits INSIDE the core middleware (it does not see the core error
boundary's own responses).
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)

__all__ = ["PluginResult", "load_plugins"]


@dataclass(frozen=True)
class PluginResult:
    """Outcome for one discovered module: ``status`` is ``"loaded"`` or ``"skipped"``; ``reason`` is a short,
    client-safe code (never an exception message) when skipped."""

    name: str
    status: str
    reason: str | None = None


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").strip().lower() == "production"


def _iter_routes(routes: Sequence[Any], prefix: str = ""):
    """Yield ``(full_path, route)``, descending into lazily included routers.

    Recent FastAPI/Starlette keep ``app.include_router(r, prefix=p)`` as one opaque ``_IncludedRouter`` (with
    ``original_router`` and ``include_context.prefix``) instead of copying its routes into ``app.routes``, so
    walking ``app.routes`` alone would miss every included route. Older versions copy eagerly (the path already
    carries the prefix); both shapes are handled.
    """
    for route in list(routes or []):
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original is not None and context is not None:
            yield from _iter_routes(original.routes, prefix + (getattr(context, "prefix", "") or ""))
            continue
        path = getattr(route, "path", None)
        if path is None:
            children = getattr(route, "routes", None)
            if children:
                yield from _iter_routes(children, prefix)
            continue
        yield prefix + path, route


def _route_keys(routes: Sequence[Any]) -> set[tuple[str, str]]:
    """``(path, method)`` for every route; websocket and mounted routes use the pseudo-methods WS / MOUNT."""
    keys: set[tuple[str, str]] = set()
    for path, route in _iter_routes(routes):
        methods = getattr(route, "methods", None)
        if methods:
            keys.update((path, m) for m in methods)
        elif type(route).__name__ == "APIWebSocketRoute":
            keys.add((path, "WS"))
        else:
            keys.add((path, "MOUNT"))
    return keys


def _log_failure(name: str, reason: str) -> None:
    level = logging.ERROR if _is_production() else logging.WARNING
    logger.log(level, "plugin %s skipped: %s", name, reason, exc_info=True)


def _load_one(app: FastAPI, package: str, name: str, dependencies: Sequence[Any] | None) -> PluginResult:
    full_name = f"{package}.{name}"
    try:
        module = importlib.import_module(full_name)
    except Exception:  # noqa: BLE001 -- a plugin must never take the API down
        _log_failure(name, "import failed")
        return PluginResult(name, "skipped", "import_failed")

    router = getattr(module, "router", None)
    setup = getattr(module, "setup", None)
    if router is not None and not isinstance(router, APIRouter):
        logger.log(
            logging.ERROR if _is_production() else logging.WARNING,
            "plugin %s skipped: router is not an APIRouter",
            name,
        )
        return PluginResult(name, "skipped", "invalid_router")
    if setup is not None and not callable(setup):
        logger.log(
            logging.ERROR if _is_production() else logging.WARNING, "plugin %s skipped: setup is not callable", name
        )
        return PluginResult(name, "skipped", "invalid_setup")
    if router is None and setup is None:
        logger.info("plugin module %s exports neither router nor setup; nothing to do", name)
        return PluginResult(name, "skipped", "no_entry_point")

    if router is not None:
        clash = _route_keys(router.routes) & _route_keys(app.routes)
        if clash:
            logger.log(
                logging.ERROR if _is_production() else logging.WARNING,
                "plugin %s skipped: router would re-register %d existing route(s), e.g. %s %s",
                name,
                len(clash),
                *sorted(clash)[0][::-1],
            )
            return PluginResult(name, "skipped", "route_collision")

    try:
        if setup is not None:
            setup(app)
        if router is not None:
            app.include_router(router, dependencies=list(dependencies) if dependencies else None)
    except Exception:  # noqa: BLE001
        _log_failure(name, "setup failed")
        return PluginResult(name, "skipped", "setup_failed")
    return PluginResult(name, "loaded")


def load_plugins(
    app: FastAPI,
    *,
    package: str = __name__,
    dependencies: Sequence[Any] | None = None,
) -> list[PluginResult]:
    """Import every module of ``package`` (default: this one) and wire its ``router`` / ``setup``.

    ``dependencies`` are applied to every plugin router (``api/main.py`` passes the core "general" limit set).
    ``package`` exists so tests can point the loader at fixture packages. Returns one result per module and
    stores them on ``app.state.plugin_results``.
    """
    existing = getattr(app.state, "plugin_results", None)
    if existing is not None:
        return list(existing)

    results: list[PluginResult] = []
    try:
        pkg = importlib.import_module(package)
        names = sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_"))
    except Exception:  # noqa: BLE001
        _log_failure(package, "plugin package could not be listed")
        names = []
    for name in names:
        results.append(_load_one(app, package, name, dependencies))

    app.state.plugin_results = tuple(results)
    loaded = [r.name for r in results if r.status == "loaded"]
    logger.info("plugins: %d loaded %s, %d skipped", len(loaded), loaded, len(results) - len(loaded))
    return results
