# Task 17 report: reproducible report export bound to a run id

## What was added
- `src/run_export.py`: builds a Markdown (default) or PDF report from a stored run in `reports/runs/<run_id>/`. Nothing is recomputed; every number comes from `results.json`, `manifest.json` and `status.json`.
- `tests/test_run_export.py`: 19 test cases on a synthetic run directory.

## Behaviour
- Refuses (exit 2, nothing written) when: the run id is invalid or unknown; the directory name, `manifest.run_id` and `status.run_id` disagree; `status.state` is not `completed`; the LF-normalised SHA-256 of `results.json` differs from `manifest.result_sha256`; the results fail `repro.report.validate_results`; or `--expect-result-sha256` does not match the stored result.
- Report contents: run id, physics/environment/reward versions, code revision and DIRTY warning, config file hashes, seeds, scenario sets, carbon signal (ASSUMED vs real), summary, tables, hard-constraint violation counts per policy (outlet, inlet over/under, PUE), claims, notes and fixed limitations. A counter missing from a run is shown as "not measured", never as 0.
- Deterministic: two exports of the same run are byte-identical (Markdown checked; CRLF checkouts give the same bytes).

## Usage
    python -m src.run_export <run_id> [--format md|pdf] --out PATH [--expect-result-sha256 SHA]

## Not done / not verified
- Task 16 (comparison view) is not done, so there is no UI button. No API endpoint was added, to avoid changing the API contract. Wire both once Task 16 exists.
- The PDF path was NOT run in the sandbox (reportlab missing). `test_pdf_is_built_from_the_same_blocks` imports it directly and will fail, not skip, if reportlab is absent. Run it on your machine.
- PDF byte-determinism is asserted by that test but unverified.
- Tests ran with a custom shim runner, not real pytest. Run real pytest.
- The committed `baselines-v4` run was made from a dirty tree with tuner/2 configs; its export says so. This is a property of that run, not of the exporter.
- The exporter does not make a run valid, calibrated or validated. It reports what was stored.
