# Digital Twin Performance Notes

> **Status (deep audit, 2026-10-18).** The earlier version of this file claimed "45 s -> 0.003 s, 1,360x". That claim was not reproducible and referred to modules (`src.digital_twin_fast`, `src.digital_twin_original`) that do not exist. It has been removed. Everything below was measured with `benchmark_performance.py` on one Linux sandbox (Python 3.12.3, NumPy 2.4.4, no numba installed), one run, no warm-up control. Treat it as indicative, not as a benchmark.

## What was measured (288 steps = one simulated day, the benchmark's own inputs)

| Implementation | Wall time (one run) | Note |
|---|---|---|
| `DigitalTwin` (legacy-0) | ~3.3 ms | the main simulator |
| `DigitalTwin` (physics 1) | ~3.7 ms | the default for new work |
| `DigitalTwinOptimized` | ~1.1 ms | **not numerically equivalent** (below) |

The main simulator already steps a whole simulated day in a few milliseconds; speed is not a bottleneck for the dashboard.

## Correctness caveat

`DigitalTwinOptimized` does **not** reproduce `DigitalTwin`: on the benchmark inputs the outlet temperature differs by up to ~20 C and PUE by up to ~0.10 versus legacy-0. A speed-up that changes the answer is not an optimisation. The module is used only by the benchmark and two tests. Until it is fixed or retired, do not use it for results. `tests/test_audit_regressions.py::test_optimized_twin_matches_the_main_twin_on_the_benchmark_inputs` is a strict xfail that records this.

## Not measured

RL training/evaluation throughput, API latency, frontend rendering and 3D scene cost, and database queries have no recorded measurements in this repository. `docs/CLAIMS.md` (C-20) lists the performance claims backed by a script.
