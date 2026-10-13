"""Generate the committed API reference: ``docs/api/openapi.json`` and ``docs/api/README.md``.

Usage (from the repository root)::

    python scripts/gen_api_reference.py            # (re)write both files
    python scripts/gen_api_reference.py --check    # exit 1 if the committed files are stale

Environment: importing ``api.main`` needs a JWT secret, so this script sets, ONLY if not already set,
``JWT_SECRET_KEY`` to a documented placeholder, and forces ``ENVIRONMENT=development`` (production would demand
CORS origins and more). Nothing is started: no lifespan, no database connection, no network. The placeholder is
never written to the output.

Output is deterministic: sorted keys, 2-space indent, LF line endings, trailing newline, no timestamps.
The OpenAPI document is produced by FastAPI itself (``app.openapi()``); the README adds the facts OpenAPI
cannot express (role required, rate-limit class) by inspecting the live route dependencies.

Endpoints added by later tasks (``api/plugins/*``) appear after this script is re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = ROOT / "docs" / "api" / "openapi.json"
README_PATH = ROOT / "docs" / "api" / "README.md"

_PLACEHOLDER_SECRET = "gen-api-reference-placeholder-not-a-secret"
_HTTP_METHODS = ("get", "put", "post", "delete", "patch", "options", "head")


def _prepare_environment() -> None:
    os.environ.setdefault("JWT_SECRET_KEY", _PLACEHOLDER_SECRET)
    os.environ["ENVIRONMENT"] = "development"
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _load_app():
    _prepare_environment()
    from api.main import app  # noqa: PLC0415 - must come after the environment is prepared

    return app


# ----------------------------------------------------------------------------- route inspection


def _iter_api_routes(routes: Any, prefix: str = ""):
    """Yield ``(full_path, route)`` for every HTTP route, descending into lazily included routers.

    Same two shapes as ``api.plugins._iter_routes``: newer FastAPI keeps ``include_router`` as one opaque
    entry with ``original_router`` / ``include_context``; older versions copy routes eagerly.
    """
    for route in list(routes or []):
        original = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if original is not None and context is not None:
            yield from _iter_api_routes(original.routes, prefix + (getattr(context, "prefix", "") or ""))
            continue
        path = getattr(route, "path", None)
        if path is None:
            children = getattr(route, "routes", None)
            if children:
                yield from _iter_api_routes(children, prefix)
            continue
        yield prefix + path, route


def _dependency_calls(dependant: Any) -> list[Any]:
    calls: list[Any] = []
    for sub in getattr(dependant, "dependencies", None) or []:
        call = getattr(sub, "call", None)
        if call is not None:
            calls.append(call)
        calls.extend(_dependency_calls(sub))
    return calls


def _slowapi_limit_text(endpoint: Any) -> str | None:
    """Best effort: the per-IP slowapi limit declared with ``@limiter.limit`` (used by /auth/*)."""
    try:
        from api.rate_limit import limiter  # noqa: PLC0415

        key = f"{endpoint.__module__}.{endpoint.__name__}"
        limits = getattr(limiter, "_route_limits", {}).get(key) or []
        texts = sorted({str(getattr(item, "limit", item)) for item in limits})
        return ", ".join(texts) or None
    except Exception:  # noqa: BLE001 - documentation only; never fail the generator for this
        return None


def route_facts(app: Any) -> dict[tuple[str, str], dict[str, str]]:
    """``(path, METHOD)`` -> ``{"role": ..., "rate": ...}`` read from the live route dependencies."""
    from api import config  # noqa: PLC0415
    from api.auth import require_operator  # noqa: PLC0415

    facts: dict[tuple[str, str], dict[str, str]] = {}
    for path, route in _iter_api_routes(app.routes):
        methods = getattr(route, "methods", None)
        dependant = getattr(route, "dependant", None)
        if not methods or dependant is None:
            continue  # websocket / mount entries are documented by hand in the README
        calls = _dependency_calls(dependant)
        scopes = sorted({getattr(c, "http_limit_scope") for c in calls if hasattr(c, "http_limit_scope")})
        if path in config.HTTP_LIMIT_EXEMPT_PATHS:
            rate = "exempt (probe)"
        else:
            # api/main.py applies the "general" window to every HTTP router, plugin routers included.
            names = ["general"] + [s for s in scopes if s != "general"]
            rate = ", ".join(names)
            slow = _slowapi_limit_text(getattr(route, "endpoint", None))
            if slow:
                rate += f" + per-IP {slow}"
        role = "operator" if require_operator in calls else ""
        for method in sorted(methods):
            facts[(path, method)] = {"role": role, "rate": rate}
    return facts


# ----------------------------------------------------------------------------- rendering


def render_openapi(app: Any) -> str:
    spec = app.openapi()
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _cell(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _auth_text(operation: dict[str, Any], spec: dict[str, Any], role: str) -> str:
    security = operation.get("security", spec.get("security"))
    if not security:
        return "none"
    return f"bearer, role `{role}`" if role else "bearer (any valid user)"


def render_readme(app: Any, spec: dict[str, Any]) -> str:
    from api import config  # noqa: PLC0415

    facts = route_facts(app)
    info = spec.get("info", {})
    rows: list[tuple[str, str, str, str, str, str]] = []
    for path, item in sorted(spec.get("paths", {}).items()):
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not op:
                continue
            fact = facts.get((path, method.upper()), {"role": "", "rate": "NOT DETERMINED"})
            tags = ", ".join(op.get("tags", [])) or "-"
            summary = op.get("summary") or op.get("operationId") or ""
            rows.append(
                (
                    method.upper(),
                    path,
                    _auth_text(op, spec, fact["role"]),
                    fact["rate"],
                    tags,
                    summary,
                )
            )

    lines: list[str] = [
        "# TwinGrid API reference",
        "",
        "<!-- GENERATED by scripts/gen_api_reference.py - do not edit by hand. -->",
        "",
        f"**{_cell(info.get('title'))}** - version `{_cell(info.get('version'))}`. {_cell(info.get('description'))}.",
        "The data behind these endpoints is **simulated**; nothing here is a measurement from a real facility.",
        "",
        "Machine-readable contract: [`openapi.json`](openapi.json) (OpenAPI "
        f"{_cell(spec.get('openapi'))}). The running API also serves it at `/openapi.json`, with Swagger UI "
        "at `/docs` and ReDoc at `/redoc`.",
        "",
        "Regenerate after any route change: `python scripts/gen_api_reference.py`. "
        "A test (`tests/test_task9_api_reference.py`) fails when these files are stale.",
        "",
        "## Authentication",
        "",
        "- `POST /auth/login` returns an access token (short-lived JWT) and a refresh token; "
        "send the access token as `Authorization: Bearer <token>`.",
        "- `POST /auth/refresh` rotates the refresh token; `POST /auth/logout` revokes it.",
        "- Roles: `viewer` (default) and `operator`. Endpoints marked `role operator` answer 403 to a viewer.",
        "- Routes with auth `none` need no token (login, register, probes).",
        "- `/ws/live` (WebSocket, not part of OpenAPI) accepts a one-time ticket from `POST /auth/ws-ticket`; "
        "a `?token=` query token is accepted only while `WS_ALLOW_QUERY_TOKEN` is not `false`.",
        "- See `SECURITY.md` for the token lifecycle.",
        "",
        "## Rate-limit classes",
        "",
        "Every HTTP route is in the `general` window; a route that names a class is also in that class. "
        "Windows are sliding, per user (valid token) or per client IP, in memory per process. "
        "Over the limit -> `429` with `Retry-After`. Probes (`/livez`, `/readyz`, `/healthz`) are exempt. "
        "`/auth/*` routes additionally have a per-IP limit from `slowapi`. Defaults below; each is "
        "overridable by the environment variable shown.",
        "",
        "| Class | Default | Environment variable |",
        "|---|---|---|",
    ]
    for scope in sorted(config.RATE_LIMIT_DEFAULTS):
        env_name, default = config.RATE_LIMIT_DEFAULTS[scope]
        lines.append(f"| `{scope}` | {_cell(default)} | `{env_name}` |")

    lines += [
        "",
        "Compute-heavy routes are also bounded in concurrency and wall-clock time: "
        "`429 compute_busy` when too many run at once, `504 compute_timeout` when one runs too long.",
        "",
        "## Error shape",
        "",
        "Every failure is `application/problem+json`:",
        "",
        "```json",
        "{",
        '  "type": "urn:twingrid:error:<code>",',
        '  "title": "Not Found",',
        '  "status": 404,',
        '  "detail": "<one-line human message, always a string>",',
        '  "instance": "/request/path",',
        '  "request_id": "<same value as the X-Request-ID response header>",',
        '  "errors": [{"loc": ["query", "hours"], "msg": "...", "type": "..."}]',
        "}",
        "```",
        "",
        "- `errors` appears on `422` only; each item is `{loc, msg, type}` (the caller's raw input is never echoed).",
        "- `instance` is the path only, never the query string.",
        "- An unhandled server error is a generic `500` (`Internal server error`); "
        "tracebacks, file paths and SQL never reach the client.",
        "",
        "## Endpoints",
        "",
        f"{len(rows)} HTTP operations. Parameter and response schemas: see [`openapi.json`](openapi.json).",
        "",
        "| Method | Path | Auth | Rate class | Tags | Summary |",
        "|---|---|---|---|---|---|",
    ]
    for method, path, auth, rate, tags, summary in rows:
        lines.append(
            f"| {method} | `{_cell(path)}` | {_cell(auth)} | {_cell(rate)} | {_cell(tags)} | {_cell(summary)} |"
        )
    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- entry points


def generate() -> tuple[str, str]:
    """Return ``(openapi_json_text, readme_text)`` built in memory from the current code."""
    app = _load_app()
    openapi_text = render_openapi(app)
    readme_text = render_readme(app, json.loads(openapi_text))
    return openapi_text, readme_text


def _read(path: Path) -> str | None:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n") if path.exists() else None


def stale_files() -> list[str]:
    """Repo-relative paths whose committed content differs from a fresh generation (or is missing)."""
    openapi_text, readme_text = generate()
    stale = []
    for path, fresh in ((OPENAPI_PATH, openapi_text), (README_PATH, readme_text)):
        if _read(path) != fresh:
            stale.append(path.relative_to(ROOT).as_posix())
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 if the committed files are stale")
    args = parser.parse_args(argv)

    if args.check:
        stale = stale_files()
        for name in stale:
            print(f"STALE: {name} (run: python scripts/gen_api_reference.py)")
        if not stale:
            print("API reference is up to date.")
        return 1 if stale else 0

    openapi_text, readme_text = generate()
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_bytes(openapi_text.encode("utf-8"))
    README_PATH.write_bytes(readme_text.encode("utf-8"))
    print(f"wrote {OPENAPI_PATH.relative_to(ROOT).as_posix()} and {README_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
