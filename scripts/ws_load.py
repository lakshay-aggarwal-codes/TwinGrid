#!/usr/bin/env python3
"""T31 load / resilience harness (no product code is modified; see reports/postT9/T31_evidence.md).

Sub-commands
  ws        open N WebSocket clients on /ws/live (optionally one STALLED client), measure connect latency,
            close codes and tick-time drift.
  ingest    drive src.telemetry.ingest.ingest_samples in-process with batches of the batch limit.
            (There is NO HTTP ingest route in the backend; ingest is MQTT/in-process only.)
  validate  validate result files against the schema in scripts/load_profile.json.
  budgets   --propose: derive budgets from ONE measured result; --check: enforce budgets over a results dir.

Result file (reports/perf/<run_id>.json) fields: see ``result_schema`` in scripts/load_profile.json.
Credentials are never defaulted: LOAD_USER/LOAD_PASSWORD (or LOAD_USERS="u1:p1,u2:p2") must be set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = Path(__file__).resolve().parent / "load_profile.json"
SCHEMA_VERSION = 1


# ----------------------------------------------------------------------------------------------------
# generic helpers (also imported by locustfile.py)
# ----------------------------------------------------------------------------------------------------
def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile, q in [0, 100]. None for an empty sample (never 0, which would read as 'fast')."""
    if not values:
        return None
    s = sorted(values)
    k = max(1, math.ceil(q / 100.0 * len(s)))
    return float(s[k - 1])


def percentiles(values_ms: Sequence[float]) -> dict[str, Any]:
    return {
        "count": len(values_ms),
        "p50_ms": percentile(values_ms, 50),
        "p95_ms": percentile(values_ms, 95),
        "p99_ms": percentile(values_ms, 99),
        "max_ms": float(max(values_ms)) if values_ms else None,
    }


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def host_spec() -> dict[str, Any]:
    mem_mb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    mem_mb = int(line.split()[1]) // 1024
                    break
    except OSError:
        pass
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "memory_mb": mem_mb,
        "python": platform.python_version(),
    }


