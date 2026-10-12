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


def _walk(routes: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Yield ``(full_path, route)`` for every HTTP route under ``routes``, descending into nested routers."""
    for route in list(routes or []):
        path = getattr(route, "path", "") or ""
        if getattr(route, "dependant", None) is not None and getattr(route, "methods", None):
            yield (path if path.startswith(prefix) else prefix + path), route
        children = getattr(route, "routes", None)
        if children and getattr(route, "dependant", None) is None:
            yield from _walk(children, prefix + path if not path.startswith(prefix) else path)


def _dependency_calls(dependant: Any) -> list[Any]:
    found: list[Any] = []
    for sub in getattr(dependant, "dependencies", None) or []:
        if getattr(sub, "call", None) is not None:
            found.append(sub.call)
        found.extend(_dependency_calls(sub))
    return found


def _all_calls(route: Any) -> list[Any]:
    declared = [getattr(d, "dependency", None) for d in getattr(route, "dependencies", None) or []]
    return [c for c in declared if c is not None] + _dependency_calls(route.dependant)


def _limit(path: str, route: Any) -> str:
    if path in config.HTTP_LIMIT_EXEMPT_PATHS:
        return "exempt (probe)"
    scopes: list[str] = []
    for call in _all_calls(route):
        scope = getattr(call, "http_limit_scope", None)
        if scope and scope not in scopes:
            scopes.append(scope)
    return " + ".join(scopes) if scopes else "NONE"


def _auth(route: Any) -> str:
    names = {getattr(c, "__name__", "") for c in _all_calls(route)}
    if "require_operator" in names:
        return "operator"
    if "get_current_user" in names:
        return "user"
    return "public"


def rows(app: Any) -> list[dict[str, str]]:
    """The route table of ``app`` (HTTP routes only), sorted by path then method."""
    table: list[dict[str, str]] = []
    for path, route in _walk(getattr(app, "routes", [])):
        limit, auth = _limit(path, route), _auth(route)
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
