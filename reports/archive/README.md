# Archive of loose logs, October 2026 (`2026-10-loose-logs/`)

These files used to sit at the repository root and in `twin-stream-insight-main/`. They were **moved into `2026-10-loose-logs/` unchanged** (BASE-002) so the tree is tidy without losing evidence. They are historical records of local runs on the author's Windows machine, not current results.

## Read before citing

- **Descriptions are inferred** from file names and a read of each file's opening content; they were not confirmed with the author.

- **Not current.** Counts such as "13 failed, 610 passed" or "881 pyrefly errors" describe the tree at the time of each run. Task 1 (BASE-001) re-measures the baseline; use `docs/roadmap/BASELINE.md` for current numbers once it exists.
- **Local path inside.** Many of these files contain the author's local Windows path (for example `C:\Users\<name>\Desktop\...`). The contents were deliberately **not** scrubbed: editing evidence would change what it proves. Treat that path as incidental.
- **Encodings.** Several `t7_*` files are UTF-16 (PowerShell redirection). Decode with `Get-Content -Encoding Unicode` or Python `open(..., encoding="utf-16")`.
- **Referenced by name elsewhere.** `docs/audit/TwinGrid_Final_Assessment.md` cites `t7_tests_2.txt` by its old root name. It now lives here: `reports/archive/2026-10-loose-logs/t7_tests_2.txt`.
- **Moved, not deleted.** Nothing was removed. Not touched: `reports/runs`, `reports/policy_evaluation*`, `reports/postT9`, `reports/industry`.

## From the repository root

| Original path | Bytes | sha256 (first 16) | What it is |
|---|---:|---|---|
| `fails.txt` | 0 | `e3b0c44298fc1c14` | Empty (0 bytes) placeholder. |
| `playwright_a11y.txt` | 6,357 | `b9b79d39d28c2967` | Playwright run that failed: "test() called here" (spec imported by config). |
| `pyrefly.json` | 493,243 | `288da9fb52286690` | pyrefly --output-format=json output (881 errors); identical to pyrefly2.json. CI regenerates this file. |
| `pyrefly2.json` | 493,243 | `288da9fb52286690` | Byte-identical duplicate of pyrefly.json. |
| `pyrefly_baseline.txt` | 1,945 | `3375082dc002e28d` | Summary of the 881-error pyrefly count by error kind (basis of the CI ceiling). |
| `retune_1_prereg.txt` | 129 | `c866580018a4b8e5` | Output of writing reports/policy_evaluation_physics1/PREREGISTRATION.json (retune session). |
| `retune_3_run.txt` | 31 | `ab5ff2788f162447` | Tuner version string printed during the retune session (baselines-v3). |
| `retune_4_summary.txt` | 1,205 | `84537a42d3345bb2` | Rule/constant tuner summaries (tuner=baselines-tuner/2, physics 1, range 16-25 C). |
| `retune_5_pid_top15.txt` | 1,481 | `6faec8713c05fd79` | Top-15 PID grid rows by validation reward. |
| `retune_6_prereg_fields.txt` | 2,825 | `8b1b2063e3a5fabf` | Grep of fields in PREREGISTRATION.json. |
| `retune_7_tests.txt` | 10,813 | `76610a537246ee4c` | pytest session log (Windows, Python 3.12.10) from the retune session. |
| `run_clean.txt` | 0 | `e3b0c44298fc1c14` | Empty (0 bytes) placeholder. |
| `t7_0_env.txt` | 130 | `1b641c1d0c08c685` | Environment capture for the T7 run (Python / pip versions). |
| `t7_0_freeze.txt` | 2,906 | `7682cab09bc30c9c` | pip freeze for the T7 run. |
| `t7_1_pyrefly_version.txt` | 18 | `dc2b4bc5f4e44534` | pyrefly version used for the ceiling measurement (0.64.1). |
| `t7_junit_0.xml` | 103,953 | `c56decd6d7d5f3b5` | JUnit XML, earlier T7 run: 655 tests, 25 failures, 5 skipped (2026-10-18). |
| `t7_junit_2.xml` | 88,827 | `c186a8353c081db9` | JUnit XML, later T7 run: 624 tests, 13 failures, 1 skipped (2026-10-19). |
| `t7_tests_0.txt` | 13,500 | `a2394ad82c7e8c80` | pytest output for the earlier T7 run (UTF-16 text). |
| `t7_tests_1.txt` | 3,717 | `0e6c087fcb48a385` | pytest output, intermediate T7 run. |
| `t7_tests_2.txt` | 21,005 | `546a9b0fb2a4fc50` | pytest output for the later T7 run (UTF-16 LE). Cited by name in docs/audit/TwinGrid_Final_Assessment.md. |
| `t7b_failing_files.txt` | 20,137 | `4aa0610ab730e661` | pytest output for the T7b run over the failing files. |
| `task9_ppo_eval.txt` | 1,451 | `e7c2b0c9a4ecc9c4` | Console output of a Task 9 PPO evaluation attempt (carbon CSV missing, flat fallback used). |
| `tests_clean.txt` | 10,979 | `3c85c8697dda8a10` | pytest failure excerpt (config validity tests). |
| `tune_clean.txt` | 0 | `e3b0c44298fc1c14` | Empty (0 bytes) placeholder. |

## From `twin-stream-insight-main/` (kept in a subfolder because `fails.txt` exists in both places)

| Original path | Bytes | sha256 (first 16) | What it is |
|---|---:|---|---|
| `twin-stream-insight-main/fails.txt` | 440,421 | `f205296a12debc4b` | Frontend vitest output, ~440 KB, contains ANSI colour codes. |
| `twin-stream-insight-main/playwright_a11y_login.txt` | 9,727 | `6507541aa6b8f952` | Playwright axe run on the login screen. |
| `twin-stream-insight-main/playwright_after.txt` | 901 | `8ea1eaaec74dc6b8` | Playwright axe run on the login screen (shorter, later run). |

Total: 27 files (24 from the root, 3 from `twin-stream-insight-main/`).

## Why `pyrefly.json` is not needed at the root

CI regenerates it (`pyrefly check --output-format=json > pyrefly.json`) and uploads it as an artifact, so the root copy was a stale local output. It is now git-ignored at the root.
