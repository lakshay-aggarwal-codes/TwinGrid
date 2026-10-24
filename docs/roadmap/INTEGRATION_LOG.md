# Integration log

> **Superseded in part (2026-10-24, L4).** This log records the 2026-10-21 integration wave. Since then the owner ran the full backend suite: 5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed (`C:\twlogs\pytest_full_final.txt`). In particular: `tests/test_authz_matrix.py` no longer fails at collection (183 tests pass); the four "open issues found by this wave" are fixed and their xfails removed (the 9 remaining xfails are a different defect, L1); and the "Pre-existing failures, unchanged" file list passes (see `failure-ledger.csv`, column `last_verified`). Still not run: the Postgres suite, Alembic against a database, Playwright, `pip-audit`, `npm audit`, TensorFlow-dependent tests.

## Wave: Tasks 24, 11, 25 on the uploaded `TwinGrid-main.zip` (Tasks 1-10, 12-18 already present)          Date: 2026-10-21

Patches were task ZIPs, applied by overlay in the card's order (backend core, then frontend, then QA): **24 -> 11 -> 25**.
Environment: Python 3.12.3 venv with real `pytest`, `fastapi`, `sqlalchemy`, `ruff`; Node with `npm ci` from the lockfile.
**No** TensorFlow/torch, Docker, Postgres or browser. `reports/baseline-2026-10/` holds only `check_register.txt` (no test counts), so
the baseline was **measured here on the pristine upload** with exactly the same commands.

### Patches applied
| Task | New files | Modified existing files | Overlap with another patch |
|---|---|---|---|
| 24 LLM adapter | `src/copilot/llm.py`, `tests/test_copilot_llm.py`, `tests/copilot_conftest_plugin.py`, `docs/env/T24.md`, report | `src/copilot/answer.py`, `src/copilot/__init__.py`, `.env.example` (append block) | none |
| 11 Visitor UX | `src/features/access/*`, `DemoBanner*`, `LoginScreen.access.test.tsx`, `authClient.demo.test.ts`, `publicRoutes.test.ts`, `contract/fixtures-access/`, `docs/roadmap/task-scripts/task_11_*.sh`, report | `App.tsx`, `authClient.ts`, `AuthGate.tsx`, `LoginScreen.tsx`, `features/registry.ts`, `hooks/useAuth.ts` | none |
| 25 AI-D suite | `tests/test_copilot_adversarial.py`, `tests/fixtures/copilot_adversarial/*`, `e2e/assistant.spec.ts`, `docs/copilot/LIMITS.md`, report | none | none |

No conflicts. The only append block (`.env.example`) came from Task 24 alone, so there was nothing to merge. No ownership breach.

### Reconciliation (the files this integration changed)
| File | Change | Why |
|---|---|---|
| `pytest.ini` | add marker `live_llm` | Task 24's requested change; its plugin already deselects live tests (observed: 1 deselected under real pytest) |
| `src/copilot/signal_adapter.py` | remove the `ImportError` fallback; import `src.signal_state` directly; guard is `rule is None` only | card step 3: Task 16 is merged |
| `tests/test_copilot_tools.py`, `tests/test_copilot_answer.py` | rewrite the two tests that asserted the pre-Task-16 behaviour ("`evaluate is None`", "every status is unknown") | they said "this test marks the day it does [exist]"; they now assert the engine resolves, a fresh in-bounds signal is `normal` / `within_bounds`, and no rule or no value is still `unknown` |
| `src/copilot/answer.py`, `src/copilot/llm.py`, `tests/test_copilot_llm.py` | `ruff format` only | Task 24 reported it never ran ruff |
| `twin-stream-insight-main/src/features/access/ActivatePage.test.tsx` | one test: look the form up once | the helper finds the form by the button name `/activate/`; after the first submit the button correctly reads "Activating…", so the second lookup threw. Test bug, component is correct. **Task 11's owner should confirm.** |

