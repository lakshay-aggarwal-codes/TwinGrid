# R3 Task 4 report: demo checklist to baselines-v6

Status: **Done on pasted evidence (pass 2).** Docs only; no code touched.

## Changed (`docs/DEMO_CHECKLIST.md`)

- Steps 2 and 3 of the three-minute path now use `baselines-v6` (verify, export, report file name).
- "What step 2 should print": the dirty-tree WARN is gone, because the v6 manifest records `dirty: false`. Platform WARNs are described as appearing only where the environment differs from the recording machine (Windows, AMD64, Python 3.12.10, numpy 2.5.3).
- "What the stored run shows": v4's "PID collapsed to the rule (all gains 0)" and the "v5 is not in tree" text are removed. It now says v6's PID chose kp=1, ki=0, kd=0 (26 C target) and scored -54.24 against -54.85 for the rule; constant -36.33 and lookup -36.07; v5 is superseded and unedited.
- "If asked": the DIRTY row became "Can the stored run be re-checked?"; the "PID and rule rows match" row became "...are close", with the real numbers.
- Closing caution now names v6 as the stored run and v4 and v5 as superseded history.

## Checked from the repo (not run)

| Claim on the page | Source |
| --- | --- |
| Numbers above | `reports/runs/baselines-v6/REPORT.md` |
| `dirty: false`, recording platform, tuner config | `reports/runs/baselines-v6/manifest.json`, `configs/baselines/pid.json` (`baselines-tuner/3`) |
| Run used the current shipped configs | SHA-256 of all five `configs/baselines/*.json` equals the hashes in the v6 manifest |
| Banned-word list in `tests/test_task33_claims.py` | Re-applied to the page by hand: 0 hits. The test itself was not run. |

## Evidence pasted (your machine, Windows, Python 3.12.10)

- `python scripts\repro.py verify baselines-v6`: `FAIL code_revision: recorded 'c2dd59f...' but now '4ced51f...'`, then `FAIL baselines-v6: 1 failure(s), 0 warning(s)`. No other check failed and there were no WARN lines.
- Pass 1 of the page did not match this (it implied a clean verify). Pass 2 describes the output as it is: the one `code_revision` FAIL is expected after any later commit, as `docs/roadmap/ML-002_RUNBOOK.md` already says for v3 and v4. It is not a pass, and the page says not to call it one.
- `pytest tests/test_task33_claims.py tests/test_task20_docs_consistency.py`: 15 passed.
- The sandbox's schema-hash FAILs were gymnasium missing here; on your machine they pass.

## Not verified

- A clean-machine run of the three-minute path (the page says so).
- Out of scope, for Task 14: line 11 still names `scripts\rehearsal.ps1`, which is not in the tree; `docs/roadmap/ML-002_RUNBOOK.md` still talks about v5.
