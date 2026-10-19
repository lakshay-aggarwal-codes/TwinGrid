# Task 21 report: clean-environment setup and demo rehearsal (pass 1; HUMAN GATE open)

(Named `Task21_clean_setup_REPORT.md` because `Task21_REPORT.md` is an older, unrelated task.)

## Found and fixed
**Defect:** `python scripts\repro.py verify <run>` failed for every stored run (baselines-v2/v3/v4, toy-reference, ppo-train) with
`FAIL REPORT.md: differs from the version regenerated from results.json`. That is step 2 of the three-minute demo path.
**Cause:** `src/repro/report.py` ended the `Experiment:` and `Schema:` lines with two spaces (Markdown hard break). The repository's
pre-commit `trailing-whitespace` hook strips them from committed files, so committed `REPORT.md` files can never equal the output.
**Fix:** the generator no longer emits trailing spaces. Stored files are untouched (baselines-v2 is frozen and was not edited).
**Test:** `test_generated_report_has_no_trailing_whitespace_and_shipped_runs_match_it` compares every stored run's `REPORT.md` with the
regenerated text. I confirmed it fails when the old behaviour is reinstated (mutation check) and passes now.
Side effect: the Markdown now renders those three header lines as one paragraph (cosmetic).

## Already present (not changed)
`scripts/rehearsal.ps1` (fresh venv, install, lock drift, imports, migration graph, timed three-minute path, PASS/FAIL log),
`scripts/demo.ps1 -Fresh`, `scripts/check_lock_drift.py`, `docs/DEMO_CHECKLIST.md` with the viva table. I added only a note on what
step 2 should print.

## Ran here (Linux, Python 3.13, no gymnasium/pytest/PowerShell)
- `check_lock_drift.py`: no drift. `audit_alembic_graph.py`: 14 revisions, one head. `repro list`: 5 runs.
- After the fix, `repro verify baselines-v4`: no REPORT.md failure. It still prints FAIL for `observation_schema_hash` and
  `action_schema_hash` here only because gymnasium is missing (the code returns None by design).

## NOT verified (this is the human gate)
- Nothing was run on a clean Windows machine. `rehearsal.ps1` and `demo.ps1` were not executed or syntax-checked (no PowerShell here).
- Whether `pip install -r requirements.txt` and `--require-hashes -r requirements.lock` work on Windows / Python 3.12.
- Whether the schema-hash lines pass in your venv; whether Docker migrations run on an existing database; real timings of the path.
- The real pytest run of the new test (I ran the function directly).
- Separate, still open: the Task 7 test failures (missing `registry_cli`/`versions` symbols, stale baselines tests) are not part of this task.
