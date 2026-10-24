# R Task 2 report: future-dated samples must not read as normal

Status (L4, 2026-10-24): **DONE**. Verified by the owner's full run (5676 passed, 3 skipped, 81 deselected (postgres), 9 xfailed, 0 failed).

## Summary
`src/signal_state.evaluate` returned `normal` / `within_bounds` for a sample timestamped in the future. A timestamp more than `FUTURE_TOLERANCE_S` (5 s, clock skew) ahead of `now` is now `unknown` / `future` with no number and `age_s = None`. Up to 5 s ahead is still age 0 and judged normally. The TypeScript mirror and the shared fixture were changed to match.

## Acceptance checklist
- Pinned xfail `test_a_future_dated_signal_has_no_normal_status_in_the_evidence` removed and strengthened (status `unknown`, evidence `reason_code == future`, an unknowns line): met in source; NOT RUN under real pytest (see Not run).
- Test written first against the old behaviour: the old fixture case `observed_in_the_future_is_age_zero` expected `normal`; replaced by the cases below.
- Shared fixture: 36 cases (was 32), all pass in a plain-Python check of `evaluate`.

## Changed files
See manifest in the reply. Out-of-lane (Requested cross-task change, included so vitest stays green): `twin-stream-insight-main/src/contract/signalState.ts` and `.test.ts`, `tests/fixtures/signal_state_cases.json` is shared with them.

## Commands run
Plain-Python fixture parity over all fixture cases: 36 cases, 0 failures. `tests/test_signal_state.py` through a minimal pytest shim: 144 parametrized checks, 0 failures. `py_compile` on the three Python files.

## Not run
`pytest` (not installed in the build container), `ruff`, `npm run test` / `typecheck` (no node_modules), `tests/test_copilot_adversarial.py` (needs sqlalchemy and fastapi).

## Decisions used
Reason code `future`; tolerance 5 s, strict (exactly 5 s ahead is inside); value withheld for future samples, like `unknown`.

## Requested cross-task changes
None beyond the TypeScript mirror above.

## L4 update (2026-10-24): run evidence
The "Not run" list above is superseded. In `C:\twlogs\pytest_full_final.txt` `tests\test_signal_state.py` shows only passes (the file the future-dated cases live in), and `tests\test_copilot_adversarial.py` has no future-dated xfail left (its 9 xfails are the validator wording defect). Not covered by any pasted output: the TypeScript mirror (`npm run test` / `typecheck` were not pasted).
