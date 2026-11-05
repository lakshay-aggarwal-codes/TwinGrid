# Task 8 report

```text
Task number and title: Task 8 - Canonical telemetry and provenance contract
Status: Ready for review
Base commit and branch: NOT established by this agent. The repo copy used here has no .git. The owner's Task 1 report records branch wip/cp8-hardening, HEAD d40daafa60ac589a0a048b4c99be8ff5115138cb (child of the handoff's b72f0f3). All files below are new and untracked.
Files read: Master Handoff (tasks 8, sections 4.1-4.4, 10); TASK_06_REPORT.md; TASK_07_ADR.md (headings, 3.3-3.4, Appendix A.1-A.2); Tasks 2-7 Completed Context (sections 1, 6-12); a prior agent's partial Task 8 status note (its repo findings were re-verified, see below); repo files src/telemetry/{ingest,validation}.py, alembic/versions/20261004000000_t16_telemetry_sample.py, api/routes/telemetry_routes.py, research/danish_aau/evaluation/provenance.py (read-only, nothing executed against a database).
Files created/modified/deleted: created only: research/danish_aau/contract/ (__init__.py, telemetry_contract.py, negative_vectors.py, examples/*.json x17); research/danish_aau/tests/contract/ (conftest.py, test_telemetry_contract.py); reports/telemetry_handoff/task08/ (TASK_08_CONTRACT.md, TASK_08_REPORT.md). Modified/deleted: none.
Decisions made (within Task 8 authority): record = 34 explicit keys; time = source text with ts_utc null until a timezone is approved; five mutually exclusive states; four provenance labels as record fields with a provenance x storage x origin matrix (derived and synthetic never in telemetry_sample; origin enum unchanged); group power returned only as group record or pointer, split_allowed always false; absent-value cases separated by measurand_status, window_status and an unknown_entity error; v5 profile pins id grammar, units (degC, W, m/s), resolutions (2 and 1 decimals, owner CK-1 decisions), no server id; measurand named air_speed (owner question 1); dropped rows exist only as ledger entries (owner question 2); five API envelope kinds with explicit facility and stream.
Evidence and outputs (paths + SHA-256, LF-normalised):
| file | sha256 |
|---|---|
| `reports/telemetry_handoff/task08/TASK_08_CONTRACT.md` | `e67f2107fc9dd51240fd5cfde53a8c4506e7e90b73fa599feaf46ca3f834b96d` |
| `research/danish_aau/contract/telemetry_contract.py` | `9788d06cc5ed8889e6cdbc818d0b55020b8c87e9d2d03d64bee8451f169e2d30` |
| `research/danish_aau/contract/negative_vectors.py` | `f84ce9bf47134106b92054a0cedaafd46801683264b952311fbd09323b74c147` |
| `research/danish_aau/tests/contract/test_telemetry_contract.py` | `3493969b313a0c1ba52f8db382c65f5cc169def9d33974e1a5bb8f50e09f6e20` |
Commands executed and exact results (agent sandbox, Python 3.12, stdlib only; pytest and jsonschema are not installed there, so a throwaway shim ran the tests; NOT a real pytest run):
- contract tests: 116 passed, 0 failed
- protocol tests (unchanged, regression): 35 passed, 0 failed; `python -m research.danish_aau.protocol verify` -> hash 0ff45216...7098
- negative control: with the split_allowed rule disabled, exactly 1 test failed (split_allowed_true); restored, 116 passed.
Tests: passed 116 (contract, shim) + 35 (protocol, shim); failed 0; skipped 0; real pytest, ruff and the owner's venv: not run for these files. No JSON Schema was produced or run.
Frozen-path check: only new files under research/danish_aau/contract, research/danish_aau/tests/contract and reports/telemetry_handoff/task08; no frozen simulator/model path, migration, schema or asset-validation file was touched.
Data/licence/privacy limitations: no raw or row-level data used; all examples are synthetic (namespace synthetic-example, year 2000); the single v5 example carries no value. Keep reports local until redistribution is decided.
Open blockers and exact owner action: (1) review and approve the contract (version moves from 1.0.0-draft to 1.0.0); (2) answer the five questions in contract section 15; (3) before Task 9: decide how imported rows may be stored given telemetry_sample needs a UTC instant (ts_event NOT NULL), allows only quality ok/invalid, and sensors default to source_tz UTC (contract section 12); (4) run the tests on your machine (commands in the reply).
Dependencies now unlocked (do not start them): Task 9 (also needs the Task 7 ADR, already approved); Tasks 11-17 only after G1.
```
