# Task 4 — Repo cleanup and one truthful architecture

## What changed
- **Rewrote** `docs/architecture/system.md` and `data_flow.md` against the current code (the earlier versions described Phase 3–4 and were stale: client-polled anomaly scoring, "no task queue", RL env with its own physics). Old-doc claims kept only where verified (single physics source, drought threshold 0.7, flat 475 gCO2/kWh fallback, training gap for carbon columns); the rest was dropped.
- **Deleted** (see list in chat): `ARCHITECTURE.md`, `FINAL_REVIEW.md`, `DOCUMENTATION_SUMMARY.md`, both `TWINGRID_REPOSITORY_MAP` files (10.6 MB), `test_report.pdf`, `realData_tree.txt`, `detailed_dataset_report.txt`, `detailed_dataset_report_v2.py`, `generate_detailed_dataset_report.py`, `example_optimized_usage.py`, `test_startup.py`, `run_tests.py`, `ig04_pytest.txt`, `ig05_pytest.txt`, `twin-stream-insight-main/T0b.diff`, plus `dataset_schema_report.txt` (see Assumptions).
- **Repaired links:** `README.md` (supersession note), `CONTRIBUTING.md`, `DATA_DICTIONARY.md`, `PERFORMANCE_OPTIMIZATION.md`, `twin-stream-insight-main/docs/frontend/baseline/BASELINE.md`, `reports/industry/IG00_reality_baseline.md` (F-19 row).
- `.gitignore`: added `node_modules/` and `backups/` (`dist/`, `build/` were already covered).

## Assumptions
- `dataset_schema_report.txt` is a misnamed Python script whose output path is the deleted `detailed_dataset_report.txt`; unreferenced elsewhere, so removed with the rest of that family.
- `IG00_reality_baseline.md` (dated audit evidence) still names the deleted files in prose; left as history, F-19 marked resolved. Not links.
- Old-doc content about 20 phases, `digital_twin_documented.py`, real Electricity Maps data, and the "Outstanding work" tables was not carried over: unverifiable or contradicted by the code.
- `deployment.md` and the README body were not in scope; README still says "5 revisions" (code has 10, one head) — left for Task 33.

## Test results
- Docs/config only; no code touched.
- Dangling-reference grep over the whole tree (excluding `node_modules`, `requirements.lock`) for every deleted name: only prose hits in `IG00_reality_baseline.md`, the README note explaining the removal, and `BASELINE.md` saying `T0b.diff` was removed.
- Import scan of all `.py` files for the deleted modules: `import scan done` (no hits). No test references the deleted or edited files (tests only glob `*.py` at root for the artifact-gate scan, which a smaller set cannot fail).
- Alembic graph check (script): `heads: ['20261004000000'] count 10`.

## Not verified
- `pytest -q` was **not run**: pytest and the project dependencies are not installed in the sandbox and there is no network. Expected unaffected (no code changed).
- Mermaid diagrams were not rendered.
