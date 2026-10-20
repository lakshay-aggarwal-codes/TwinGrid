# Task 6 — SEC-001 plan

Files touched (all owned, §6): `src/optimizer.py` (`JointOptimizer.load` only), `models/registry.json` (text of the five
`ppo-p1-e2-*` entries only), `tests/test_artifact_gate.py`. No change to `src/artifacts/*` or `src/model_registry.py` was needed.

Tests first: negative tests for the SB3 path (api profile, unregistered path, hash mismatch, quarantined, contract-before-gate),
a registry-truth test tied to `results.json`, and the evaluator path (`pe.load_candidates`) under the training profile.
Then: gate-first `JointOptimizer.load`; then the registry text; then re-pointing stale tests in the gate suite.

Commands: `pytest tests/test_artifact_gate.py tests/test_artifact_integrity.py`, neighbouring optimizer suites, `ruff check .`, `ruff format --check .`.
