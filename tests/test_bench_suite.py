"""Task 19: the measurement suite is honest. Pure stdlib/numpy; the API section is exercised against a local stub server."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bench_suite", ROOT / "scripts" / "bench_suite.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)


def test_summarise_is_exact_on_a_known_sample():
    s = bs.summarise([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert s["n"] == 10 and s["median"] == 5.5 and s["min"] == 1.0 and s["max"] == 10.0
    assert s["iqr"] == pytest.approx(4.5) and s["p95"] == 10.0 and s["mean"] == 5.5
    with pytest.raises(ValueError):
        bs.summarise([1.0])


def test_fewer_than_twenty_repeats_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        bs.main(["--sections", "twin", "--repeats", "19", "--out", str(tmp_path / "x.json")])


def test_unknown_sections_are_refused(tmp_path):
    with pytest.raises(SystemExit):
        bs.main(["--sections", "tune", "--out", str(tmp_path / "x.json")])


def test_day_actions_are_deterministic_and_cover_one_day():
    a, b = bs.day_actions(20.0), bs.day_actions(20.0)
    assert a == b and len(a) == 288 and all(x["chilled_water_temp_C"] == 20.0 for x in a)


def test_twin_section_measures_and_writes_the_documented_schema(tmp_path):
    out = tmp_path / "b.json"
    assert bs.main(["--sections", "twin", "--repeats", "20", "--warmup", "0", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "twingrid-bench/1" and doc["protocol"]["repeats"] == 20
    twin = doc["sections"]["twin"]
    assert twin["status"] == "measured"
    for key in ("physics_legacy-0", "physics_1"):
        assert twin[key]["seconds"]["n"] == 20 and twin[key]["seconds"]["median"] > 0


def test_a_section_that_cannot_run_is_recorded_with_its_reason_not_filled_in(tmp_path):
    class A:
        warmup, repeats, api_url, api_interval_s = 0, 20, None, 0.0

    res = bs.run_section("api", A)
    assert res["status"] == "skipped" and "no --api-url" in res["reason"] and "seconds" not in json.dumps(res)


class _Stub(BaseHTTPRequestHandler):
    throttled_once: set = set()

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({"access_token": "tok", "role": "viewer"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/scenarios" and "once" not in _Stub.throttled_once:
            _Stub.throttled_once.add("once")
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/api/evaluations" and self.headers.get("Authorization") != "Bearer tok":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b'{"ok":true}' * 50
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_api_section_times_200s_counts_429s_and_reports_unmeasurable_endpoints(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.delenv("TWINGRID_USERNAME", raising=False)
        monkeypatch.delenv("TWINGRID_PASSWORD", raising=False)
        res = bs.bench_api(1, 20, f"http://127.0.0.1:{server.server_port}", 0.0)
    finally:
        server.shutdown()
    eps = res["endpoints"]
    assert res["authenticated"] is False
    assert eps["/api/state"]["latency"]["seconds"]["n"] == 20
    assert eps["/api/state"]["payload_bytes"]["identity"]["median"] == 550
    assert eps["/api/scenarios"]["throttled_429"] == 1 and eps["/api/scenarios"]["latency"]["seconds"]["n"] == 20
    assert eps["/api/evaluations"]["status"] == "not_measured" and "latency" not in eps["/api/evaluations"]


def test_credentials_never_appear_in_the_output(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("TWINGRID_USERNAME", "benchuser")
    monkeypatch.setenv("TWINGRID_PASSWORD", "s3cret-bench-password")
    try:
        res = bs.bench_api(0, 20, f"http://127.0.0.1:{server.server_port}", 0.0)
    finally:
        server.shutdown()
    text = json.dumps(res)
    assert res["authenticated"] is True and "s3cret-bench-password" not in text and "benchuser" not in text
    assert res["endpoints"]["/api/evaluations"]["latency"]["seconds"]["n"] == 20


def test_peak_memory_probe_returns_a_positive_number_or_none():
    v = bs.peak_rss_mb()
    assert v is None or v > 0
