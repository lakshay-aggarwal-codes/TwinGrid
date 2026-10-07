"""Locust scenarios for T31 (reports/postT9/T31_evidence.md).

Required environment (no defaults -- there is no fallback account):
  LOAD_USER, LOAD_PASSWORD   credentials of an existing account
  LOAD_SCENARIO              rest_mix (default) | compute
Optional: LOAD_RESULT_PATH + LOAD_RUN_ID + LOAD_DB_ENGINE (+ LOAD_COMMIT, LOAD_LIMITER) -> writes a
reports/perf-style result file at test end (schema: scripts/load_profile.json).

  locust -f locustfile.py --headless -u 50 -r 5 -t 5m --host http://localhost:8000
"""

import importlib.util
import os
from pathlib import Path

import requests
from locust import HttpUser, between, events, task

TOKEN = None
_SCENARIO = os.environ.get("LOAD_SCENARIO", "rest_mix")


def _harness():
    spec = importlib.util.spec_from_file_location("ws_load", Path(__file__).parent / "scripts" / "ws_load.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def require_credentials():
    user, pw = os.environ.get("LOAD_USER"), os.environ.get("LOAD_PASSWORD")
    if not user or not pw:
        raise RuntimeError("LOAD_USER and LOAD_PASSWORD must be set; there are no default credentials")
    return user, pw


@events.test_start.add_listener
def login_once(environment, **kwargs):
    global TOKEN
    user, pw = require_credentials()
    r = requests.post(f"{environment.host}/auth/login", json={"username": user, "password": pw}, timeout=10)
    r.raise_for_status()
    TOKEN = r.json()["access_token"]


@events.test_stop.add_listener
def write_result(environment, **kwargs):
    out = os.environ.get("LOAD_RESULT_PATH")
    if not out:
        return
    h = _harness()
    st = environment.stats.total
    duration = max((st.last_request_timestamp or 0) - (st.start_time or 0), 0.0)
    users = getattr(environment.runner, "target_user_count", None) or int(os.environ.get("LOAD_USERS_COUNT", "0"))
    errs = {}
    for e in environment.stats.errors.values():
        errs[f"{e.method} {e.name}: {e.error}"[:120]] = e.occurrences
    lat_samples = []
    for ms, n in st.response_times.items():  # rounded-ms histogram -> expanded sample for nearest-rank percentiles
        lat_samples.extend([float(ms)] * n)
    res = h.make_result(
        run_id=os.environ.get("LOAD_RUN_ID", "locust-run"),
        scenario=os.environ.get("LOAD_SCENARIO_NAME", _SCENARIO),
        environment=h.build_environment(users=users, duration_s=duration, extra={"locust_scenario": _SCENARIO}),
        latencies_ms=lat_samples,
        requests_total=st.num_requests,
        errors_by_kind=errs,
        extra={"kind": "http", "rps": st.total_rps, "latency_meaning": "response time (rounded ms histogram)"},
    )
    h.write_result(res, out)


class _Base(HttpUser):
    abstract = True
    wait_time = between(0.5, 2)

    def on_start(self):
        self.h = {"Authorization": f"Bearer {TOKEN}"}


class Viewer(_Base):
    """rest_mix: read-heavy mix weighted like the historical baseline."""

    abstract = _SCENARIO != "rest_mix"

    @task(5)
    def whatif(self):
        self.client.get("/api/whatif", headers=self.h)

    @task(3)
    def simulate(self):
        self.client.get("/api/simulate/24", headers=self.h)

    @task(3)
    def state(self):
        self.client.get("/api/state", headers=self.h)

    @task(1)
    def alerts(self):
        self.client.get("/api/alerts", headers=self.h)

    @task(1)
    def health(self):
        self.client.get("/healthz")


class ComputeOnly(_Base):
    """compute: only the CPU-bound endpoints, to expose the limiter (run once with HTTP_LIMITS_ENABLED on, once off)."""

    abstract = _SCENARIO != "compute"

    @task(5)
    def whatif(self):
        self.client.get("/api/whatif", headers=self.h)

    @task(3)
    def simulate(self):
        self.client.get("/api/simulate/24", headers=self.h)
