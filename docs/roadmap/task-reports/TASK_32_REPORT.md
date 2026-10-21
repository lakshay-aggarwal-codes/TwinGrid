# Task 32 — REL-003 Docs, README, demo script and closeout          Status: PARTIAL
Base: TwinGrid-main.zip as uploaded. **Prerequisite Task 31 (RC gate) does not exist** (no `RC_REPORT.md`, no drill results), so the closeout cannot carry a verdict and `evidence/status.json` was not created (it must come from Task 31's real results).
Environment: Python 3.12 only; no Docker, Postgres, browser, node_modules or network.

## Summary
README, judges pack, demo checklist, issue register, frontend STATUS and the evidence matrix now say what the tree contains and what has not been run. Nothing was added to the claims ledger: the card allows viewer-access and assistant claims only after Tasks 22 and 25 pass, and neither exists.

## Acceptance checklist
- Every README feature exists -> met by reading the tree; the new access/demo/assistant section lists what exists and what does not (no public request form, no demo button, no language model).
- Every metric links to current evidence -> met for existing rows; no new numbers were added.
- No forbidden claim -> `tests/test_task33_claims.py` 8 passed (stand-in runner); `grep -rniE "production-ready|calibrated|saves? energy" README.md docs/*.md` read line by line: every hit is a negation, a forbidden-words list, or "uncalibrated".
- Issue register: one status and evidence per ID -> met (reconciliation table; headings aligned; `tests/test_task22_register_consistency.py` 5 passed).
- EVIDENCE_MATRIX.md: every J1-J7 and §9 item -> code, test, run output or blocker -> met (the matrix says "no run output" for nearly all rows).
- README quickstart "actually run from a clean clone" -> NOT met; README now says no clean-clone run is recorded.
- Screenshots -> none (none captured).

## Changed files
- MODIFY `README.md` — new "Access, demo mode and the assistant" and "Configure mail and run the checks" sections; quickstart and Status lines say what is unrecorded.
- MODIFY `docs/JUDGES.md` — engineering talking points (bullets; the ten numbered questions are unchanged).
- MODIFY `docs/DEMO_CHECKLIST.md` — five-minute viewer script (drafted, not rehearsed) and a caution that stored run `baselines-v4` predates the re-tuned configs.
- MODIFY `docs/audit/TwinGrid_Issue_Register.md` — reconciliation table; five stale headings aligned (TG-A-05, -07, -10, -12, -19).
- MODIFY `twin-stream-insight-main/docs/frontend/STATUS.md` — playbook-task section.
- CREATE `docs/roadmap/EVIDENCE_MATRIX.md`.
- CREATE `docs/roadmap/task-reports/TASK_32_REPORT.md`.
- NOTE: while I worked, `EVIDENCE_MATRIX.md`, `STATUS.md` and the register's reconciliation table appeared in the working tree and were not written by this session's commands. I read them, found them consistent with my own checks (Alembic single head, PID config, removed twin, carbon label), and kept them. Treat them as needing your review.

## Commands run
- tests/test_task33_claims.py 8 passed; tests/test_task22_register_consistency.py 5 passed; tests/test_truth_copy.py 2 passed (stand-in runner, not real pytest). Alembic head computed by reading the files: one head, `20261101000000`.

## Pre-existing failures observed
None observed.

## Not run / blocked
Everything needing a stack: clean-clone quickstart, demo run (twice), screenshots, failure drills. Run `ruff check .; ruff format --check .; pytest tests/test_task33_claims.py tests/test_task22_register_consistency.py -q`.

## Decisions and defaults used
- Held back new ledger rows and README claims about viewer access and the assistant (Tasks 22/25 not passed); described them as "built, not checked end to end" in an untagged section instead.
- Assistant: "no language model is connected" (checked `src/copilot/answer.py`), so the card's "optional LLM configuration" is documented as absent.
- JUDGES additions are bullets, so the ten-question and tagged-table tests stay valid.

## Requested cross-task changes
Task 31 (RC gate and drills), Task 21 (CI/contract fixtures/`docs/api/`), a public request-access page, a demo-session entry point in the UI, and regenerating the baselines run (`baselines-v5`) on your machine.

## New limitations or risks
The five-minute demo script is untested. The matrix and register describe source state, not run results.

## Next tasks unblocked
None.
