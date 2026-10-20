# Task 2 — BASE-002 Repo hygiene and identity          Status: DONE (with checks not run, listed below)
Base: `TwinGrid-main.zip` as uploaded (no `.git`; a scratch `git init` baseline was used)     Date: 2026-10-20
Environment: Linux sandbox, Python 3 stdlib only. No pytest, ruff, node or network available.

## Summary
27 loose logs (24 from the repo root, 3 from `twin-stream-insight-main/`) are moved, unchanged, into `reports/archive/2026-10-loose-logs/` by PowerShell command (the ZIP carries only new/changed files). `reports/archive/README.md` lists every moved file with origin, size and a sha256 prefix. `.gitignore` gets anchored entries so the logs are not re-committed, and a broken line is fixed. The `scripts/demo_seed.py` docstring no longer says admin has no extra rights. No code changed.

## Acceptance checklist
| Criterion | Result | Evidence |
|---|---|---|
| `git status` shows only moves + `.gitignore` + docstring (+ new README/report) | met in scratch repo | 25 renames (R100), 3 adds (README, 2 files that git could not pair as renames), 2 modifies (`.gitignore`, `scripts/demo_seed.py`) |
| Archive README lists every moved file | met | 27 rows; the build asserted the listed names equal the directory contents |
| Nothing under the keep-list changed | met | `reports/runs`, `reports/policy_evaluation*`, `reports/postT9`, `reports/industry` absent from the diff |
| Historical logs not edited | met | renames are R100 (identical content) |
| Loose logs not re-committed | met | `git check-ignore --no-index` matches root `fails.txt`, `run_clean.txt`, `pyrefly.json`, `t7_*`, `retune_*`, `playwright_*` and the two frontend names |
| Archived copies stay trackable | met | `git check-ignore` reports none of the archived files as ignored |

## Changed files
- `.gitignore` — replaced the "Local experiment logs" block. Old block had unanchored names (`run_clean.txt` would also have ignored the archived copy) and one corrupted line (`tests_clean.txt<TAB>tune_clean.txt`, a tab, so neither file was ignored; both were in fact tracked). New entries are root-anchored.
- `scripts/demo_seed.py` — docstring only: admin gates `/api/admin/*`, optimizer-proposal decisions and role changes; it is not an operator (`require_operator` checks the exact role `operator`).
- `reports/archive/README.md` — new (see above).
- `docs/roadmap/task-reports/TASK_2_REPORT.md` — this report.
- Moved (by command): 24 root files + 3 `twin-stream-insight-main/` files → `reports/archive/2026-10-loose-logs/` (frontend ones in a `twin-stream-insight-main/` subfolder because `fails.txt` exists in both places).

## Commands run
- scratch `git init` + move + `git add -A`: 25 R100, 3 A, 2 M.
- `python3 -I scripts/check_register.py`: `data/external/REGISTER.json: OK (15 datasets)`.
- `python3 -I -m py_compile scripts/demo_seed.py`: OK.
- `grep` of `tests/` and `scripts/` for every moved file name: no references.

## Pre-existing failures observed
None observed; the full test suite was not run.

## Not run / blocked
- `pytest tests -q -x -k "register or hygiene"` — pytest not installed here. Test files with matching names exist (e.g. `tests/test_external_register.py`, `tests/test_ci_gates.py`). Run: `pytest tests -q -x -k "register or hygiene"`.
- `pytest tests/test_task5_demo_seed.py` and `ruff check; ruff format --check` — not run (no pytest/ruff). The docstring edit compiles and is docstring-only.
- Local-path count: the task says 64 files; I count 67 outside `node_modules` (the extra ones are mostly under the kept `reports/industry/perfile/`, untouched by design). Your working copy may differ.

## Decisions and defaults used
- Moves are PowerShell commands (not in the ZIP) so evidence bytes are never re-encoded; hashes in the README let you verify.
- README descriptions are inferred from file names and opening content, and say so.
- Not moved: loose files directly under `reports/` (`baseline_pytest.txt`, `full_run.txt`, `junit.xml`, `load_baseline_*.csv`) — outside this task's candidate list.

## Requested cross-task changes
- Task 32 (owner of audit docs): `docs/audit/TwinGrid_Final_Assessment.md` cites `t7_tests_2.txt` by its old root name; update to the archive path.
- Task 1: when it says "read `t7_tests_2.txt` (UTF-16)", the file is now `reports/archive/2026-10-loose-logs/t7_tests_2.txt`.

## New limitations or risks
- `.gitignore` does not untrack anything: if you had committed `tests_clean.txt`/`tune_clean.txt`, the move shows as a rename, which is intended.
- `pyrefly*.json` at root is now ignored; CI still writes and uploads it, which is unaffected.

## Next tasks unblocked
None required; Task 1 can proceed on a tidier tree.