def build_environment(
    *, users: int, duration_s: float, limiter: str | None = None, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run metadata required by the contract: host spec, commit, DB engine, users, duration.

    ``LOAD_COMMIT`` / ``LOAD_DB_ENGINE`` / ``LOAD_LIMITER`` come from the environment because the harness runs on a
    different machine than the server in the workflow. DB engine has no default: a run without it is rejected.
    """
    commit = os.environ.get("LOAD_COMMIT") or _git("rev-parse", "HEAD")
    dirty_raw = _git("status", "--porcelain")
    return {
        "host": host_spec(),
        "server_host_note": os.environ.get("LOAD_SERVER_HOST_NOTE", ""),
        "commit": commit,
        "tree_dirty": bool(dirty_raw) if dirty_raw is not None else None,
        "db_engine": os.environ.get("LOAD_DB_ENGINE"),
        "limiter": limiter if limiter is not None else os.environ.get("LOAD_LIMITER"),
        "users": users,
        "duration_s": round(float(duration_s), 3),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "extra": extra or {},
    }


def make_result(
    *,
    run_id: str,
    scenario: str,
    environment: dict[str, Any],
    latencies_ms: Sequence[float],
    requests_total: int,
    errors_by_kind: dict[str, int],
    tick_drift: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    n_err = sum(errors_by_kind.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "scenario": scenario,
        "environment": environment,
        "percentiles": percentiles(latencies_ms),
        "errors": {
            "requests": requests_total,
            "count": n_err,
            "rate": (n_err / requests_total) if requests_total else None,
            "by_kind": dict(errors_by_kind),
        },
        "tick_drift": tick_drift,
        "extra": extra or {},
    }


def load_profile() -> dict[str, Any]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def validate_result(result: dict[str, Any], profile: dict[str, Any] | None = None) -> list[str]:
    """Schema errors for one result (empty list = valid). Also rejects runs that lack mandatory metadata."""
    import jsonschema

    profile = profile or load_profile()
    validator = jsonschema.Draft202012Validator(profile["result_schema"])
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in validator.iter_errors(result)]
    env = result.get("environment") or {}
    if not env.get("commit"):
        errs.append("environment.commit: missing (set LOAD_COMMIT or run inside the git checkout)")
    if env.get("db_engine") not in ("sqlite", "postgresql"):
        errs.append("environment.db_engine: must be 'sqlite' or 'postgresql' (set LOAD_DB_ENGINE)")
    return errs


def write_result(result: dict[str, Any], out: str | Path) -> Path:
    errs = validate_result(result)
    if errs:
        raise SystemExit("result does not satisfy the schema:\n  " + "\n  ".join(errs))
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------------------------------------------
# credentials / login
# ----------------------------------------------------------------------------------------------------
def credentials_from_env() -> list[tuple[str, str]]:
    raw = os.environ.get("LOAD_USERS", "").strip()
    pairs: list[tuple[str, str]] = []
    if raw:
        for item in raw.split(","):
            user, sep, pw = item.strip().partition(":")
            if not sep or not user or not pw:
                raise SystemExit("LOAD_USERS must be 'user:password[,user:password...]'")
            pairs.append((user, pw))
    elif os.environ.get("LOAD_USER") and os.environ.get("LOAD_PASSWORD"):
        pairs.append((os.environ["LOAD_USER"], os.environ["LOAD_PASSWORD"]))
    if not pairs:
        raise SystemExit("credentials required: set LOAD_USER and LOAD_PASSWORD (or LOAD_USERS); there are no defaults")
    return pairs


def login(base_url: str, username: str, password: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/auth/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-supplied URL
        return json.loads(resp.read())["access_token"]


# ----------------------------------------------------------------------------------------------------
# ws scenario
# ----------------------------------------------------------------------------------------------------
def _ws_uri(base_url: str, token: str) -> str:
    base = base_url.rstrip("/")
    scheme = "wss" if base.startswith("https://") else "ws"
    return f"{scheme}://{base.split('://', 1)[1]}/ws/live?token={token}"


def tick_drift_from_arrivals(arrivals: Iterable[tuple[float, int, float]]) -> list[float]:
    """Client-observed drift in ms: for consecutive messages, (arrival gap) - (seq delta * nominal interval).

    ``arrivals`` = (monotonic_s, seq, interval_s). A seq jump is a gap in delivery; it is counted by the caller as a
    missed tick, and its drift is computed against ``seq delta`` so one missed tick does not look like 3 s of lag.
    """
    drifts: list[float] = []
    prev: tuple[float, int, float] | None = None
    for t, seq, interval in arrivals:
        if prev is not None and seq > prev[1]:
            drifts.append(abs((t - prev[0]) - (seq - prev[1]) * interval) * 1000.0)
        prev = (t, seq, interval)
    return drifts


async def _ws_client(uri: str, deadline: float, *, stalled: bool, rcvbuf: int | None, out: dict[str, Any]) -> None:
    import websockets
    from websockets.asyncio.client import connect

    t0 = time.monotonic()
    sock = None
    kwargs: dict[str, Any] = {"open_timeout": 15, "ping_interval": None, "max_queue": 1 if stalled else 64}
    try:
        if stalled:
            # Stalled = connected, never reads. A tiny receive buffer + max_queue=1 makes the TCP window close
            # after one frame, which is what a stuck browser tab looks like to the server's send().
            host, port = (
                uri.split("://", 1)[1].split("/", 1)[0].rsplit(":", 1)
                if ":" in uri.split("://", 1)[1].split("/", 1)[0]
                else (uri.split("://", 1)[1].split("/", 1)[0], "80")
            )
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf or 1024)
            sock.setblocking(False)
            await asyncio.get_running_loop().sock_connect(sock, (host, int(port)))
            kwargs["sock"] = sock
        ws = await connect(uri, **kwargs)
    except Exception as exc:  # noqa: BLE001 - every failure kind is recorded
        out["connect_error"] = type(exc).__name__
        if sock is not None:
            sock.close()
        return
    out["connect_ms"] = (time.monotonic() - t0) * 1000.0
    arrivals: list[tuple[float, int, float]] = []
    server_gaps: list[float] = []
    try:
        if stalled:
            while time.monotonic() < deadline and ws.close_code is None:
                await asyncio.sleep(0.25)
        else:
            last_server_ts: float | None = None
            last_seq: int | None = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                now = time.monotonic()
                try:
                    msg = json.loads(raw)
                    seq, interval = int(msg["seq"]), float(msg["interval_s"])
                except (ValueError, KeyError, TypeError):
                    out["bad_messages"] = out.get("bad_messages", 0) + 1
                    continue
                arrivals.append((now, seq, interval))
                try:
                    ts = datetime.fromisoformat(msg["ts_ingest"]).timestamp()
                    if last_server_ts is not None and last_seq is not None and seq > last_seq:
                        server_gaps.append(abs((ts - last_server_ts) - (seq - last_seq) * interval) * 1000.0)
                    last_server_ts, last_seq = ts, seq
                except (KeyError, ValueError, TypeError):
                    pass
    except websockets.ConnectionClosed:
        pass
    finally:
        out["close_code"] = ws.close_code  # None while still open at the deadline
        await ws.close()
    out["arrivals"] = arrivals
    out["server_gaps_ms"] = server_gaps


async def run_ws(
    base_url: str, connections: int, duration_s: float, stalled: int, per_user: int, rcvbuf: int | None
) -> dict[str, Any]:
    creds = credentials_from_env()
    need = math.ceil((connections + stalled) / per_user)
    if len(creds) < need:
        raise SystemExit(
            f"{connections + stalled} connections at {per_user}/user needs {need} users, {len(creds)} supplied "
            f"(or raise WS_MAX_CONNECTIONS_PER_USER on the server and pass --per-user; record it)"
        )
    loop = asyncio.get_running_loop()
    tokens = [await loop.run_in_executor(None, login, base_url, u, p) for u, p in creds[:need]]
    t_start = time.monotonic()
    deadline = t_start + duration_s
    outs: list[dict[str, Any]] = []
    tasks = []
    for i in range(connections + stalled):
        out: dict[str, Any] = {"stalled": i >= connections}
        outs.append(out)
        tasks.append(
            asyncio.create_task(
                _ws_client(
                    _ws_uri(base_url, tokens[i // per_user]), deadline, stalled=out["stalled"], rcvbuf=rcvbuf, out=out
                )
            )
        )
        if i % 50 == 49:
            await asyncio.sleep(0.05)  # do not turn the connect phase itself into the load
    await asyncio.gather(*tasks)
    return {"outs": outs, "elapsed": time.monotonic() - t_start}


def summarize_ws(raw: dict[str, Any], *, run_id: str, scenario: str, connections: int, stalled: int) -> dict[str, Any]:
    outs = raw["outs"]
    connect_ms = [o["connect_ms"] for o in outs if "connect_ms" in o]
    errors: Counter[str] = Counter()
    closes: Counter[str] = Counter()
    for o in outs:
        if "connect_error" in o:
            errors[f"connect:{o['connect_error']}"] += 1
        elif o.get("close_code") not in (None, 1000):
            # a healthy client that was closed by the server before the deadline is an error; a stalled one is data
            (closes if o["stalled"] else errors)[f"close:{o['close_code']}"] += 1
        if o.get("bad_messages"):
            errors["bad_message"] += o["bad_messages"]
    healthy = [o for o in outs if not o["stalled"] and "arrivals" in o]
    drifts: list[float] = []
    server_drifts: list[float] = []
    missed = 0
    for o in healthy:
        drifts.extend(tick_drift_from_arrivals(o["arrivals"]))
        server_drifts.extend(o.get("server_gaps_ms", []))
        seqs = [a[1] for a in o["arrivals"]]
        missed += sum(max(0, b - a - 1) for a, b in zip(seqs, seqs[1:]))
    stalled_outs = [o for o in outs if o["stalled"]]
    td = percentiles(drifts)
    tick_drift = {
        **td,
        "missed_ticks": missed,
        "clients_measured": len(healthy),
        "server_ts_ingest_p95_ms": percentile(server_drifts, 95),
        "server_ts_ingest_max_ms": max(server_drifts) if server_drifts else None,
    }
    env = build_environment(users=connections + stalled, duration_s=raw["elapsed"])
    return make_result(
        run_id=run_id,
        scenario=scenario,
        environment=env,
        latencies_ms=connect_ms,
        requests_total=connections + stalled,
        errors_by_kind=dict(errors),
        tick_drift=tick_drift,
        extra={
            "kind": "websocket",
            "latency_meaning": "connect (handshake) latency",
            "healthy_connections": connections,
            "stalled_connections": stalled,
            "stalled_close_codes": dict(closes),
            "stalled_still_open_at_end": sum(1 for o in stalled_outs if o.get("close_code") is None),
            "healthy_still_open_at_end": sum(1 for o in healthy if o.get("close_code") is None),
        },
    )


# ----------------------------------------------------------------------------------------------------
# ingest scenario (in-process; imports product code read-only, lazily)
# ----------------------------------------------------------------------------------------------------
async def run_ingest(duration_s: float, concurrency: int, batch: int, stream_id: str, origin: str) -> dict[str, Any]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from models.db_models import Sensor
    from src.telemetry.ingest import MAX_BATCH, ingest_samples

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required for the ingest scenario")
    batch = min(batch, MAX_BATCH)
    engine = create_async_engine(url, pool_size=concurrency + 2) if "sqlite" not in url else create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        sensors = (await s.execute(select(Sensor.external_id).limit(50))).scalars().all()
    if not sensors:
        raise SystemExit("no sensors in the database: seed it first (scripts/seed_facility.py)")
    lat: list[float] = []
    errors: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    deadline = time.monotonic() + duration_s
    base_ts = datetime.now(timezone.utc).timestamp()
    counter = {"n": 0}

    async def worker(w: int) -> None:
        while time.monotonic() < deadline:
            counter["n"] += 1
            k = counter["n"]
            samples = [
                {
                    "external_id": sensors[j % len(sensors)],
                    "ts_event": datetime.fromtimestamp(base_ts - 1e5 - k * 1000 - j, timezone.utc).isoformat(),
                    "value": 20.0 + (j % 10) * 0.1,
                    **({"sim_time": 0.0} if origin == "simulated" else {}),
                }
                for j in range(batch)
            ]
            t0 = time.monotonic()
            try:
                async with maker() as session:
                    res = await ingest_samples(session, samples, stream_id=stream_id, origin=origin)
                    await session.commit()
                outcomes.update(getattr(res, "counts", {}) or {})
                lat.append((time.monotonic() - t0) * 1000.0)
            except Exception as exc:  # noqa: BLE001
                errors[type(exc).__name__] += 1

    t_start = time.monotonic()
    await asyncio.gather(*(worker(w) for w in range(concurrency)))
    elapsed = time.monotonic() - t_start
    await engine.dispose()
    env = build_environment(users=concurrency, duration_s=elapsed)
    return make_result(
        run_id="",
        scenario="ingest",
        environment=env,
        latencies_ms=lat,
        requests_total=len(lat) + sum(errors.values()),
        errors_by_kind=dict(errors),
        extra={
            "kind": "ingest",
            "batch_size": batch,
            "batches_ok": len(lat),
            "outcomes": dict(outcomes),
            "samples_per_s": (len(lat) * batch / elapsed) if elapsed else None,
        },
    )


# ----------------------------------------------------------------------------------------------------
# budgets
# ----------------------------------------------------------------------------------------------------
BUDGET_FIELDS = {
    "p95_ms": lambda r: r["percentiles"]["p95_ms"],
    "p99_ms": lambda r: r["percentiles"]["p99_ms"],
    "error_rate": lambda r: r["errors"]["rate"],
    "tick_drift_p95_ms": lambda r: (r.get("tick_drift") or {}).get("p95_ms"),
}


def propose_budgets(result: dict[str, Any], headroom: float) -> dict[str, float | None]:
    """Budgets from ONE measured run: measured value x headroom (error_rate: measured + 1 pp). Never auto-written."""
    out: dict[str, float | None] = {}
    for name, getter in BUDGET_FIELDS.items():
        val = getter(result)
        if val is None:
            out[name] = None
        elif name == "error_rate":
            out[name] = round(val + 0.01, 4)
        else:
            out[name] = round(val * headroom, 1)
    return out


def check_budgets(results: Sequence[dict[str, Any]], profile: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(breaches, unset). A scenario whose budgets are all null is 'unset' (first run), not a pass."""
    breaches: list[str] = []
    unset: list[str] = []
    for r in results:
        budgets = (profile["scenarios"].get(r["scenario"]) or {}).get("budgets") or {}
        if not any(v is not None for v in budgets.values()):
            unset.append(r["scenario"])
            continue
        for name, limit in budgets.items():
            if limit is None:
                continue
            val = BUDGET_FIELDS[name](r)
            if val is None:
                breaches.append(f"{r['scenario']}: {name} not measured (budget {limit})")
            elif val > limit:
                breaches.append(f"{r['scenario']}: {name} {val} > budget {limit}")
    return breaches, unset


# ----------------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------------
def _load_results(paths: Sequence[str]) -> list[dict[str, Any]]:
    files: list[Path] = []
    for p in paths:
        pp = Path(p)
        files.extend(sorted(pp.glob("*.json")) if pp.is_dir() else [pp])
    out = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION and "scenario" in data:
            out.append(data)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("ws")
    w.add_argument("--base-url", required=True)
    w.add_argument("--connections", type=int, required=True, help="healthy clients (a stalled one is extra)")
    w.add_argument("--stalled", type=int, default=1)
    w.add_argument("--duration", type=float, default=60.0)
    w.add_argument("--per-user", type=int, default=5, help="server WS_MAX_CONNECTIONS_PER_USER (record it)")
    w.add_argument("--stalled-rcvbuf", type=int, default=1024)
    w.add_argument("--run-id", required=True)
    w.add_argument("--scenario", required=True)
    w.add_argument("--out", required=True)

    i = sub.add_parser("ingest")
    i.add_argument("--duration", type=float, default=60.0)
    i.add_argument("--concurrency", type=int, default=4)
    i.add_argument("--batch", type=int, default=1000)
    i.add_argument("--stream-id", default="load")
    i.add_argument("--origin", default="simulated")
    i.add_argument("--run-id", required=True)
    i.add_argument("--out", required=True)

    v = sub.add_parser("validate")
    v.add_argument("paths", nargs="+")

    b = sub.add_parser("budgets")
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--propose", metavar="RESULT_JSON")
    g.add_argument("--check", metavar="RESULTS_DIR")
    b.add_argument("--headroom", type=float, default=None)
    b.add_argument("--allow-unset", action="store_true", help="first run: scenarios with no budgets do not fail")

    a = ap.parse_args(argv)
    if a.cmd == "ws":
        raw = asyncio.run(run_ws(a.base_url, a.connections, a.duration, a.stalled, a.per_user, a.stalled_rcvbuf))
        res = summarize_ws(raw, run_id=a.run_id, scenario=a.scenario, connections=a.connections, stalled=a.stalled)
        res["extra"]["per_user_cap_assumed"] = a.per_user
        print(write_result(res, a.out))
        return 0
    if a.cmd == "ingest":
        res = asyncio.run(run_ingest(a.duration, a.concurrency, a.batch, a.stream_id, a.origin))
        res["run_id"] = a.run_id
        print(write_result(res, a.out))
        return 0
    if a.cmd == "validate":
        bad = 0
        for r in _load_results(a.paths):
            errs = validate_result(r)
            print(("FAIL " if errs else "ok   ") + r.get("run_id", "?"))
            for e in errs:
                print("   ", e)
            bad += bool(errs)
        return 1 if bad else 0
    profile = load_profile()
    if a.propose:
        head = a.headroom or profile.get("budget_headroom")
        if not head:
            raise SystemExit("--headroom required (profile budget_headroom is unset)")
        r = _load_results([a.propose])[0]
        print(json.dumps({r["scenario"]: propose_budgets(r, float(head))}, indent=2))
        return 0
    breaches, unset = check_budgets(_load_results([a.check]), profile)
    for u in unset:
        print(f"UNSET budgets for scenario {u!r}")
    for br in breaches:
        print("BREACH", br)
    if breaches or (unset and not a.allow_unset):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