### Gate results (same commands on the pristine base and on the integrated tree)
| Gate | Base | Integrated |
|---|---|---|
| `alembic heads` | 1 head `20261101000000` | 1 head `20261101000000` |
| `pytest tests -m "not postgres"` (no TF/PG/Docker) | 4856 passed, 82 failed, 13 errors, 78 skipped | **4993 passed**, 81 failed, 13 errors, 78 skipped, 5 xfailed |
| failing test ids | 95 | 94: 2 fixed (the stale Task 14 tests), 1 appears only in the integrated run and is **not a regression** (below) |
| `test_startup_checks`, `test_alembic_chain`, `test_ci_gates` | n/a | 68 passed |
| all `tests/test_copilot_*` incl. Tasks 24 and 25 | n/a | 198 passed, 1 deselected (live provider), 4 xfailed |
| frontend `typecheck` | 19 errors | the **same 19** (identical set, none in Task 11 files) |
| frontend `lint:ci` | 4 warnings | the **same 4** |
| frontend `vitest run` | 4 failed, 2207 passed (2221) | 5 failed, 2300 passed (2315) before reconciliation; the one extra failure was fixed above and `src/features/access` re-run: 5 files, 69 passed. **The full suite was not re-run after that fix.** |
| frontend `build` | ok | ok (needs `VITE_API_BASE_URL` and `VITE_ERROR_REPORT_URL`; without them the env guard stops the build, by design) |
| `ruff check` (`src`, copilot tests) | clean | clean |
| `ruff format --check` (`src`, copilot tests) | 1 file: `src/policy_evaluation.py` | the same single file |

**The one backend id new in the integrated run**, `tests/test_runtime_fanout.py::test_two_hundred_clients_one_stalled_everyone_else_gets_every_frame_in_order`, also fails on the pristine base when run alone (1 failed, 16 passed, twice on the integrated tree, once on the base). It passed in the full base run. It is a load-sensitive existing test, not caused by these patches.

### Pre-existing failures, unchanged (not caused by this wave)
- Backend, by file: `test_anomaly_detector` 14, `api/test_error_contract` 14, `test_artifact_gate` 12, `test_task7_observability` 5, `test_load_harness` 5, `api/test_provenance_writers` 5, `test_task9_api_reference` 4, `test_facility_migration` 4, `characterization/test_route_contracts_and_targets` 4, plus a long tail. Many are probably this sandbox (no TF or Postgres), but that was **not** verified per test.
- Frontend: `AssistantDrawer.test.tsx` "stale evidence is flagged distinctly and never reads as normal", `LabPage.test.tsx` "saves a scenario…", and two in `what-if-lab/logic.test.ts`.
- **`tests/test_authz_matrix.py` fails at collection**: `T13.yaml routes[0] POST /auth/demo-session: anonymous must be '401' or 'public'`. Changing that word is not enough: the fragment also uses a `demo` column the Task 3 loader does not know and rows without `anonymous/viewer/operator/admin`. I tried it and reverted. Until the owners (3, 13) agree the schema, **the matrix, including Task 9 and Task 14 fragments, is not enforced**.

### Open issues found by this wave (each is pinned by a strict xfail in `tests/test_copilot_adversarial.py`)
1. `api/demo_guard.py` (T13): `POST /api/copilot/ask` is not in `ALLOWED_DEMO_WRITES`, so the public demo gets 403 from the assistant.
2. `api/plugins/copilot.py` (T14): `load_signal` filters `quality == "good"`; the schema has only `ok` / `invalid`, so no signal is ever found.
3. `api/plugins/copilot.py` (T14): alert id `"²"` passes `isdigit()` then `int()` raises, HTTP 500.
4. `src/signal_state.evaluate` (T16): a future-dated sample is `normal` / `within_bounds`.

### Not run
Postgres suite (no Postgres), `alembic upgrade head / check / downgrade base` against a database, `pip-audit`, `npm audit`, Playwright (`assistant.spec.ts` and every other e2e), Task 11's UI at 320 px, the live-provider test, TensorFlow-dependent tests.

### Follow-ups now possible
- **Task 25 (extension):** Task 24 is merged, so the fake-LLM mode of invariants 1-9 can be added; invariant 8 should also assert the `llm_unavailable` / `llm_rejected` warnings. (Today's check for it only proves the env vars cannot break the rule-based path.)
- **Unblocked by dependencies:** Task 22 (needs 9-13: all present now; needs Docker and a browser), Task 28 (11, 12, 15, 16), Task 21 (4-7), Task 23 (8, 16). Task 27 still waits for 22.
