#!/usr/bin/env python3
"""Measurement suite (roadmap Task 19). MEASURES ONLY: it optimises nothing and writes nothing but the JSON you name.

    python scripts\\bench_suite.py --sections twin,env,episode --out bench_local.json
    python scripts\\bench_suite.py --sections api --api-url http://localhost:8000 --out bench_api.json

Protocol (fixed so numbers are comparable between runs; numbers from different machines must not be mixed):
  * warm-up   : ``--warmup`` untimed repetitions (default 3), then ``--repeats`` timed repetitions (default 20, minimum 20)
  * clock     : ``time.perf_counter``; every repetition is one sample
  * reported  : n, median, IQR (Q3 - Q1, inclusive quartiles), min, max, p95 (nearest rank), mean
  * memory    : peak resident set of THIS PROCESS (``ru_maxrss`` / ``PeakWorkingSetSize``). It is a process-wide high-water
                mark, so run one section per process if you want per-section attribution (the PowerShell in the task
                report does this)
  * a section that cannot run is recorded as ``skipped`` or ``failed`` WITH the reason; nothing is estimated or filled in

Sections
  twin     DigitalTwin.step: one simulated day (288 steps) per sample, legacy-0 and physics 1, fresh twin per sample
  env      DataCentreEnv: reset + 288 steps per sample, physics 1 (needs gymnasium)
  episode  one evaluation episode (src.policy_evaluation.run_episode, rule policy), physics 1 (needs gymnasium)
  api      GET latency and payload size for /healthz, /api/state, /api/scenarios, /api/evaluations against a RUNNING server
           (``--api-url``; sign-in with TWINGRID_USERNAME / TWINGRID_PASSWORD from the environment, never argv).
           Requests are paced (``--api-interval-s``, default 2.5 s) to stay under the server's 30/minute ``state`` limit;
           a 429 is waited out and counted, never timed. Times include loopback/network and server work; keep-alive.
NOT MEASURED BY DESIGN: a full ``baselines tune`` (it overwrites the committed configs/baselines/*.json).

Everything measured is simulated plant behaviour on the machine named in ``environment``.
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import logging
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA = "twingrid-bench/1"
MIN_REPEATS = 20
DEFAULT_WARMUP = 3
STEPS_PER_DAY = 288
ALL_SECTIONS = ("twin", "env", "episode", "api")
LOCAL_SECTIONS = ("twin", "env", "episode")
API_PATHS = ("/healthz", "/api/state", "/api/scenarios", "/api/evaluations")


class BenchError(RuntimeError):
    """A section could not be measured (recorded with its reason, never hidden)."""


# --------------------------------------------------------------------------------------------- statistics
def summarise(samples: Sequence[float]) -> dict[str, float | int]:
    """Distribution summary of ``samples`` (seconds or bytes). Raises ``ValueError`` on fewer than 2 samples."""
    xs = sorted(float(x) for x in samples)
    if len(xs) < 2:
        raise ValueError("need at least 2 samples")
    q = statistics.quantiles(xs, n=4, method="inclusive")
    p95 = xs[min(len(xs) - 1, max(0, math.ceil(0.95 * len(xs)) - 1))]
    return {
        "n": len(xs),
        "median": statistics.median(xs),
        "iqr": q[2] - q[0],
        "min": xs[0],
        "max": xs[-1],
        "p95": p95,
        "mean": statistics.fmean(xs),
    }


def time_samples(
    fn: Callable[[], Any], *, warmup: int, repeats: int, prepare: Callable[[], Any] | None = None
) -> list[float]:
    """Seconds per call. ``prepare()`` (untimed) builds the argument for ``fn``; its result is passed in when given."""

    def once() -> float:
        arg = prepare() if prepare else None
        start = time.perf_counter()
        fn(arg) if prepare else fn()  # type: ignore[call-arg]
        return time.perf_counter() - start

    for _ in range(warmup):
        once()
    return [once() for _ in range(repeats)]


def peak_rss_mb() -> float | None:
    """Peak resident set size of this process in MiB, or None if the platform gives no way to read it."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / (1024.0 * 1024.0) if sys.platform == "darwin" else peak / 1024.0
    except ImportError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi  # type: ignore[attr-defined]
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return counters.PeakWorkingSetSize / (1024.0 * 1024.0)
        except Exception:  # noqa: BLE001  (a memory probe must never break a benchmark)
            return None
    return None


def environment() -> dict[str, Any]:
    import numpy as np

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
    }


def _timing(samples: Sequence[float], *, per: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"seconds": summarise(samples)}
    if per:
        out["microseconds_per_unit_median"] = out["seconds"]["median"] / per * 1e6
    return out


