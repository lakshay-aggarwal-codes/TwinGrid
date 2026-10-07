"""T31 harness tests: result schema, budgets, credentials, and a smoke run against a STUB server.

The stub stands in for the app (the real app is exercised only by the manual workflow, .github/workflows/load.yml).
"""

import asyncio
import importlib.util
import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ws_load", ROOT / "scripts" / "ws_load.py")
wl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wl)

ENV = {"LOAD_COMMIT": "abc123", "LOAD_DB_ENGINE": "sqlite", "LOAD_LIMITER": "on"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


def _result(**kw):
    base = dict(
        run_id="r1",
        scenario="rest_mix_25",
        environment=wl.build_environment(users=25, duration_s=10),
        latencies_ms=[10, 20, 30, 40, 1000],
        requests_total=5,
        errors_by_kind={},
    )
    base.update(kw)
    return wl.make_result(**base)


def test_percentile_nearest_rank_and_empty():
    assert wl.percentile([1, 2, 3, 4, 100], 95) == 100
    assert wl.percentile([1, 2, 3, 4, 100], 50) == 3
    assert wl.percentile([], 95) is None


def test_valid_result_passes_schema():
    assert wl.validate_result(_result()) == []


def test_missing_db_engine_or_commit_rejected(monkeypatch):
    monkeypatch.delenv("LOAD_DB_ENGINE")
    assert any("db_engine" in e for e in wl.validate_result(_result()))
    monkeypatch.setenv("LOAD_DB_ENGINE", "sqlite")
    monkeypatch.setenv("LOAD_COMMIT", "")
    monkeypatch.setattr(wl, "_git", lambda *a: None)
    assert any("commit" in e for e in wl.validate_result(_result()))


def test_schema_rejects_missing_sections():
    r = _result()
    del r["errors"]
    assert wl.validate_result(r)


def test_write_result_refuses_invalid(tmp_path):
    r = _result()
    r["schema_version"] = 2
    with pytest.raises(SystemExit):
        wl.write_result(r, tmp_path / "x.json")


def test_budgets_unset_then_enforced():
    profile = wl.load_profile()
    r = _result()
    assert wl.check_budgets([r], profile) == ([], ["rest_mix_25"])
    prop = wl.propose_budgets(r, 1.5)
    assert prop["p95_ms"] == 1500.0 and prop["error_rate"] == 0.01 and prop["tick_drift_p95_ms"] is None
    profile["scenarios"]["rest_mix_25"]["budgets"] = prop
    assert wl.check_budgets([r], profile) == ([], [])
    worse = _result(latencies_ms=[3000] * 5)
    breaches, _ = wl.check_budgets([worse], profile)
    assert breaches and "p95_ms" in breaches[0]


def test_profile_budgets_are_all_unset_until_measured():
    profile = wl.load_profile()
    for name, sc in profile["scenarios"].items():
        assert all(v is None for v in sc["budgets"].values()), name


def test_tick_drift_accounts_for_missed_ticks():
    # ticks at 1 s nominal; seq 1,2 on time; seq 3 lost; seq 4 arrives 2 s after seq 2 -> drift 0
    arr = [(0.0, 1, 1.0), (1.0, 2, 1.0), (3.0, 4, 1.0)]
    assert wl.tick_drift_from_arrivals(arr) == [0.0, 0.0]
    late = [(0.0, 1, 1.0), (1.5, 2, 1.0)]
    assert wl.tick_drift_from_arrivals(late) == [500.0]


def test_credentials_required_no_defaults(monkeypatch):
    for k in ("LOAD_USER", "LOAD_PASSWORD", "LOAD_USERS"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit):
        wl.credentials_from_env()
    monkeypatch.setenv("LOAD_USERS", "a:b,c:d")
    assert wl.credentials_from_env() == [("a", "b"), ("c", "d")]


def test_locustfile_has_no_default_credentials(monkeypatch):
    src = (ROOT / "locustfile.py").read_text(encoding="utf-8")
    assert "password123" not in src and "viewer1" not in src
    pytest.importorskip("locust")
    spec = importlib.util.spec_from_file_location("lf", ROOT / "locustfile.py")
    lf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lf)
    for k in ("LOAD_USER", "LOAD_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError):
        lf.require_credentials()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_ws_smoke_against_stub_with_stalled_client(monkeypatch, tmp_path):
    pytest.importorskip("websockets")
    from websockets.asyncio.server import serve

    port = _free_port()
    monkeypatch.setenv("LOAD_USERS", "u1:p,u2:p")
    monkeypatch.setattr(wl, "login", lambda base, u, p, timeout=10: f"tok-{u}")

    async def handler(ws):
        seq = 0
        try:
            while True:
                seq += 1
                await ws.send(
                    json.dumps(
                        {"seq": seq, "interval_s": 0.1, "ts_ingest": "2026-01-01T00:00:00+00:00", "pad": "x" * 20000}
                    )
                )
                await asyncio.sleep(0.1)
        except Exception:  # noqa: BLE001 - client went away
            return

    async def scenario():
        async with serve(handler, "127.0.0.1", port):
            return await wl.run_ws(
                f"http://127.0.0.1:{port}", connections=3, duration_s=2.0, stalled=1, per_user=2, rcvbuf=1024
            )

    raw = asyncio.run(scenario())
    res = wl.summarize_ws(raw, run_id="smoke", scenario="ws_50", connections=3, stalled=1)
    assert wl.validate_result(res) == []
    assert res["extra"]["healthy_connections"] == 3
    assert res["percentiles"]["count"] == 4  # four connects measured
    assert res["tick_drift"]["clients_measured"] == 3 and res["tick_drift"]["count"] > 5
    assert res["extra"]["stalled_still_open_at_end"] == 1  # a stalled peer must not be what kills the healthy ones
    assert res["errors"]["count"] == 0
    out = wl.write_result(res, tmp_path / "smoke.json")
    assert wl.main(["validate", str(out)]) == 0


def test_ws_not_enough_users_is_an_error(monkeypatch):
    monkeypatch.setenv("LOAD_USERS", "u1:p")
    with pytest.raises(SystemExit):
        asyncio.run(wl.run_ws("http://127.0.0.1:1", connections=10, duration_s=1, stalled=1, per_user=5, rcvbuf=None))
