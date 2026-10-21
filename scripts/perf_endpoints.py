#!/usr/bin/env python3
"""Task 29: per-endpoint API latency (p50/p95/p99), error rate and payload size against a RUNNING server. MEASURES ONLY.

    $env:TWINGRID_USERNAME="..."; $env:TWINGRID_PASSWORD="..."
    python scripts\\perf_endpoints.py --base-url http://localhost:8000 --out reports\\perf\\2026-10\\api_endpoints.json

Endpoints: state, whatif, history (stored samples, one page of up to 5000), alerts inbox, copilot (rule-based question),
access-request create and status. Standard library only. Nothing is estimated: an endpoint that cannot run is recorded
as ``skipped``/``failed`` WITH the reason.

Rules: time = first byte request to last byte read, ``time.perf_counter``, keep-alive, identity encoding. A 429 is counted
(``rate_limited``) and NEVER timed or counted as an error; run the server with HTTP_LIMITS_ENABLED=false for latency work
and say so with ``--limits`` (it is recorded, not detected). Error rate = (non-2xx non-429 responses + connection errors)
/ attempts. Access-request create is capped at ``--create-requests`` (default 5, the per-IP limit when limits are on) so
it does not fill the table.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

SCHEMA = "twingrid-perf-endpoints/1"


def percentile(sorted_values: list[float], q: float) -> float:
    """Nearest rank."""
    rank = max(1, math.ceil(q / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def summarise(times: list[float], sizes: list[int], attempts: int, rate_limited: int, errors: int) -> dict[str, Any]:
    out: dict[str, Any] = {"attempts": attempts, "timed": len(times), "rate_limited": rate_limited, "errors": errors}
    out["error_rate"] = round(errors / attempts, 4) if attempts else None
    if times:
        s = sorted(times)
        out.update(
            {
                "p50_ms": round(percentile(s, 50) * 1000, 3),
                "p95_ms": round(percentile(s, 95) * 1000, 3),
                "p99_ms": round(percentile(s, 99) * 1000, 3),
                "min_ms": round(s[0] * 1000, 3),
                "max_ms": round(s[-1] * 1000, 3),
                "mean_ms": round(statistics.fmean(s) * 1000, 3),
                "payload_bytes_median": int(statistics.median(sizes)) if sizes else None,
            }
        )
    if 0 < len(times) < 100:
        out["note"] = "fewer than 100 timed samples: p99 is the maximum, not a stable estimate"
    return out


class Client:
    def __init__(self, base_url: str) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SystemExit(f"--base-url must be http(s)://host[:port], got {base_url!r}")
        self._cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        self._host, self._port = parts.hostname, parts.port
        self.token: str | None = None
        self._conn = self._cls(self._host, self._port, timeout=60)

    def request(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None):
        h = {"Accept": "application/json", "Accept-Encoding": "identity", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        start = time.perf_counter()
        try:
            self._conn.request(method, path, body=data, headers=h)
            resp = self._conn.getresponse()
            payload = resp.read()
        except (OSError, http.client.HTTPException):
            self._conn.close()
            self._conn = self._cls(self._host, self._port, timeout=60)
            raise
        return resp.status, payload, time.perf_counter() - start


def run_endpoint(
    base_url: str,
    token: str | None,
    make: Callable[[int], tuple[str, str, Any, dict[str, str]]],
    n: int,
    warmup: int,
    concurrency: int,
) -> dict[str, Any]:
    lock = threading.Lock()
    times: list[float] = []
    sizes: list[int] = []
    counts = {"attempts": 0, "rl": 0, "err": 0}
    counter = iter(range(-warmup, n))

    def worker() -> None:
        c = Client(base_url)
        c.token = token
        while True:
            with lock:
                i = next(counter, None)
            if i is None:
                return
            method, path, body, headers = make(i)
            try:
                status, payload, dt = c.request(method, path, body, headers)
            except (OSError, http.client.HTTPException):
                status, payload, dt = -1, b"", 0.0
            if i < 0:
                continue  # warm-up: not recorded
            with lock:
                counts["attempts"] += 1
                if status == 429:
                    counts["rl"] += 1
                elif 200 <= status < 300:
                    times.append(dt)
                    sizes.append(len(payload))
                else:
                    counts["err"] += 1

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    wall = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = summarise(times, sizes, counts["attempts"], counts["rl"], counts["err"])
    out["concurrency"] = concurrency
    out["throughput_rps"] = round(len(times) / (time.perf_counter() - wall), 2)
    return out


def _git(*args: str) -> str | None:
    try:
        return (
            subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
            or None
        )
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--create-requests", type=int, default=5)
    ap.add_argument("--history-stream", default="live")
    ap.add_argument("--history-measurand", default="it_power_kw")
    ap.add_argument("--history-hours", type=int, default=24)
    ap.add_argument("--limits", default="not stated", help="record HTTP_LIMITS_ENABLED of the server, e.g. false")
    ap.add_argument("--only", default="", help="comma list of endpoint names")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.requests < 1 or a.concurrency < 1:
        ap.error("--requests and --concurrency must be >= 1")

    user, pw = os.environ.get("TWINGRID_USERNAME"), os.environ.get("TWINGRID_PASSWORD")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "client_runs_on_same_host_as_server": "unknown: state it in FE-20.md",
            "commit": _git("rev-parse", "--short", "HEAD"),
            "base_url": a.base_url,
            "http_limits_enabled": a.limits,
        },
        "protocol": {"requests": a.requests, "warmup": a.warmup, "concurrency": a.concurrency},
        "endpoints": {},
    }

    boot = Client(a.base_url)
    try:
        status, _, _ = boot.request("GET", "/healthz")
    except OSError as exc:
        raise SystemExit(f"cannot reach {a.base_url}: {exc}") from exc
    if status >= 500:
        raise SystemExit(f"/healthz returned {status}")
    token = None
    if user and pw:
        status, payload, _ = boot.request("POST", "/auth/login", {"username": user, "password": pw})
        if status != 200:
            raise SystemExit(f"sign-in failed with HTTP {status} (credentials are not echoed)")
        token = json.loads(payload)["access_token"]
        boot.token = token
    result["environment"]["authenticated"] = token is not None

    specs: dict[str, Callable[[int], tuple[str, str, Any, dict[str, str]]]] = {}
    skipped: dict[str, str] = {}
    specs["state"] = lambda i: ("GET", "/api/state", None, {})
    specs["whatif"] = lambda i: ("GET", "/api/whatif", None, {})
    specs["alerts_inbox"] = lambda i: ("GET", "/api/alerts/inbox", None, {})
    specs["copilot_ask_rule_based"] = lambda i: (
        "POST",
        "/api/copilot/ask",
        {"question": "Why is the PUE where it is?"},
        {},
    )

    status, payload, _ = boot.request("GET", "/api/facility")
    if status == 200 and isinstance(json.loads(payload).get("id"), int):
        sensor = f"fac{json.loads(payload)['id']}.{a.history_measurand}"
        end = datetime.now(timezone.utc).replace(microsecond=0)
        frm = (end - timedelta(hours=a.history_hours)).isoformat().replace("+00:00", "Z")
        to = end.isoformat().replace("+00:00", "Z")
        path = (
            f"/api/telemetry/sensors/{quote(sensor)}/samples?from={quote(frm)}&to={quote(to)}"
            f"&stream={quote(a.history_stream)}&limit=5000"
        )
        specs["history_samples_5000"] = lambda i, p=path: ("GET", p, None, {})
        s, body, _ = boot.request("GET", path)
        result["history_probe"] = {
            "sensor": sensor,
            "stream": a.history_stream,
            "http_status": s,
            "rows_in_first_page": len(json.loads(body).get("items", [])) if s == 200 else None,
            "has_more": (json.loads(body).get("next_cursor") is not None) if s == 200 else None,
        }
    else:
        skipped["history_samples_5000"] = f"/api/facility returned HTTP {status} or no integer id"

    only = {x.strip() for x in a.only.split(",") if x.strip()}
    for name, make in specs.items():
        if only and name not in only:
            continue
        result["endpoints"][name] = run_endpoint(a.base_url, token, make, a.requests, a.warmup, a.concurrency)

    if not only or {"access_request_create", "access_request_status"} & only:
        tag = uuid.uuid4().hex[:8]
        created: list[tuple[str, str]] = []

        def make_create(i: int):
            n = i + a.warmup
            return (
                "POST",
                "/api/access-requests",
                {
                    "name": f"Perf {tag} {n}",
                    "email": f"perf-{tag}-{n}@example.invalid",
                    "purpose": "performance measurement",
                },
                {},
            )

        c = Client(a.base_url)
        for k in range(a.create_requests):
            email = f"perf-{tag}-s{k}@example.invalid"
            try:
                s, body, dt = c.request(
                    "POST",
                    "/api/access-requests",
                    {"name": f"Perf {tag} {k}", "email": email, "purpose": "performance measurement"},
                )
            except (OSError, http.client.HTTPException):
                s, body, dt = -1, b"", 0.0
            if s == 202:
                j = json.loads(body)
                created.append((j["ref"], j["status_token"]))
                result.setdefault("_create_times", []).append((dt, len(body)))
            elif s == 429:
                result["access_request_create_rate_limited"] = result.get("access_request_create_rate_limited", 0) + 1
            elif s == 404:
                skipped["access_request_create"] = "HTTP 404: ACCESS_REQUESTS_ENABLED is false on this server"
                break
        times = result.pop("_create_times", [])
        if times:
            result["endpoints"]["access_request_create"] = summarise(
                [t for t, _ in times],
                [b for _, b in times],
                a.create_requests,
                result.pop("access_request_create_rate_limited", 0),
                a.create_requests - len(times),
            )
            result["endpoints"]["access_request_create"]["note"] = (
                f"{len(times)} timed creates only (capped by --create-requests); not a load figure"
            )
        if created:
            ref, tok = created[0]
            result["endpoints"]["access_request_status"] = run_endpoint(
                a.base_url,
                None,
                lambda i: ("GET", f"/api/access-requests/{ref}/status", None, {"X-Request-Token": tok}),
                a.requests,
                a.warmup,
                a.concurrency,
            )
        elif "access_request_create" not in skipped:
            skipped["access_request_status"] = "no access request could be created"
    result["skipped"] = skipped
    result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {a.out}")
    for name, r in sorted(result["endpoints"].items()):
        print(
            f"{name:28s} n={r['timed']:5d} p50={r.get('p50_ms')} p95={r.get('p95_ms')} p99={r.get('p99_ms')} errors={r['errors']} 429={r['rate_limited']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
