# Task 27 — SEC-002 Final security and dependency review          Status: PARTIAL
Base: uploaded TwinGrid-main.zip (no git history). Date: 2026-10-21.
Environment: Linux, Python 3.12.3 (91 of 93 locked packages installed with hashes; no torch/tensorflow), Node 22-class npm, pip-audit 2.10.1, npm audit, gitleaks 8.30.0.
**Prerequisites not met:** Tasks 22 and 25 (and 11, 20, 21, 23, 24, 26) are not applied in the supplied tree. The review covers what exists (access requests, demo session, copilot, admin queue API, WebSocket tickets) and must be re-run when those land.

## Summary
Direct-HTTP probes written as 58 tests; three behaviour defects fixed (timing oracle, dead authorisation matrix, copilot blocked for demo viewers); vulnerable dependencies upgraded or waived with owner and expiry; secret scan clean after documenting seven test placeholders. No critical or high finding in the probed surface. Open items are deployment settings (WebSocket origin/query token, proxy hops, worker count). **Not a penetration test.**

## Acceptance
- Critical/high fixed or blocking: none found. Met.
- Waivers recorded with owner and expiry: `docs/security/waivers.md`. Met.
- No token/secret in tracked files or logs: gitleaks working-tree scan clean after allowlisting placeholders; log-leak probe passes. **Git history not scanned** (no history here).

## Changed files
MODIFY `api/plugins/access_requests.py` (timing floor, +17 lines) · `api/demo_guard.py` (one allow-list entry) · `requirements.lock` (certifi, pillow) · `twin-stream-insight-main/package.json`, `package-lock.json` (vite 7.3.7) · `.gitleaks.toml` (allowlist) · `tests/authz_matrix.py` (overlay rows) · `tests/test_authz_matrix.py` (real demo probes) · `tests/authz_matrix.d/T9.yaml`, `T13.yaml`.
CREATE `tests/api/test_sec002_probes.py` · `docs/security/REVIEW_2026-10.md` · `docs/security/waivers.md` · this report.
Files edited that other tasks own, and why: `tests/authz_matrix*` (Task 3/9/13: the gate could not collect), `api/plugins/access_requests.py` (Task 9: timing), `api/demo_guard.py` (Task 13: copilot). None is in flight in this tree.

## Commands run and results (my environment)
- `pytest tests/api/test_sec002_probes.py` 58 passed; `tests/test_authz_matrix.py` 128 passed (was: collection error); `tests/api/test_access_requests.py`, `test_demo_session.py`, `tests/test_copilot_api.py`, `tests/test_lockfile.py`, startup-check and redaction suites pass.
- Probes shown able to fail: HS512 accepted, a write route added to the demo allow-list, per-email limit removed — each made a probe fail, then restored.
- `pip-audit` on the lock: 12 advisories before, 3 after (waived). `npm audit`: 11 before, 10 after (waived).
- `ruff check` / `ruff format` clean on all changed Python files.
- `npm run build` passes with `VITE_API_BASE_URL` set on vite 7.3.7; `vitest run src/test` 27 passed.
- Broad run `pytest tests -m "not postgres"`: 5056 passed, 83 failed, 12 errors. For the 11 security-adjacent failing files (26 failures) the set is identical with my source changes reverted, so they predate this task. The other failing files (artifact gate, anomaly, load harness, migrations, telemetry, provenance, register consistency, API reference and similar) touch nothing I changed; they were not triaged and probably need TensorFlow, Postgres, `src/runs` or missing docs.

## Not run
Postgres/Redis/mail/browser/deployed-host checks; git-history secret scan; full vitest (time limit); Playwright; pyrefly; a full `--require-hashes` install of the whole lock (torch CUDA dependencies are intentionally unlocked). `tsc` has 19 errors, identical before and after the vite bump.

## Decisions
Timing mitigation is a fixed minimum response time (default 100 ms, env `ACCESS_SUBMIT_MIN_MS`), not a rewrite of the decoy path. Production WebSocket defaults were not changed (could fail start-up); guidance is in the review.

## Requested cross-task changes
- Task 21 / deploy docs: set `WS_ALLOW_QUERY_TOKEN=false`, `WS_ALLOWED_ORIGINS`, `REDIS_URL`, `TRUST_PROXY_HEADERS=true`, `TRUSTED_PROXY_HOPS`; add `ACCESS_SUBMIT_MIN_MS` to `.env.example`.
- Tasks 22/25 owners: re-run the probe file and the authz matrix after landing.
- Task 30 (integrator): decide whether the pre-existing failures above go in the baseline ledger.

## Next tasks unblocked
Task 31 (final doc consistency) can cite `docs/security/REVIEW_2026-10.md` and `waivers.md`.