# --------------------------------------------------------------------------------------------- sections
def day_actions(chilled_c: float) -> list[dict[str, Any]]:
    """Deterministic 288-step day (no RNG): the same inputs for every sample and every machine."""
    actions = []
    for i in range(STEPS_PER_DAY):
        outside = 20 + 8 * math.sin((i - 72) * math.pi / 144)
        mode = "free_air" if outside < 12 else "evaporative" if outside > 25 else "closed_loop"
        actions.append(
            {
                "utilisation": min(0.9, max(0.1, 0.5 + 0.3 * math.sin((i - 96) * 0.05))),
                "outside_temp_C": outside,
                "cooling_mode": mode,
                "humidity_pct": 45 + 15 * math.sin(i * 0.05),
                "water_pressure_bar": 2.8 + 0.4 * math.sin(i * 0.03),
                "chilled_water_temp_C": chilled_c,
            }
        )
    return actions


def bench_twin(warmup: int, repeats: int) -> dict[str, Any]:
    from src.digital_twin import DigitalTwin

    result: dict[str, Any] = {"unit": "one simulated day = 288 steps; fresh twin per sample (construction not timed)"}
    for version, chilled in (("legacy-0", 12.0), ("1", 20.0)):
        actions = day_actions(chilled)

        def run_day(twin: Any, actions=actions) -> None:
            for a in actions:
                twin.step(a)

        samples = time_samples(
            run_day, warmup=warmup, repeats=repeats, prepare=lambda v=version: DigitalTwin(physics_version=v)
        )
        result[f"physics_{version}"] = _timing(samples, per=STEPS_PER_DAY)
    return result


def _require_gymnasium() -> None:
    try:
        import gymnasium  # noqa: F401
    except ImportError as exc:
        raise BenchError(f"gymnasium is not installed ({exc}); this section needs the training stack") from exc


def bench_env(warmup: int, repeats: int) -> dict[str, Any]:
    _require_gymnasium()
    import numpy as np

    from src.carbon_provider import load_diurnal_carbon_intensity
    from src.rl.env import DataCentreEnv

    curve, is_real = load_diurnal_carbon_intensity()
    action = np.array([0.5, 0.5], dtype=np.float32)

    def make() -> Any:
        return DataCentreEnv(physics_version="1", max_steps=STEPS_PER_DAY, seed=0, carbon_intensity_by_hour=curve)

    def episode(env: Any) -> None:
        env.reset(seed=0)
        for _ in range(STEPS_PER_DAY):
            _, _, term, trunc, _ = env.step(action)
            if term or trunc:
                break

    samples = time_samples(episode, warmup=warmup, repeats=repeats, prepare=make)
    return {
        "unit": "reset + up to 288 steps, constant action [0.5, 0.5]; construction not timed",
        "physics_version": "1",
        "carbon_is_real": bool(is_real),
        **_timing(samples, per=STEPS_PER_DAY),
    }


def bench_episode(warmup: int, repeats: int) -> dict[str, Any]:
    _require_gymnasium()
    from src import policy_evaluation as pe

    cfg = pe.EvalConfig()
    curve, is_real = pe.load_diurnal_carbon_intensity()
    scenario = pe.build_scenarios(cfg)["validation"][0]
    policy = pe.RulePolicy(cfg.rule_chilled_C, physics_version=cfg.resolved_physics_version)
    samples = time_samples(lambda: pe.run_episode(policy, scenario, cfg, curve), warmup=warmup, repeats=repeats)
    return {
        "unit": "one evaluation episode incl. environment construction (the cost an evaluation multiplies by scenarios x policies)",
        "physics_version": cfg.resolved_physics_version,
        "scenario_id": scenario.scenario_id,
        "episode_steps": cfg.episode_steps,
        "carbon_is_real": bool(is_real),
        **_timing(samples, per=cfg.episode_steps),
    }


