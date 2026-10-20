"""Route x role authorization matrix: loader, route discovery and cell helpers (QA-001, Task 3).

The matrix lives in ``tests/authz_matrix.d/*.yaml``. Every API task adds its own fragment ``T<n>.yaml``; the loader merges
all of them. A fragment looks like::

    routes:
      - {method: GET, path_template: /api/state, anonymous: "401", viewer: 2xx, operator: 2xx, admin: 2xx}
    websockets:
      - {path_template: /ws/live, anonymous: rejected}

Each cell value is a *status class* describing the AUTHORISATION outcome of a probe request:

``2xx``     access granted. The request got past authentication and authorisation; whatever follows (200, 404 for a
            made-up id, 422 for a probe body, 503 for a missing model) is the handler's business, so every status
            except 401, 403 and 405 counts.
``401``     refused: no usable credentials.        ``403``  refused: authenticated but not allowed.
``404``     the route answers 404 on purpose (feature switched off, e.g. the future demo session).
``422``     the probe is rejected by request validation after access was granted (use only where a route cannot be
            probed any other way).
``429``     rate limited.
``public``  needs no credentials. Same check as ``2xx``; it is a different word so a reader can see that open access is
            intended. ``anonymous`` may only be ``401`` or ``public``.

Probes never run business logic where that can be avoided: write requests carry the body ``[]`` (a JSON array is never a
valid request model, so FastAPI answers 422 only AFTER authentication and role checks have run), and the few handlers
with side effects are stubbed by the test module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

MATRIX_DIR = Path(__file__).resolve().parent / "authz_matrix.d"

ROLES: tuple[str, ...] = ("anonymous", "viewer", "operator", "admin")
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
STATUS_CLASSES = frozenset({"2xx", "401", "403", "404", "422", "429", "public"})

# What FastAPI answers when no Authorization header is sent. HTTPBearer(auto_error=True) answers 403 on FastAPI < 0.122
# and 401 on later versions; the lockfile pins 0.141.1. The one place to change if the pinned version ever differs.
MISSING_CREDENTIALS_STATUS = 401

# Framework-generated documentation routes. They carry no application data and are not part of the matrix.
DOCS_ALLOW_LIST = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

# Write methods that an anonymous caller may reach, and why. Anything else must answer 401 to anonymous.
PUBLIC_WRITE_ALLOW_LIST: dict[str, str] = {
    "/auth/login": "obtains a session; the credential is in the body",
    "/auth/refresh": "exchanges a refresh token; the token is the credential",
    "/auth/logout": "revokes a refresh token; possession of the token is the credential",
    "/auth/register": "environment-dependent (ALLOW_PUBLIC_REGISTRATION / X-Admin-Key); the handler enforces it",
    "/api/client-errors": "browser error reports cannot send headers; guarded by a report key in the handler",
    # Future public routes: Tasks 9 and 13 add their own fragments; listing the prefixes here keeps this file stable.
    "/api/access-requests": "(Task 9) visitor access requests; prefix match",
    "/auth/demo-session": "(Task 13) server-issued read-only demo token",
}

# Write methods a plain `viewer` token may reach, and why. Everything else must be refused (403) for viewers.
VIEWER_WRITE_ALLOW_LIST: dict[str, str] = {
    "/api/runs": "DECISION (playbook section 5): a normal viewer may submit a scenario run (existing run caps apply); "
    "demo tokens are denied by Task 13 with 403 demo_read_only",
    "/auth/ws-ticket": "issues a single-use WebSocket ticket for the caller's own session; changes no facility data",
}


@dataclass(frozen=True)
class DiscoveredRoute:
    method: str  # HTTP method, or "WEBSOCKET"
    path_template: str
    has_body: bool  # FastAPI declares a request body model for this route

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path_template)


# ------------------------------------------------------------------------------------------------ loading


class MatrixError(ValueError):
    """A fragment is malformed. The message names the file and the entry."""


def _norm(value: Any) -> str:
    return str(value).strip()


def _load_one(path: Path) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, dict[str, str]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not set(data) <= {"routes", "websockets"}:
        raise MatrixError(f"{path.name}: top level may only contain 'routes' and 'websockets'")
    routes: dict[tuple[str, str], dict[str, str]] = {}
    for i, entry in enumerate(data.get("routes") or []):
        where = f"{path.name} routes[{i}]"
        if not isinstance(entry, dict):
            raise MatrixError(f"{where}: must be a mapping")
        allowed = {"method", "path_template", "demo", *ROLES}
        extra = set(entry) - allowed
        if extra:
            raise MatrixError(f"{where}: unknown keys {sorted(extra)}")
        missing = [k for k in ("method", "path_template", *ROLES) if k not in entry]
        if missing:
            raise MatrixError(f"{where}: missing keys {missing}")
        method = _norm(entry["method"]).upper()
        template = _norm(entry["path_template"])
        cells = {role: _norm(entry[role]) for role in ROLES}
        if "demo" in entry:
            cells["demo"] = _norm(entry["demo"])
        for role, value in cells.items():
            if value not in STATUS_CLASSES:
                raise MatrixError(
                    f"{where} {method} {template}: {role}={value!r} is not one of {sorted(STATUS_CLASSES)}"
                )
        if cells["anonymous"] not in {"401", "public"}:
            raise MatrixError(f"{where} {method} {template}: anonymous must be '401' or 'public'")
        if (method, template) in routes:
            raise MatrixError(f"{where}: {method} {template} is declared twice in one file")
        routes[(method, template)] = cells
    sockets: dict[str, dict[str, str]] = {}
    for i, entry in enumerate(data.get("websockets") or []):
        where = f"{path.name} websockets[{i}]"
        if not isinstance(entry, dict) or set(entry) != {"path_template", "anonymous"}:
            raise MatrixError(f"{where}: needs exactly path_template and anonymous")
        if _norm(entry["anonymous"]) != "rejected":
            raise MatrixError(f"{where}: anonymous must be 'rejected'")
        sockets[_norm(entry["path_template"])] = {"anonymous": "rejected"}
    return routes, sockets


def load_fragments(
    directory: Path = MATRIX_DIR,
) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, dict[str, str]]]:
    """Merge every ``*.yaml`` fragment. A route declared in two files is an error (one owner per route)."""
    merged: dict[tuple[str, str], dict[str, str]] = {}
    owner: dict[tuple[str, str], str] = {}
    sockets: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("*.yaml")):
        routes, socks = _load_one(path)
        for key, cells in routes.items():
            if key in merged:
                raise MatrixError(f"{key[0]} {key[1]} is declared in both {owner[key]} and {path.name}")
            merged[key] = cells
            owner[key] = path.name
        for template, cells in socks.items():
            if template in sockets:
                raise MatrixError(f"websocket {template} is declared twice")
            sockets[template] = cells
    return merged, sockets


# ------------------------------------------------------------------------------------------------ discovery


def discover(app: Any) -> tuple[list[DiscoveredRoute], list[str]]:
    """Every HTTP route and WebSocket the app serves, plus a list of routes this harness does not understand.

    Walks ``app.routes`` and descends into lazily included routers (the same walk ``api.plugins`` uses to detect
    collisions), so plugin and core routes are all seen, including ones with ``include_in_schema=False``.
    """
    from fastapi.routing import APIRoute, APIWebSocketRoute

    from api.plugins import _iter_routes

    found: list[DiscoveredRoute] = []
    unknown: list[str] = []
    for path, route in _iter_routes(app.routes):
        if isinstance(route, APIRoute):
            has_body = getattr(route, "body_field", None) is not None
            for method in sorted(route.methods or ()):
                if method in {"HEAD", "OPTIONS"}:
                    continue
                found.append(DiscoveredRoute(method, path, has_body))
        elif isinstance(route, APIWebSocketRoute):
            found.append(DiscoveredRoute("WEBSOCKET", path, False))
        elif path in DOCS_ALLOW_LIST:
            continue
        else:
            unknown.append(f"{type(route).__name__} {path}")
    return sorted(found, key=lambda r: r.key), unknown


def diff_routes(
    discovered: Iterable[DiscoveredRoute],
    declared_http: Iterable[tuple[str, str]],
    declared_ws: Iterable[str],
) -> tuple[list[str], list[str]]:
    """(undeclared, stale): served without an expectation / an expectation for a route that is gone."""
    served = {r.key for r in discovered}
    wanted = set(declared_http) | {("WEBSOCKET", p) for p in declared_ws}
    undeclared = sorted(f"{m} {p}" for m, p in served - wanted)
    stale = sorted(f"{m} {p}" for m, p in wanted - served)
    return undeclared, stale


# ------------------------------------------------------------------------------------------------ probing

_PARAM = re.compile(r"\{([^}:]+)(?::[^}]*)?\}")
_STRING_IDS = {"run_id", "job_id", "external_id", "evaluation_id"}


def sample_path(template: str) -> str:
    """Fill path parameters with values that cannot match a real record, so a handler that does run answers 404/422."""

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "wid":
            return "0123456789abcdef"  # matches the webhook id pattern; not registered, so 404
        if name == "hours":
            return "1"
        if name in _STRING_IDS:
            return "authz-probe"
        if name.endswith("id"):
            return "1"
        return "authz-probe"

    return _PARAM.sub(fill, template)


def status_matches(expected: str, status: int) -> bool:
    if expected in {"2xx", "public"}:
        return status not in {401, 403, 405}
    return status == int(expected)


def path_allowed(path: str, allow_list: Iterable[str]) -> bool:
    return any(path == a or path.startswith(a.rstrip("/") + "/") or path.startswith(a + "?") for a in allow_list)
