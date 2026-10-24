# R_L2: Optimized twin retired (TG-A-05) and dead markers cleaned

**Verdict: DONE** (owner's run, 2026-10-24). Decision D1 = retire (default).

## State found in the tree (read, not changed in this step)
- `src/digital_twin_optimized.py` is absent. `docs/audit/TwinGrid_Issue_Register.md`: TG-A-05 = RESOLVED-BY-REMOVAL.
- No `xfail` is left in `tests/` (`tests/test_audit_regressions.py` has none).
- `tests/characterization/test_route_contracts_and_targets.py` no longer defines `target(task_id)`.
- Remaining mentions of the module are guards or history only: `tests/test_task22_register_consistency.py:46` and `tests/test_physics_v1_invariants.py:773` assert the file stays absent; `tests/test_time_contract.py:365` is a comment; docs (`PERFORMANCE_OPTIMIZATION.md`, audit and architecture docs) refer to it as retired.

## Evidence (pasted by the owner)
- `pytest tests -q -k "audit_regressions or physics_v1 or time_contract or register_consistency or route_contracts"`: **835 passed, 1 skipped**, 4943 deselected.
- `ruff check .`: All checks passed. `ruff format --check .`: 442 files already formatted.

## Open / limit
- The 1 skip is in `tests/test_time_contract.py` (the Postgres round-trip, "set TWINGRID_TEST_PG_URL"). That run was made without `-rs` and without the Postgres env vars, so the reason is inferred, not shown. With `TWINGRID_TEST_PG_URL` set, the same file passed in the L6 Postgres run (77 passed, 3 skipped).
