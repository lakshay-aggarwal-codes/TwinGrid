"""Task 29: the latency summary is nearest-rank, never times a 429, and says when p99 is not a stable estimate."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "perf_endpoints", Path(__file__).resolve().parents[1] / "scripts" / "perf_endpoints.py"
)
pe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pe)


def test_nearest_rank_percentiles():
    values = [float(i) for i in range(1, 101)]
    assert pe.percentile(values, 50) == 50.0
    assert pe.percentile(values, 95) == 95.0
    assert pe.percentile(values, 99) == 99.0
    assert pe.percentile([7.0], 99) == 7.0


def test_summary_reports_ms_error_rate_and_counts_rate_limited_separately():
    out = pe.summarise([0.010, 0.020, 0.030, 0.040], [100, 200, 300, 400], attempts=10, rate_limited=4, errors=2)
    assert out["timed"] == 4 and out["rate_limited"] == 4 and out["errors"] == 2
    assert out["error_rate"] == 0.2  # 429 is not in the error rate
    assert out["p50_ms"] == 20.0 and out["max_ms"] == 40.0 and out["payload_bytes_median"] == 250
    assert "p99 is the maximum" in out["note"]


def test_summary_with_no_timed_requests_has_no_latency_numbers():
    out = pe.summarise([], [], attempts=3, rate_limited=0, errors=3)
    assert "p50_ms" not in out and out["error_rate"] == 1.0
