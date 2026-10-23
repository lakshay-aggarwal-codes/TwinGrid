"""T14 route-controls table: which request-rate limit and which auth every HTTP route carries.

``rows(app)`` is imported by tests/api/test_error_contract.py (it is the executable form of the T14
route table), and the file can be run directly to print the table::

    python reports/postT9/T14_route_controls.py

Each row is ``{"methods": "POST", "path": "/api/optimize", "limit": "general + optimize", "auth": "operator"}``,
one row per HTTP method:

* ``limit`` is the ``http_limit`` scopes in dependency order joined by `` + ``; ``NONE`` when the route has
  none; ``exempt (probe)`` for the infrastructure probes in ``config.HTTP_LIMIT_EXEMPT_PATHS``.
* ``auth`` is ``operator`` (``require_operator``), ``user`` (``get_current_user``) or ``public``.

Routes are found by shape, not by class: anything with ``methods``, ``path`` and a FastAPI ``dependant`` is an
HTTP route, and anything with ``routes`` is walked into. WebSocket routes have no ``methods`` and are skipped
(their caps live in ConnectionManager).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import config  # noqa: E402

_SKIPPED_METHODS = {"HEAD", "OPTIONS"}


def _walk(routes: Any, prefix: str = "", inherited: tuple[Any, ...] = ()) -> Iterator[tuple[str, Any, tuple[Any, ...]]]:
    """Yield ``(full_path, route, inherited_dependencies)`` for every HTTP route under ``routes``.

    Recent FastAPI/Starlette keep ``app.include_router(r, prefix=p, dependencies=d)`` as one opaque
    ``_IncludedRouter`` whose ``include_context`` holds the prefix and ``dependencies`` (the general rate limit is
    attached that way in api/main.py and api/plugins), and does NOT copy them onto each route's ``dependant``. So the
    descent carries those dependencies down and ``_all_calls`` adds them back. Older versions copy eagerly (the path
    already carries the prefix, the dependencies are already on the route); the same code handles both. A mount
    (child ``routes`` and no ``dependant``) is walked with its path as the prefix.
    """
    for route in list(routes or []):
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original is not None and context is not None:
            deps = inherited + tuple(getattr(context, "dependencies", None) or ())
            yield from _walk(original.routes, prefix + (getattr(context, "prefix", "") or ""), deps)
            continue
        path = getattr(route, "path", "") or ""
        if getattr(route, "dependant", None) is not None and getattr(route, "methods", None):
            yield (path if path.startswith(prefix) else prefix + path), route, inherited
            continue
        children = getattr(route, "routes", None)
        if children and getattr(route, "dependant", None) is None:
            yield from _walk(children, prefix + path if not path.startswith(prefix) else path, inherited)


def _dependency_calls(dependant: Any) -> list[Any]:
    found: list[Any] = []
    for sub in getattr(dependant, "dependencies", None) or []:
        if getattr(sub, "call", None) is not None:
            found.append(sub.call)
        found.extend(_dependency_calls(sub))
    return found


def _all_calls(route: Any, inherited: tuple[Any, ...] = ()) -> list[Any]:
    declared = [getattr(d, "dependency", None) for d in (*inherited, *(getattr(route, "dependencies", None) or []))]
    return [c for c in declared if c is not None] + _dependency_calls(route.dependant)


def _limit(path: str, route: Any, inherited: tuple[Any, ...] = ()) -> str:
    if path in config.HTTP_LIMIT_EXEMPT_PATHS:
        return "exempt (probe)"
    scopes: list[str] = []
    for call in _all_calls(route, inherited):
        scope = getattr(call, "http_limit_scope", None)
        if scope and scope not in scopes:
            scopes.append(scope)
    return " + ".join(scopes) if scopes else "NONE"


def _auth(route: Any, inherited: tuple[Any, ...] = ()) -> str:
    names = {getattr(c, "__name__", "") for c in _all_calls(route, inherited)}
    if "require_operator" in names:
        return "operator"
    if "get_current_user" in names:
        return "user"
    return "public"


def rows(app: Any) -> list[dict[str, str]]:
    """The route table of ``app`` (HTTP routes only), sorted by path then method."""
    table: list[dict[str, str]] = []
    for path, route, inherited in _walk(getattr(app, "routes", [])):
        limit, auth = _limit(path, route, inherited), _auth(route, inherited)
        for method in sorted(set(route.methods) - _SKIPPED_METHODS):
            table.append({"methods": method, "path": path, "limit": limit, "auth": auth})
    return sorted(table, key=lambda r: (r["path"], r["methods"]))


if __name__ == "__main__":
    from api.main import app

    table = rows(app)
    for row in table:
        print(f'{row["methods"]:<7} {row["path"]:<45} {row["auth"]:<9} {row["limit"]}')
    if not table:  # diagnostic: what does the app expose?
        print("no HTTP routes found; app.routes types:", sorted({type(r).__name__ for r in app.routes}))
