# R3 Task 4: demo checklist to baselines-v6

Scope: docs only. One file changed: `docs/DEMO_CHECKLIST.md`.

## Changes
- Steps 2 and 3 now use `baselines-v6` (verify, export, output file name).
- "What step 2 should print": dirty-tree WARN removed; `baselines-v6` manifest says `dirty: false`, commit `c2dd59f`.
- "What the stored run shows" rewritten from `reports/runs/baselines-v6/REPORT.md`; the "v5 not in tree" text and the Task 17 pointer are gone.
- FAQ: "marked DIRTY" row replaced by a reproducibility row; "PID and rule rows match" row replaced (v6 PID is -54.24, rule -54.85, not equal).
- Closing caution about `baselines-v4` removed (its premise no longer applies).

## Evidence (labels)
- Verified local source: v6 manifest (dirty false, c2dd59f, physics 1, 20 seeds), v6 REPORT.md numbers, `configs/baselines/pid.json` gains kp=1, ki=0, kd=0.
- Ran, Linux sandbox, no gymnasium, no git: `python scripts/repro.py verify baselines-v6` gave 2 FAIL (observation and action schema hash, "now None", gymnasium missing) and 7 WARN (code revision unknown, platform differences). No hash, config or REPORT.md FAIL.
- Ran: banned-word scan of the file against the `test_task33_claims.py` patterns, no hits. pytest itself was not available in the sandbox.
- Not verified: the match on your Windows machine. Open until you paste the output.

## Left unchanged on purpose
Remaining "(not in this tree)" notes are about the read-only demo button and the public request form, not baselines.