class _Client:
    """Keep-alive HTTP client with 429 handling; stdlib only."""

    def __init__(self, base_url: str) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise BenchError(f"--api-url must be http(s)://host[:port], got {base_url!r}")
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        self.conn = cls(parts.hostname, parts.port, timeout=30)
        self.token: str | None = None

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, bytes, float, dict[str, str]]:
        headers = {"Accept-Encoding": "identity", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        start = time.perf_counter()
        self.conn.request(method, path, body=data, headers=headers)
        resp = self.conn.getresponse()
        payload = resp.read()
        return resp.status, payload, time.perf_counter() - start, {k.lower(): v for k, v in resp.getheaders()}


def bench_api(warmup: int, repeats: int, api_url: str | None, interval_s: float) -> dict[str, Any]:
    if not api_url:
        raise BenchError("no --api-url given (start the API first); not measured")
    user, password = os.environ.get("TWINGRID_USERNAME"), os.environ.get("TWINGRID_PASSWORD")
    client = _Client(api_url)
    try:
        status, payload, _, _ = client.request("GET", "/healthz")
    except OSError as exc:
        raise BenchError(f"cannot reach {api_url}: {exc}") from exc
    if status >= 500:
        raise BenchError(f"/healthz returned {status}")
    if user and password:
        status, payload, _, _ = client.request("POST", "/auth/login", {"username": user, "password": password})
        if status != 200:
            raise BenchError(f"sign-in failed with HTTP {status} (credentials are not echoed)")
        client.token = json.loads(payload)["access_token"]
        authenticated = True
    else:
        authenticated = False
    result: dict[str, Any] = {
        "authenticated": authenticated,
        "pacing_s": interval_s,
        "note": "times include network/loopback and keep-alive; server work not separated",
        "endpoints": {},
    }
    for path in API_PATHS:
        times: list[float] = []
        sizes: list[int] = []
        statuses: dict[str, int] = {}
        throttled = 0
        total = warmup + repeats
        attempts = answered = 0
        while len(times) < repeats and attempts < total * 5:
            attempts += 1
            code, body, elapsed, headers = client.request("GET", path)
            statuses[str(code)] = statuses.get(str(code), 0) + 1
            if code == 429:
                throttled += 1
                time.sleep(min(60.0, float(headers.get("retry-after", "1")) + 0.5))
                continue
            answered += 1
            if answered > warmup:  # the first ``warmup`` answered requests are not timed
                times.append(elapsed)
                sizes.append(len(body))
            time.sleep(interval_s)
        entry: dict[str, Any] = {"http_status_counts": statuses, "throttled_429": throttled}
        ok = statuses.get("200", 0)
        if len(times) >= repeats and ok >= repeats and set(statuses) <= {"200", "429"}:
            entry["latency"] = {"seconds": summarise(times)}
            entry["payload_bytes"] = {
                "identity": summarise(sizes),
                "gzip_estimate_bytes_last": len(gzip.compress(body)),
            }
        else:
            entry["status"] = "not_measured"
            entry["reason"] = "not enough 200 responses (authentication, role or rate limit); no latency is reported"
        result["endpoints"][path] = entry
    return result


SECTION_FUNCS: dict[str, Callable[..., dict[str, Any]]] = {
    "twin": bench_twin,
    "env": bench_env,
    "episode": bench_episode,
}


def run_section(name: str, args: argparse.Namespace) -> dict[str, Any]:
    """Run one section and wrap the outcome; never raises for a section problem."""
    try:
        if name == "api":
            data = bench_api(args.warmup, args.repeats, args.api_url, args.api_interval_s)
        else:
            data = SECTION_FUNCS[name](args.warmup, args.repeats)
        return {"status": "measured", **data}
    except BenchError as exc:
        return {"status": "skipped", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001  (record, do not hide, do not crash the rest)
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:500]}


def parse_sections(text: str) -> list[str]:
    names = [s.strip() for s in text.split(",") if s.strip()]
    bad = [n for n in names if n not in ALL_SECTIONS]
    if bad or not names:
        raise argparse.ArgumentTypeError(f"sections must be a comma list of {ALL_SECTIONS}; got {text!r}")
    return names


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sections", type=parse_sections, default=list(LOCAL_SECTIONS))
    ap.add_argument(
        "--repeats", type=int, default=MIN_REPEATS, help=f"timed samples per measurement (>= {MIN_REPEATS})"
    )
    ap.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    ap.add_argument("--api-url", default=None)
    ap.add_argument("--api-interval-s", type=float, default=2.5)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.repeats < MIN_REPEATS:
        ap.error(f"--repeats must be >= {MIN_REPEATS} (median/IQR are not meaningful below that)")
    if args.warmup < 0 or args.api_interval_s < 0:
        ap.error("--warmup and --api-interval-s must be >= 0")

    logging.disable(logging.CRITICAL)  # keep the carbon-fallback warning out of the timing loops
    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "environment": environment(),
        "protocol": {
            "warmup": args.warmup,
            "repeats": args.repeats,
            "clock": "time.perf_counter",
            "sections_requested": args.sections,
        },
        "sections": {},
    }
    for name in args.sections:
        print(f"[{name}] ...", flush=True)
        doc["sections"][name] = run_section(name, args)
        print(f"[{name}] {doc['sections'][name]['status']}", flush=True)
    doc["peak_rss_mb_process_wide"] = peak_rss_mb()
    args.out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0 if all(s["status"] != "failed" for s in doc["sections"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
