# TASK 22 REPORT: Viewer workflow e2e

**Status: PARTIAL.** Tests are written and syntax-checked only. Neither suite could be executed in the authoring sandbox (no PyPI, no npm registry: no fastapi/sqlalchemy/pytest, no `node_modules`). Nothing below claims a passing test. Run `bash docs/roadmap/task-scripts/task_22_verify.sh`.

**Scope note (assumption).** The Task 22 card was not in the uploads. Scope was taken from the repo's own references (TASK_9 "22 (viewer workflow e2e)", TASK_13 "Task 22 (viewer workflow)") and confirmed with the owner: request access -> owner approves -> activation -> sign-in as viewer, plus the demo path. Task 11 is not merged in `TwinGrid-main.zip`; Task 22 assumes it is (the verify script refuses to run otherwise). The older `docs/tasks/Task22_REPORT.md` (reports/export) is a different, earlier numbering and was not touched.

## What was built
- `tests/api/test_task22_viewer_workflow.py` (backend, real app, in-memory SQLite, **real** `src.notify.mail` with `ACCESS_NOTIFY_BACKEND=file`; the activation link is read out of the written `.eml`, no mail double):
  - approve path (12 steps): submit -> owner mail has no approve/reject link -> poll pending -> queue -> approve -> activation mail to the visitor -> `can_activate` -> weak/equals-email password refused without burning the link -> activate (no session issued) -> replay 400 -> login as viewer -> read 200, `POST /api/optimize` 403, admin queue 403 -> stored user is a hashed viewer -> audit actions present and no token/password in any audit row.
  - status token vs activation token are separate secrets; wrong token and unknown ref give one identical 404.
  - reject path: no link, no account, 409 on a later approve.
  - expired link refused with the same body as any bad token; resend issues a new working link and kills the old one; resend before approval sends nothing and answers like an unknown ref.
  - demo path: demo session reads, writes 403 `demo_read_only`, no refresh token stored; a real approved viewer's token has no `demo` claim.
- `twin-stream-insight-main/e2e/viewer-workflow.spec.ts` (Playwright, real backend, no `page.route`): visitor form -> pending "Awaiting decision" -> owner approves in the real admin console (separate context) -> pending page flips to "Approved" by polling -> emailed link opened (token leaves the address bar; password set; "Access activated") -> reopening the link shows "Activation link problem" -> sign-in as the new viewer (no Admin nav) -> admin queue shows "Activated". Second test: demo banner, Live Twin, no Admin nav.
- `docs/roadmap/task-scripts/task_22_apply.sh`, `task_22_verify.sh`.
- No product code changed. No existing test edited.

## Verification actually performed
- `python3 -I -m py_compile` on the new test: OK.
- `bun build --no-bundle` of the spec (transpile): OK. `bash -n` on both scripts: OK.
- Selectors and copy were checked against the Task 11/12 sources (`RequestAccessForm`, `PendingPage`, `ActivatePage`, `LoginScreen`, `DemoBanner`, `AccessPanel`, `AdminPage`, `FeatureNav`) and the backend against `access_requests.py`, `service.py`, `mail.py`, `demo_session.py`, `demo_guard.py`, `auth.py`. This is reading, not execution.

## NOT run (BLOCKED)
- `pytest tests/api/test_task22_viewer_workflow.py`, ruff, `tsc`, eslint, `npx playwright test e2e/viewer-workflow.spec.ts`.
- Exact commands: `bash docs/roadmap/task-scripts/task_22_verify.sh` (Part B needs `E2E_ADMIN_USERNAME`, `E2E_ADMIN_PASSWORD`, `E2E_OUTBOX_DIR`).

## Setup for the Playwright run
Backend: `ACCESS_NOTIFY_BACKEND=file ACCESS_NOTIFY_FILE_DIR=<dir> ACCESS_NOTIFY_OWNER_EMAIL=<any> ACCESS_NOTIFY_FROM=<any> ACCESS_PUBLIC_BASE_URL=http://localhost:8080 ACCESS_TOKEN_PEPPER=<random> DEMO_PUBLIC_ENABLED=true`, an admin account, and a seeded `demo_viewer`. Frontend dev server without `VITE_DEMO_USERNAME/PASSWORD`. `E2E_OUTBOX_DIR` = the same `<dir>`. Limit: 5 access requests/hour/IP, so rerun spacing matters; each run creates one `e2e-viewer-<ms>@example.com` account.

## Decisions to review
- Real mail adapter with the file backend instead of the Task 9 double: this exercises Task 10 and the link format together. Cost: the file backend and a shared directory are required for the browser test.
- Owner approval is done in the real admin UI (Task 12), not by API, so Tasks 11, 12 and the backend are proven in one run.
- The browser test does not reload the visitor page after sign-in (tokens are in memory) and does not open `/admin` directly for the viewer; it asserts the Admin nav is absent. The backend 403 on the admin queue is covered in the pytest file.

## Risks and unverified points
- Selector guesses most likely to need a tweak on first run: the confirm button in the approve dialog (`getByRole("button", {name:"Approve", exact:true}).last()`), and `getByLabel("Name")` matching more than one field on the sign-in/request view.
- The pytest file relies on background mail tasks completing before the ASGI call returns (httpx `ASGITransport` does this; Task 9 tests depend on the same behaviour).
- Equal-to-email password case assumes the address is >= 12 characters (it is: 25).
- PostgreSQL not exercised. Not covered: 320 px layout, real SMTP, timing equality of real vs decoy responses.

## Requested cross-task changes
None required. Optional: add the Playwright spec to the CI e2e job once the outbox env is wired (the frontend e2e job is still `continue-on-error` per the audit register).

## Next tasks unblocked
Task 21/32 (CI and audit docs) can cite this spec as the viewer-flow evidence once it has actually run green.
