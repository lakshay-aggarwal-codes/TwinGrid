# R_TASK_4_REPORT: Frontend red tests and type errors

Status: DONE (no code change required)

## Summary
At commit 2c4639c (branch wip/bc10-run-contract) the frontend checks listed in the roadmap are already clean.
The roadmap's 19 type errors, 4 lint warnings and 5 failing vitest tests came from an older audit and no longer reproduce.
No source or test file was changed. No test was weakened, skipped or relaxed.

## Acceptance checklist
- 0 type errors: MET. `npm run typecheck` (tsc app + node projects) printed no errors, owner-run output.
- 0 lint warnings: MET. `npm run lint:ci` (`--max-warnings 0`) printed nothing, owner-run output.
- 0 failing tests: MET. `npx vitest run`: Test Files 184 passed (184); Tests 2347 passed | 10 skipped (2357); 0 failed.
- Stale-evidence test keeps proving stale data never reads as normal: MET by not touching it; it passes.
- Per-test code-vs-test decision: not applicable, none of the five listed tests fail. Neither the component nor the test was changed.
- `npm run build`: NOT A DEFECT. Build stops at the intentional environment guard in `vite.config.ts`
  ("VITE_API_BASE_URL points at http://localhost:8000; a production bundle must not target localhost").
  Not yet run to completion; see Not run.

## Changed files
None (this report only).

## Commands run (by owner, Windows, Node v22 required by package.json)
npm run typecheck; npm run lint:ci; npx vitest run; npm run build (blocked by the guard above).

## Not run
A successful production build. Command (PowerShell, any non-localhost placeholder URL):
  $env:VITE_API_BASE_URL="https://api.example.invalid"; npm run build
Clear it afterwards: Remove-Item Env:VITE_API_BASE_URL
Also not verified: the Node version used for the passing run (confirm `node -v` prints v22.x; v24 only warns).

## Decisions used
No code changes: the stated failures do not reproduce, and inventing changes would break the "stay in your lane" rule.

## Requested cross-task changes
- Task 8: 10 skipped vitest tests need a reason each (or a fix). List them with `npx vitest run --reporter=verbose | Select-String -Pattern "skipped|↓"`.
