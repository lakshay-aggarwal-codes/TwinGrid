"""T14 route-controls table: which request-rate limit and which auth every HTTP route carries.

``rows(app)`` is imported by tests/api/test_error_contract.py (it is the executable form of the T14
route table), and the file can be run directly to print the table::

    python reports/postT9/T14_route_controls.py

Each row is ``{"methods": "POST", "path": "/api/optimize", "limit": "general + optimize", "auth": "operator"}``,
one row per HTTP method:

* ``limit`` is the ``http_limit`` scopes in dependency order joined by `` + ``; ``NONE`` when the route has
  none; ``exempt (probe)`` for the infrastructure probes in ``config.HTTP_LIMIT_EXEMPT_PATHS``.
* ``auth`` is ``operator`` (``require_operator``), ``user`` (``get_current_user``) or ``public``.

WebSocket routes are not HTTP routes and are not listed (their caps live in ConnectionManager).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute  # noqa: E402

from api import config  # noqa: E402

_SKIPPED_METHODS = {"HEAD", "OPTIONS"}


def _calls(dependant: Any) -> list[Any]:
    """Every dependency callable under ``dependant`` (outermost first, depth-first)."""
    found: list[Any] = []
    for sub in dependant.dependencies:
        if sub.call is not None:
            found.append(sub.call)
        found.extend(_calls(sub))
    return found


def _limit(route: APIRoute) -> str:
    if route.path in config.HTTP_LIMIT_EXEMPT_PATHS:
        return "exempt (probe)"
    scopes = [s for s in (getattr(c, "http_limit_scope", None) for c in _calls(route.dependant)) if s]
    return " + ".join(scopes) if scopes else "NONE"


def _auth(route: APIRoute) -> str:
    names = {getattr(c, "__name__", "") for c in _calls(route.dependant)}
    if "require_operator" in names:
        return "operator"
    if "get_current_user" in names:
        return "user"
    return "public"


def rows(app: Any) -> list[dict[str, str]]:
    """The route table of ``app`` (HTTP routes only), sorted by path then method."""
    table: list[dict[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        limit, auth = _limit(route), _auth(route)
        for method in sorted(route.methods - _SKIPPED_METHODS):
            table.append({"methods": method, "path": route.path, "limit": limit, "auth": auth})
    return sorted(table, key=lambda r: (r["path"], r["methods"]))


if __name__ == "__main__":
    from api.main import app

    for row in rows(app):
        print(f'{row["methods"]:<7} {row["path"]:<45} {row["auth"]:<9} {row["limit"]}')
