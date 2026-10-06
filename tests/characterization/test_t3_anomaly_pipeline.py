"""T3: server-owned anomaly scoring, fail-closed statuses, one alert per episode, webhook gating.

A scripted FAKE detector is injected (no TensorFlow needed); the pipeline, window provider,
repository and database are real (in-memory SQLite via the shared ``session_maker`` fixture).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from unittest import mock

import pytest
from sqlalchemy import select

import api.services.anomaly_service as svc
import api.services.live_broadcast_service as lbs
import api.services.telemetry_window as tw
from api.services import webhook_service
from models.db_models import Alert
from tests.characterization import golden_support as gs

THRESHOLD = 0.01


class ScriptedDetector:
    """detect() returns scripted scores: a list of floats consumed one per call (last one repeats)."""

    threshold = THRESHOLD

    def __init__(self, scores, raises: Exception | None = None, delay: float = 0.0):
        self.scores, self.raises, self.delay, self.calls = list(scores), raises, delay, 0

    def detect(self, arr):
        import time

        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.raises:
            raise self.raises
        score = self.scores.pop(0) if len(self.scores) > 1 else self.scores[0]
        return [score], [score > THRESHOLD]


@pytest.fixture
def pipeline_env(session_maker, monkeypatch):
    """Fresh window + pipeline, deterministic model version, stubbed explain, real DB sessions."""
    monkeypatch.setenv("ANOMALY_SERVER_SIDE", "true")
    # T17: these tests characterize the T3 pipeline fed from the in-memory ring buffer (the rollback source);
    # the store-backed window has its own tests in tests/test_telemetry_window.py.
    monkeypatch.setenv("TELEMETRY_WINDOW_SOURCE", "memory")
    monkeypatch.setattr(tw, "_provider", tw.InMemoryTelemetryWindow())
    monkeypatch.setattr(svc, "_pipeline", svc.AnomalyPipeline(close_after=3))
    monkeypatch.setattr(svc, "get_model_version", lambda: "sha256-testmodel01")
    monkeypatch.setattr(svc, "explain", lambda det, arr: [{"top_feature": "server_outlet_temp_C"}])

    @asynccontextmanager
    async def factory():
        async with session_maker() as s:
            yield s

    return factory


def use_detector(monkeypatch, det):
    monkeypatch.setattr(svc, "_anomaly_detector", det)
    monkeypatch.setattr(svc, "get_anomaly_detector", lambda: det)


def feed(seq: int, origin: str = "simulated", **over):
    state = {
        "water_flow_lpm": 50.0,
        "water_pressure_bar": 3.0,
        "server_outlet_temp_C": 30.0,
        "it_power_kw": 300.0,
        "humidity_pct": 50.0,
    }
    state.update(over)
    tw.get_window_provider().append(
        tw.sample_from_state(state, seq=seq, ts_ingest="2026-01-01T00:00:00+00:00", origin=origin)
    )


async def step(factory, seq, **kw):
    feed(seq, **kw)
    return await svc.get_pipeline().process(session_factory=factory)


async def alerts(session_maker):
    async with session_maker() as s:
        return list((await s.execute(select(Alert).order_by(Alert.id))).scalars())


async def warm(factory, n=11, origin="simulated"):
    for i in range(1, n + 1):
        r = await step(factory, i, origin=origin)
        assert r["status"] == "warming_up"


# ------------------------------------------------------------------------------- window / warm-up
async def test_warming_up_until_twelve_samples_and_no_scoring(pipeline_env, monkeypatch):
    det = ScriptedDetector([0.5])
    use_detector(monkeypatch, det)
    for i in range(1, 12):
        r = await step(pipeline_env, i)
        assert r["status"] == "warming_up" and r["window_filled"] == i and r["window_size"] == 12
    assert det.calls == 0
    r = await step(pipeline_env, 12)
    assert r["status"] != "warming_up" and det.calls == 1


def test_window_provider_returns_last_n_oldest_first_and_is_bounded():
    w = tw.InMemoryTelemetryWindow(capacity=20)
    for i in range(30):
        w.append(
            tw.sample_from_state({k: float(i) for k in tw.FEATURE_ORDER}, seq=i, ts_ingest="t", origin="simulated")
        )
    got = w.window(12)
    assert [s.seq for s in got] == list(range(18, 30)) and len(w) == 20
    assert len(w.window(100)) == 20 and w.window(0) == []


def test_feature_order_matches_the_trained_model_config():
    import json

    cfg = json.loads((gs.REPO_ROOT / "models" / "anomaly" / "config.json").read_text())
    assert list(tw.FEATURE_ORDER) == cfg["feature_columns"]


def test_lowest_evidence_origin():
    assert tw.lowest_evidence_origin(["simulated", "simulated"]) == "simulated"
    assert tw.lowest_evidence_origin(["measured", "simulated"]) == "simulated"
    assert tw.lowest_evidence_origin([]) == "unknown"


# ------------------------------------------------------------------------------- statuses
async def test_normal_window_is_ok_with_score_and_unchanged_threshold(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.001]))
    await warm(pipeline_env)
    r = await step(pipeline_env, 12)
    assert r["status"] == "ok" and r["score"] == 0.001 and r["threshold"] == THRESHOLD
    assert r["model_version"] == "sha256-testmodel01" and r["trained_on"] == "synthetic"
    assert r["detector_id"] == "lstm_autoencoder" and r["origin"] == "simulated" and r["seq"] == 12
    assert r["episode"]["open"] is False
    assert await alerts(session_maker) == []


async def test_missing_detector_is_unavailable_never_normal(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, None)
    await warm(pipeline_env)
    r = await step(pipeline_env, 12)
    assert r["status"] == "unavailable" and r["score"] is None and r["type"] != "normal"


async def test_detector_exception_is_error_not_normal_and_creates_no_alert(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.0], raises=RuntimeError("boom")))
    before = svc.ANOMALY_SCORING_ERRORS._value.get()
    await warm(pipeline_env)
    for i in range(12, 16):
        r = await step(pipeline_env, i)
        assert r["status"] == "error" and "boom" in r["message"] and r["type"] == "error"
    assert await alerts(session_maker) == []
    assert svc.ANOMALY_SCORING_ERRORS._value.get() == before + 4


async def test_non_finite_window_is_error(pipeline_env, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.5]))
    await warm(pipeline_env)
    r = await step(pipeline_env, 12, water_flow_lpm=float("nan"))
    assert r["status"] == "error"


async def test_slow_scoring_times_out_to_error_and_blocks_overlap(pipeline_env, monkeypatch):
    det = ScriptedDetector([0.0], delay=0.4)
    use_detector(monkeypatch, det)
    monkeypatch.setenv("ANOMALY_SCORE_TIMEOUT_S", "0.05")
    await warm(pipeline_env)
    r1 = await step(pipeline_env, 12)
    assert r1["status"] == "error" and "timed out" in r1["message"]
    r2 = await step(pipeline_env, 13)  # first scoring still in its worker thread
    assert r2["status"] == "error" and "still running" in r2["message"]
    assert det.calls == 1
    await asyncio.sleep(0.6)
    monkeypatch.setenv("ANOMALY_SCORE_TIMEOUT_S", "2")
    r3 = await step(pipeline_env, 14)
    assert r3["status"] == "ok" and det.calls == 2


async def test_server_side_flag_off_reports_unavailable(pipeline_env, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.5]))
    monkeypatch.setenv("ANOMALY_SERVER_SIDE", "false")
    r = await step(pipeline_env, 1)
    assert r["status"] == "unavailable" and "disabled" in r["message"]


# ------------------------------------------------------------------------------- episodes
async def test_sustained_anomaly_creates_exactly_one_alert_with_identity(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.5]))  # 50x threshold, repeats
    await warm(pipeline_env)
    statuses = [(await step(pipeline_env, i, server_outlet_temp_C=60.0))["status"] for i in range(12, 22)]
    assert statuses == ["anomalous"] * 10
    rows = await alerts(session_maker)
    assert len(rows) == 1
    a = rows[0]
    assert a.dedupe_key == "lstm_autoencoder:sha256-testmodel01:12"
    assert a.model_version == "sha256-testmodel01" and a.origin == "simulated"
    assert a.type == "thermal_spike" and a.severity == "CRITICAL" and a.alert is True
    assert svc.get_pipeline().snapshot()["episode"]["alert_id"] == a.id


async def test_episode_closes_after_k_normals_then_new_episode_gets_new_alert(pipeline_env, session_maker, monkeypatch):
    # anomalous x2, normal x3 (close), anomalous x2 (new episode)
    use_detector(monkeypatch, ScriptedDetector([0.05, 0.05, 0.001, 0.001, 0.001, 0.05, 0.05]))
    await warm(pipeline_env)
    seen = [(await step(pipeline_env, i))["status"] for i in range(12, 19)]
    assert seen == ["anomalous", "anomalous", "ok", "ok", "ok", "anomalous", "anomalous"]
    rows = await alerts(session_maker)
    assert [r.dedupe_key.rsplit(":", 1)[1] for r in rows] == ["12", "17"]


async def test_brief_normal_dip_does_not_split_an_episode(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.05, 0.001, 0.05, 0.05]))
    await warm(pipeline_env)
    for i in range(12, 16):
        await step(pipeline_env, i)
    assert len(await alerts(session_maker)) == 1


async def test_severity_escalation_updates_the_existing_alert(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.015, 0.05, 0.015]))  # WARNING, CRITICAL, then lower
    await warm(pipeline_env)
    for i in (12, 13, 14):
        await step(pipeline_env, i)
    rows = await alerts(session_maker)
    assert len(rows) == 1 and rows[0].severity == "CRITICAL" and rows[0].score == 0.05  # never de-escalated


async def test_error_during_episode_neither_closes_nor_duplicates_it(pipeline_env, session_maker, monkeypatch):
    det = ScriptedDetector([0.05])
    use_detector(monkeypatch, det)
    await warm(pipeline_env)
    await step(pipeline_env, 12)
    det.raises = RuntimeError("transient")
    for i in range(13, 20):  # more than K error windows
        assert (await step(pipeline_env, i))["status"] == "error"
    det.raises = None
    assert (await step(pipeline_env, 20))["status"] == "anomalous"
    assert len(await alerts(session_maker)) == 1


async def test_outage_creates_one_detector_unavailable_alert_per_outage(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, None)
    await warm(pipeline_env)
    for i in range(12, 18):
        assert (await step(pipeline_env, i))["status"] == "unavailable"
    rows = await alerts(session_maker)
    assert len(rows) == 1 and rows[0].type == "detector_unavailable" and rows[0].severity == "WARNING"
    assert rows[0].dedupe_key == "lstm_autoencoder:unavailable:12" and rows[0].model_version is None
    use_detector(monkeypatch, ScriptedDetector([0.001]))  # recovers
    assert (await step(pipeline_env, 18))["status"] == "ok"
    use_detector(monkeypatch, None)  # second outage
    await step(pipeline_env, 19)
    assert len(await alerts(session_maker)) == 2


async def test_persistence_failure_is_retried_idempotently(pipeline_env, session_maker, monkeypatch):
    use_detector(monkeypatch, ScriptedDetector([0.05]))
    await warm(pipeline_env)

    @asynccontextmanager
    async def broken():
        raise RuntimeError("db down")
        yield

    feed(12)
    r = await svc.get_pipeline().process(session_factory=broken)
    assert r["status"] == "anomalous" and r["episode"]["alert_id"] is None
    assert await alerts(session_maker) == []
    for i in (13, 14):
        await step(pipeline_env, i)  # DB back: retried under the SAME key
    rows = await alerts(session_maker)
    assert len(rows) == 1 and rows[0].dedupe_key.endswith(":12")


# ------------------------------------------------------------------------------- webhook gating
async def _run_with_webhooks(pipeline_env, monkeypatch, origin):
    sent = []

    async def fake_post(url, payload):  # not used: we replace dispatch's transport below
        sent.append((url, payload))

    monkeypatch.setattr(webhook_service, "list_subscribers", lambda: ["http://example.invalid/hook"])
    monkeypatch.setattr(webhook_service, "_post_one", lambda url, payload: sent.append((url, payload)) or 200)
    use_detector(monkeypatch, ScriptedDetector([0.05]))
    await warm(pipeline_env, origin=origin)  # the WHOLE window carries this origin
    feed(12, origin=origin)
    await svc.get_pipeline().process(session_factory=pipeline_env)
    await asyncio.gather(*list(svc.get_pipeline().pending))
    return sent


async def test_simulated_alerts_do_not_fire_webhooks_by_default(pipeline_env, monkeypatch):
    monkeypatch.delenv("WEBHOOK_ON_SIMULATED", raising=False)
    assert await _run_with_webhooks(pipeline_env, monkeypatch, "simulated") == []


async def test_webhook_on_simulated_opt_in(pipeline_env, monkeypatch):
    monkeypatch.setenv("WEBHOOK_ON_SIMULATED", "true")
    sent = await _run_with_webhooks(pipeline_env, monkeypatch, "simulated")
    assert len(sent) == 1 and sent[0][1]["origin"] == "simulated" and sent[0][1]["dedupe_key"].endswith(":12")


async def test_non_simulated_origin_fires_webhook(pipeline_env, monkeypatch):
    monkeypatch.delenv("WEBHOOK_ON_SIMULATED", raising=False)
    sent = await _run_with_webhooks(pipeline_env, monkeypatch, "measured")
    assert len(sent) == 1


def test_gating_helper():
    assert webhook_service.webhook_allowed_for_origin("measured") is True
    with mock.patch.dict(os.environ, {"WEBHOOK_ON_SIMULATED": "false"}):
        assert webhook_service.webhook_allowed_for_origin("simulated") is False
    with mock.patch.dict(os.environ, {"WEBHOOK_ON_SIMULATED": "true"}):
        assert webhook_service.webhook_allowed_for_origin("simulated") is True


# ------------------------------------------------------------------------------- _tick integration
async def test_tick_runs_pipeline_once_per_tick_independent_of_clients(session_maker, monkeypatch):
    """Many connected clients + many ticks => the pipeline scores once per tick and one alert total."""
    det = ScriptedDetector([0.05])
    monkeypatch.setattr(svc, "get_anomaly_detector", lambda: det)
    monkeypatch.setattr(svc, "get_model_version", lambda: "sha256-testmodel01")
    monkeypatch.setattr(svc, "explain", lambda d, a: [{"top_feature": "x"}])
    monkeypatch.setenv("WEBHOOK_ON_SIMULATED", "false")

    class Sock:
        def __init__(self):
            self.n = 0

        async def send_json(self, p):
            self.n += 1
            assert p["anomaly_status"]["status"] in {"warming_up", "anomalous"}

    @asynccontextmanager
    async def factory():
        async with session_maker() as s:
            yield s

    mgr = lbs.ConnectionManager()
    socks = [Sock() for _ in range(25)]
    for s in socks:
        mgr.connect(s)

    with gs.live_tick_environment():
        monkeypatch.setattr(lbs, "get_session", factory)
        payloads = []
        for _ in range(15):
            p = await lbs._tick()
            payloads.append(p)
            await mgr.broadcast(p)

    assert [p["anomaly_status"]["status"] for p in payloads] == ["warming_up"] * 11 + ["anomalous"] * 4
    assert det.calls == 4  # once per full-window tick, NOT 25x
    assert all(s.n == 15 for s in socks)
    rows = await alerts(session_maker)
    assert len(rows) == 1 and rows[0].origin == "simulated" and rows[0].sensor_reading_id is not None
    assert payloads[-1]["anomaly"] == 0  # the pre-existing twin flag is untouched
    assert payloads[-1]["anomaly_status"]["episode"]["alert_id"] == rows[0].id


async def test_tick_survives_pipeline_exception_with_error_status(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("pipeline bug")

    with gs.live_tick_environment():
        monkeypatch.setattr(svc.get_pipeline(), "process", boom)
        p = await lbs._tick()
    assert p["anomaly_status"]["status"] == "error" and "pue" in p


async def test_window_with_any_simulated_sample_is_labelled_simulated(pipeline_env, monkeypatch):
    """Lowest evidence wins: 11 simulated + 1 'measured' sample is still a simulated window."""
    monkeypatch.delenv("WEBHOOK_ON_SIMULATED", raising=False)
    use_detector(monkeypatch, ScriptedDetector([0.05]))
    await warm(pipeline_env)
    r = await step(pipeline_env, 12, origin="measured")
    assert r["origin"] == "simulated"
