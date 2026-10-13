#!/usr/bin/env python3
"""Post-deploy smoke test (Task 8).

    python scripts/smoke_test.py --base-url https://api.example.org
    SMOKE_USERNAME=... SMOKE_PASSWORD=... python scripts/smoke_test.py --base-url http://localhost:8000

Checks, in order: ``/healthz``, ``/readyz``, login, ``GET /api/state``, one WebSocket frame from ``/ws/live``, and the
telemetry history endpoint. Exit status: 0 all passed, 1 a check failed, 2 usage error (no credentials, bad URL).

* Credentials come from ``--username`` and ``SMOKE_USERNAME`` / ``SMOKE_PASSWORD`` (prefer the environment: a
  password in argv ends up in shell history). Nothing secret is printed; tokens, tickets and bodies are never echoed.
* Standard library only, apart from ``websockets`` (already in requirements.txt) for the one WebSocket frame.
* The pure parts (URL handling, response checks, the runner) take plain values so tests need no server.
* Everything it reads is SIMULATED data; a pass says the deployment answers, not that any figure is right.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_WS_TIMEOUT_S = 20.0  # the live loop ticks every 3 s; this leaves room for a cold start
DEFAULT_SENSOR = "fac1.it_power_kw"  # fac<TELEMETRY_FACILITY_ID>.<measurand>; override with --sensor
HISTORY_WINDOW = timedelta(hours=1)


class SmokeError(Exception):
    """A check failed; the message is safe to print (no tokens, no bodies)."""


@dataclass(frozen=True)
class Response:
    status: int
    body: Any  # parsed JSON, or None when the body is not JSON


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


# --------------------------------------------------------------------------- pure helpers


def normalize_base_url(raw: str) -> str:
    """``https://host:port`` with no path, query or trailing slash. Raises SmokeError on anything else."""
    text = (raw or "").strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SmokeError("--base-url must be http(s)://host[:port]")
    if parts.username or parts.password:
        raise SmokeError("--base-url must not contain credentials")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def ws_url(base_url: str, query: str = "") -> str:
    """The ``/ws/live`` URL for a base URL (http -> ws, https -> wss), with an optional query string."""
    parts = urlsplit(normalize_base_url(base_url))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, parts.path + "/ws/live", query, ""))


def history_params(now: datetime, window: timedelta = HISTORY_WINDOW) -> dict[str, str]:
    """RFC 3339 ``from``/``to`` with an offset, as the history endpoint requires."""
    if now.tzinfo is None:
        raise SmokeError("history window needs an aware datetime")
    end = now.astimezone(timezone.utc)
    return {"from": (end - window).isoformat(), "to": end.isoformat(), "limit": "5", "quality": "any"}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_healthz(resp: Response) -> str:
    if resp.status != 200:
        raise SmokeError(f"/healthz returned HTTP {resp.status}")
    if not isinstance(resp.body, dict) or resp.body.get("status") != "ok":
        raise SmokeError("/healthz body is not {'status': 'ok', ...}")
    return "HTTP 200, status ok"


def check_readyz(resp: Response) -> str:
    """200 required. The body lists which check failed on a 503; only those names are reported."""
    if resp.status == 200:
        return "HTTP 200"
    failing = ""
    if isinstance(resp.body, dict):
        checks = resp.body.get("checks", resp.body)
        if isinstance(checks, dict):
            names = sorted(str(k) for k, v in checks.items() if v not in ("ok", "skipped") and isinstance(v, str))
            failing = f" (not ok: {', '.join(names)})" if names else ""
    raise SmokeError(f"/readyz returned HTTP {resp.status}{failing}")


def check_login(resp: Response) -> str:
    """Returns the role only; the tokens stay in the caller."""
    if resp.status != 200:
        raise SmokeError(f"login returned HTTP {resp.status}")
    body = resp.body
    if not isinstance(body, dict) or not isinstance(body.get("access_token"), str) or not body["access_token"]:
        raise SmokeError("login response has no access_token")
    return f"HTTP 200, role {body.get('role', 'unknown')}"


def check_state(resp: Response) -> str:
    if resp.status != 200:
        raise SmokeError(f"/api/state returned HTTP {resp.status}")
    body = resp.body
    if not isinstance(body, dict):
        raise SmokeError("/api/state body is not an object")
    missing = [k for k in ("pue", "total_power_kw") if not _is_number(body.get(k))]
    if missing:
        raise SmokeError(f"/api/state lacks numeric field(s): {', '.join(missing)}")
    return f"HTTP 200, pue {body['pue']:.3f}"


def check_ws_frame(text: str) -> str:
    """One live frame: JSON object, marked simulated, with a sequence number."""
    try:
        frame = json.loads(text)
    except (TypeError, ValueError):
        raise SmokeError("WebSocket frame is not JSON") from None
    if not isinstance(frame, dict):
        raise SmokeError("WebSocket frame is not an object")
    if frame.get("origin") != "simulated":
        raise SmokeError("WebSocket frame is not labelled origin=simulated")
    if not _is_number(frame.get("seq")):
        raise SmokeError("WebSocket frame has no seq")
    return f"frame seq {int(frame['seq'])}, origin simulated"


def check_history(resp: Response) -> str:
    """200 with an ``items`` list. An empty list passes (a fresh deployment has no history yet)."""
    if resp.status == 404:
        raise SmokeError("history sensor not found (facility sensors not seeded, or wrong --sensor)")
    if resp.status != 200:
        raise SmokeError(f"history endpoint returned HTTP {resp.status}")
    if not isinstance(resp.body, dict) or not isinstance(resp.body.get("items"), list):
        raise SmokeError("history response has no items list")
    return f"HTTP 200, {len(resp.body['items'])} item(s)"


