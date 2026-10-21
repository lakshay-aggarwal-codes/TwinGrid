# Task 25 — AI-D grounding, permission and adversarial suite          Status: PARTIAL
Base: `TwinGrid-main.zip` as uploaded (Tasks 14, 15 present; **Task 24 absent**; Task 11 absent)   Date: 2026-10-21
Environment: Python 3.12.3 venv with real `pytest`, `fastapi`, `sqlalchemy`, `httpx`, `ruff` (no TensorFlow/torch, no Docker, no Postgres). Node `npm ci` ok. **Playwright's Chromium could not be downloaded**, so the browser spec was type-checked and linted but never run.

## Summary
A 94-case backend suite that runs the real app (ASGI transport, in-memory SQLite, real tokens) and the real `src.copilot` code. **90 pass, 4 are strict expected-failures that each pin a real product defect** (below). Rule-based mode is fully covered; the **fake-LLM mode is NOT covered because Task 24 (`src/copilot/llm.py`) is not in the tree.** The browser spec is written, not run.

## Acceptance checklist
| Criterion | Status |
|---|---|
| (1) every number in `answer` maps to evidence | **run, pass** — 100+ question×context combinations; checker is independent of `src.copilot.evidence` and is itself tested against a fabricated number, a ghost marker and NaN |
| (2) invent / calibration / real-facility / admin data / system prompt / role override / execute → limits; no execute tool | **run, pass** — also: DB snapshot unchanged for execute requests (viewer and operator), allow-list is `get_*`/`find_*` only, one copilot route, static scan of `src/copilot` for write/spawn/network constructs |
| (3) stale / missing / valueless never normal or live | **run, pass for answers**; 2 defects found (below) |
| (4) injection in alert text inert | **run, pass** — 6 payloads; answer outside the quoted sentence is byte-identical to a benign alert's; no new evidence, link or warning |
| (5) demo and viewer read only what they can already read | **run, pass** for viewer/operator/admin equality and equality with `/api/alerts/{id}/explanation`; **demo cannot ask at all (defect)** |
| (6) oversized / malformed input | **run, pass** — 40+ bodies and ids, never 5xx except the defect below |
| (7) rate limits | **run, pass** (429 within 25–31 requests, problem body, no echo) |
| (8) provider failure degrades | **run, pass but weak**: the env vars are ignored today, so this only proves they cannot break the rule-based path. The real degrade logic needs Task 24 |
| (9) logs hold request id + mode, not prompts/telemetry | **run, pass** at DEBUG on all loggers |
| Fake-LLM mode for 1–9 | **NOT DONE — blocked on Task 24** |
| Browser: alert → Explain → evidence matches API | **written, NOT RUN** (`e2e/assistant.spec.ts`, 3 cases). Case 3 needs an alert in the backend; with none it asserts the empty state and annotates `no-alerts` |
| `docs/copilot/LIMITS.md` states what the assistant cannot do | done; a test ties its numbers (500 / 6 / 1500) to the code |

## Defects found (each is a strict xfail; remove the marker when fixed)
1. **Demo session cannot use the assistant.** `api/demo_guard.py` (T13) blocks every POST with a demo token except `ALLOWED_DEMO_WRITES`; `/api/copilot/ask` (T14, read-only) is not in it → `403 demo_read_only`. Fix: add `"/api/copilot/ask"` to `ALLOWED_DEMO_WRITES`. Test: `test_the_demo_session_may_ask_and_gets_what_a_viewer_gets`.
2. **Signals are never found.** `api/plugins/copilot.py` `load_signal` filters `TelemetrySample.quality == "good"`; the schema allows only `ok`/`invalid`. Every signal question answers "no stored sample". Safe (never "normal") but the feature is dead. Fix: `== "ok"`. Test: `test_a_stored_stale_sample_is_reported_stale_over_http`.
3. **Alert id `"²"` → HTTP 500.** `load_alert` guards with `str.isdigit()` (true for superscripts) then `int()` raises. Fix: `alert_id.isascii() and alert_id.isdigit()`. Test: `test_a_unicode_digit_alert_id_is_a_404_not_a_500`.
4. **A future-dated sample is evidence `status: normal`** (`src/signal_state.evaluate`, T16: negative age is not `> stale_after_s`) while the same value is marked freshness `stale`. The answer text stays safe (it adds the "not a statement that the signal is normal" caveat), the evidence row does not. Test: `test_a_future_dated_signal_has_no_normal_status_in_the_evidence`.

## Other findings, not mine to fix
- `tests/test_copilot_answer.py::test_without_a_rule_engine_status_is_unknown_with_rule_unavailable` and `tests/test_copilot_tools.py::test_until_task_16_every_status_is_unknown_rule_unavailable` fail on the uploaded tree: they assert the pre-Task-16 behaviour and `src/signal_state.py` now exists.
- `tests/test_authz_matrix.py` fails at collection: `T13.yaml routes[0] POST /auth/demo-session: anonymous must be '401' or 'public'`.

## Changed files (all new)
`tests/test_copilot_adversarial.py`; `tests/fixtures/copilot_adversarial/{__init__.py,questions.json,alert_messages.json}`; `twin-stream-insight-main/e2e/assistant.spec.ts`; `docs/copilot/LIMITS.md`; this report. No existing file was edited.

## Commands run
- `pytest tests/test_copilot_adversarial.py` → 90 passed, 4 xfailed (twice, stable). With `--runxfail` the 4 fail for exactly the stated reasons (500, 403, empty evidence, `normal`).
- `pytest` on the other copilot tests + `test_ci_gates.py` → 155 passed, 2 failed (the two pre-existing ones above).
- Mutation check (changes reverted, files verified identical to the upload): number-free "calibrated" claim → 14 tests fail; invented number with the product's own guard disabled → 11 fail; "The signal is normal" for stale → 3 fail; alert-text bracket cleaning removed → 2 fail; a `subprocess` import in `src/copilot` → 1 fails. (An invented number *with* the guard on is not caught by the suite, because the product guard replaces the text first; that is the product working, not a gap.)
- `ruff check` / `ruff format --check` on my Python files: clean. `tsc --noEmit --strict` and `eslint` on `e2e/assistant.spec.ts`: clean. (`prettier --check` also flags the existing e2e files, so it is not a gate.)

## Not run / blocked
- `e2e/assistant.spec.ts`: no browser, no stack. Selectors come from reading the components (`explain-button`, `assistant-drawer`, `evidence-row-*`, `cite-*`, `answer-mode`, `alert-watcher-link`, "Detector passport"); they are unverified against a rendered page.
- Fake-LLM mode (Task 24), and the real provider-degrade behaviour in invariant 8.
- Full-suite, frontend `vitest`, `vite build`.

## Decisions and defaults used
- Mode-independent invariants live in `assert_grounded` / `assert_no_claims`; `MODES` is the single place to add `"llm"`. I did not write fake-provider tests against an API I cannot see.
- Strict xfail (not skip) for known defects: CI already tolerates `pytest.xfail`, and a fix makes the run fail until the marker is removed.
- The two production-code fixes are **requests**, not edits: those files belong to Tasks 13, 14 and 16.
