# R Task 2 report: future-dated samples must not read as normal

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