def exit_code(results: Sequence[CheckResult]) -> int:
    return 0 if results and all(r.ok for r in results) else 1


def format_results(results: Sequence[CheckResult]) -> str:
    lines = [f"[{'PASS' if r.ok else 'FAIL'}] {r.name}: {r.detail}" for r in results]
    failed = sum(1 for r in results if not r.ok)
    lines.append(f"{len(results) - failed}/{len(results)} checks passed" + ("" if not failed else f", {failed} failed"))
    return "\n".join(lines)


# --------------------------------------------------------------------------- runner

HttpFn = Callable[[str, str, Optional[dict], Optional[dict]], Response]  # method, url, headers, json body
WsFn = Callable[[str, float], str]  # url, timeout -> first text frame


def run_smoke(
    base_url: str,
    username: str,
    password: str,
    *,
    http: HttpFn,
    ws: WsFn,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sensor: str = DEFAULT_SENSOR,
    ws_timeout: float = DEFAULT_WS_TIMEOUT_S,
) -> list[CheckResult]:
    """Run every check and return all results. A failed check never aborts the run, except that checks needing a
    token are reported as failed (not skipped silently) when login did not produce one."""
    base = normalize_base_url(base_url)
    results: list[CheckResult] = []
    token: dict[str, str | None] = {"value": None}

    def step(name: str, fn: Callable[[], str]) -> None:
        try:
            results.append(CheckResult(name, True, fn()))
        except SmokeError as exc:
            results.append(CheckResult(name, False, str(exc)))
        except Exception as exc:  # network errors etc.: type only, never the message (it can carry URLs)
            results.append(CheckResult(name, False, f"{type(exc).__name__}"))

    def authed() -> dict:
        if not token["value"]:
            raise SmokeError("no access token (login failed)")
        return {"Authorization": f"Bearer {token['value']}"}

    def login() -> str:
        resp = http("POST", f"{base}/auth/login", None, {"username": username, "password": password})
        detail = check_login(resp)
        token["value"] = resp.body["access_token"]
        return detail

    def websocket() -> str:
        headers = authed()
        ticket_resp = http("POST", f"{base}/auth/ws-ticket", headers, None)
        if ticket_resp.status == 200 and isinstance(ticket_resp.body, dict) and ticket_resp.body.get("ticket"):
            query = urllib.parse.urlencode({"ticket": ticket_resp.body["ticket"]})
            how = "ticket"
        else:  # older deployments, or no ticket store: the access token flow still works unless disabled
            query = urllib.parse.urlencode({"token": token["value"]})
            how = "token"
        return f"{check_ws_frame(ws(ws_url(base, query), ws_timeout))} (via {how})"

    def state() -> str:
        return check_state(http("GET", f"{base}/api/state", authed(), None))

    def history() -> str:
        query = urllib.parse.urlencode(history_params(now()))
        url = f"{base}/api/telemetry/sensors/{urllib.parse.quote(sensor, safe='')}/samples?{query}"
        return check_history(http("GET", url, authed(), None))

    step("healthz", lambda: check_healthz(http("GET", f"{base}/healthz", None, None)))
    step("readyz", lambda: check_readyz(http("GET", f"{base}/readyz", None, None)))
    step("login", login)
    step("state", state)
    step("websocket", websocket)
    step("history", history)
    return results


# --------------------------------------------------------------------------- real I/O


def make_http(timeout: float) -> HttpFn:
    def http(method: str, url: str, headers: Optional[dict], body: Optional[dict]) -> Response:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme checked by normalize_base_url)
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            parsed = None
        return Response(status, parsed)

    return http


def real_ws(url: str, timeout: float) -> str:
    try:
        from websockets.sync.client import connect
    except ImportError:
        raise SmokeError("the 'websockets' package (>=12) is required for the WebSocket check") from None
    try:
        with connect(url, open_timeout=timeout, close_timeout=2) as sock:
            frame = sock.recv(timeout=timeout)
    except TimeoutError:
        raise SmokeError(f"no WebSocket frame within {timeout:.0f}s") from None
    except Exception as exc:
        raise SmokeError(f"WebSocket failed ({type(exc).__name__})") from None
    return frame.decode("utf-8", "replace") if isinstance(frame, bytes) else frame


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke-test a deployed TwinGrid API (simulated data only).")
    p.add_argument("--base-url", required=True, help="http(s)://host[:port] of the API")
    p.add_argument("--username", default=os.getenv("SMOKE_USERNAME"), help="default: $SMOKE_USERNAME")
    p.add_argument("--password", default=os.getenv("SMOKE_PASSWORD"), help="default: $SMOKE_PASSWORD (preferred)")
    p.add_argument(
        "--sensor", default=DEFAULT_SENSOR, help=f"sensor external_id for the history check ({DEFAULT_SENSOR})"
    )
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="HTTP timeout in seconds")
    p.add_argument("--ws-timeout", type=float, default=DEFAULT_WS_TIMEOUT_S, help="seconds to wait for one frame")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not args.username or not args.password:
        print("error: set SMOKE_USERNAME and SMOKE_PASSWORD (or --username/--password)", file=sys.stderr)
        return 2
    try:
        results = run_smoke(
            args.base_url,
            args.username,
            args.password,
            http=make_http(args.timeout),
            ws=real_ws,
            sensor=args.sensor,
            ws_timeout=args.ws_timeout,
        )
    except SmokeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_results(results))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
