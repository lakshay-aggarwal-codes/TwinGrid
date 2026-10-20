# Task 7 — ML-001 Immutable, verifiable run provenance          Status: PARTIAL
Base: TwinGrid-main.zip as uploaded 2026-10-20 (no git history; baseline commit made in the sandbox)   Date: 2026-10-20
Environment: Python 3.12.3, numpy 2.4.4; NO pytest, NO gymnasium/torch/fastapi, NO network. Tests were run with a
home-made pytest stand-in (outside the repo), not real pytest.

## Summary
Each run now copies the exact pre-registration bytes to `<run>/prereg.snapshot.json`, records `prereg_snapshot` beside the
existing `prereg_sha256`, and `verify` reads the snapshot, never the shared path. A run made before this (no snapshot) is
checked against its recorded hash only while the shared file still matches; otherwise it is labelled
`unverifiable (historical, snapshot absent)`, which is not a pass and not a FAIL. No old manifest is rewritten.

## Acceptance checklist
- Two runs with different pre-registrations both verify after the shared file is overwritten -> met (stand-in run): `test_a_run_verifies_after_the_shared_preregistration_is_overwritten`.
- Tamper with a snapshot/report -> verify fails -> met: tampered and missing snapshot fail closed (`prereg_sha256`); a manifest pointing elsewhere fails (`prereg_snapshot`); existing report/results tamper tests still pass.
- Oldest committed run gives a deterministic result -> met: every committed run verifies twice to identical findings and never a prereg FAIL; `baselines-v3` (its shared prereg was overwritten by v4) is now UNVERIFIABLE instead of FAIL.
- The two recorded failures -> resolved/explained (see Failures).

## Changed files
- src/repro/run.py - `PREREG_SNAPSHOT`, optional manifest field `prereg_snapshot`, `snapshot_prereg` (fails the run if the shared file changed between hashing and copying)
- src/repro/verify.py - `_check_prereg`, `UNVERIFIABLE` level, `VerifyReport.label` / `.unverifiables`; `ok()` is False for an unverifiable run
- scripts/repro.py - prints `UNVERIFIABLE` and its count (summary format unchanged when 0)
- tests/test_repro_framework.py - 2 failures fixed, prereg mutation cases retargeted, 11 new cases
- docs/roadmap/task-reports/TASK_7_REPORT.md

## The two failures (Failing: tests/test_repro_framework.py (2))
1. `test_a_changed_version_constant_fails_verify_naming_it`: stale test. It set `REWARD_VERSION = "2"`, which became the running value, so nothing differed. Now sets a value that differs from the running one. (verified local source + stand-in run)
2. `test_the_shipped_toy_reference_run_round_trips`: not a code bug. `toy-reference` was recorded before the environment/action/reward/safety versions moved to 2 and before `requirements.lock` changed, so verify correctly reports those lineage fields. An old manifest is never rewritten, so it cannot pass outright. The test now requires that the only failures are those lineage fields, that content is intact and that the verdict is deterministic. A fresh reference run (new id) would restore the strict check; I did not make one because it must carry your real git revision.

## Commands run (stand-in runner, NOT real pytest)
- tests.test_repro_framework: 96 cases, 94 pass; 2 fail from the stand-in's own limits (`tmp_path_factory`, `monkeypatch.chdir`).
- Against baseline source: 12 of the cases touching this change fail (incl. the committed-run determinism test on `baselines-v3`).
- test_baselines + test_robustness_eval + test_repro_framework together: 254 pass / 24 fail before, 267 / 22 after. Differences: the two target tests fixed, new tests added, and `test_shipped_baselines_run_verifies_and_lists_all_four` moved from a prereg FAIL to a `code_revision` FAIL (unchanged by this task).

## Not run / blocked
Real pytest, `ruff check .; ruff format --check .`. `code_revision` results in the sandbox are meaningless (fake baseline commit); judge them on your machine.

## Decisions and defaults used
- `manifest_version` stays 1 and `prereg_snapshot` is optional (not in `REQUIRED_MANIFEST_FIELDS`), so every existing manifest still validates.
- The manifest already records config hashes, dataset manifest, physics version/params hash, seeds, platform + lock hash, `result_sha256` and the code revision (honours `GIT_SHA`). Not added: a hash of REPORT.md, since verify regenerates it from `results.json` and diffs it.
- Only the pre-registration was overwritten between runs; configs are not snapshotted.

## Requested cross-task changes
`src/baselines/cli.py:113` prints `FAIL ... 0 failure(s)` for an unverifiable run; switch it to `rep.label` and show `len(rep.unverifiables)` as `scripts/repro.py` now does.

## New limitations or risks
`verify` still FAILs a historical run on `code_revision`, lock hash and lineage versions when the checkout has moved on; only the pre-registration is made immutable. v3's original pre-registration is not recoverable from the repo (only its hash), so v3 stays UNVERIFIABLE.

## Next tasks unblocked
Task 17's re-tune produces snapshotted baseline runs.
