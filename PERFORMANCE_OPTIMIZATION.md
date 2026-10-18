# Digital Twin Performance Notes

There is one simulator, `src/digital_twin.py::DigitalTwin`. The former "optimised" twin
(`src/digital_twin_optimized.py`) was **retired** in Task 5 because it was a different, older model rather than a faster
copy of this one (`docs/tasks/Task5_TWIN_PARITY_REPORT.md`). The earlier claims "45 s -> 0.003 s, 1,360x" were never
reproducible and have been removed.

## Protocol (`python benchmark_performance.py [--repeats 30] [--json out.json]`)

288 steps = one simulated day on the pinned inputs of `generate_test_actions()`; 3 untimed warm-up days; at least 20
(default 30) timed days, each on a fresh twin (construction not timed); `time.perf_counter`; median, IQR, min, max.
The environment is printed with every result. Numbers from different machines must not be compared.

## Measured on the owner's machine (one run of the protocol above, 30 timed days)

Environment: Windows 11 (AMD64, AMD Family 25 Model 97, 32 logical CPUs), Python 3.12.10, NumPy 2.5.3.

| Twin | Median per day | IQR | Median per step |
|---|---|---|---|
| `DigitalTwin` physics legacy-0 | 2.518 ms | 0.033 ms | 8.7 us |
| `DigitalTwin` physics 1 | 2.778 ms | 0.034 ms | 9.6 us |

A simulated day costs a few milliseconds, so speed is not a bottleneck for the dashboard or the evaluation harness.
For reference, an earlier single run in a 1-vCPU Linux sandbox gave 5.8 / 6.6 ms/day (different hardware; do not
mix the two). The retired module measured about 3.0 ms/day there, i.e. at most ~2x faster, for different physics.

## Not measured

RL training/evaluation throughput, API latency, frontend rendering and 3D scene cost, and database queries have no
recorded measurements here. `docs/CLAIMS.md` (C-20) lists the performance claims backed by a script.
