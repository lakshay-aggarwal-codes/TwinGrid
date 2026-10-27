# R3 Task 3 report: frontend what-if tests

Status: **Done on pasted evidence.** No code change: nothing was failing in your tree.

## Evidence (your machine, `twin-stream-insight-main`, vitest 5.0.4)

| Run | Command | Result |
| --- | --- | --- |
| What-if folder | `npx vitest run src/features/what-if-lab` | 3 files, **68 tests passed** (`setpointRange.test.ts` 10, `logic.test.ts` 35, `LabPage.test.tsx` 23, including "saves a scenario, compares it with the baseline, and keeps it across a reload") |
| Whole frontend suite | `npx vitest run` | **185 files, 2401 tests passed, 0 failed** (52.6 s) |

Logs kept: `r3_t3_before.txt` (the what-if run) and `r3_t3_full.txt` (the full run).

The `FAIL`-style lines in the full log are test titles that contain the word "fail" ("a failed run is an explicit error flag...") and `stderr` output from the evaluation-contract mutation tests, which expect errors. Neither is a failing test. The pass count above is the result.

## Contract

`src/contract/fixtures/whatif.json` and `src/api/models.ts` already carry `physics_version`, `provenance.weather_source`, `provenance.registry_version` and `provenance.api_version` (see the Task 2 report), and the suite that reads them passes. No refresh was needed.

## Not verified

- I never saw the "2 failing `logic.test.ts` tests and the `LabPage` test" the roadmap describes, in any run. The first what-if run I have was already green. They were most likely fixed together with Tasks 1 and 2 in earlier commits, but I have not traced which commit, so I am not claiming that.
- Only the Vitest suite was run. The Playwright end-to-end specs are not part of this task.
- The suite ran once; I have no repeat-run evidence for flakiness.
