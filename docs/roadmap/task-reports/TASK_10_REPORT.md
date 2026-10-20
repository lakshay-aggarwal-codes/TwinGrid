# Task 10 — NOTIFY-001 Real email delivery (SMTP/Gmail)     Status: DONE (real Gmail delivery not run by Claude)
Base: TwinGrid-main.zip as uploaded (no git history)     Date: 2026-10-20
Environment: Linux container, Python 3.12.3, pytest 9.1.1, ruff; no Gmail credentials, no internet SMTP.

## Summary
Adds `src/notify` (settings, mail adapter, `python -m src.notify` self-test). Backends: `smtp` (real mail, Gmail defaults),
`console` (redacted log), `file` (writes .eml to a dev outbox), `disabled`. Contract §8.2 result codes. No new dependencies.

## Acceptance checklist
- smtp success / auth_failed / refused / timeout / invalid_recipient: met (fake local SMTP server)
- No token or password in logs on any backend: met (test)
- HTML escaping of name/purpose; header-injection rejected: met
- Production requires https base URL: met
- Owner mail has only an /admin link, no approve/reject link: met
- STARTTLS happens before login: met (stub test)
- Real Gmail delivery: NOT RUN here. Run `python -m src.notify` with your credentials.

## Changed files
CREATE src/notify/{__init__,settings,mail,__main__}.py; tests/test_notify_mail.py; docs/env/T10.md; docs/env/T10.env.block;
docs/roadmap/task-reports/TASK_10_REPORT.md

## Commands run
- `pytest tests/test_notify_mail.py` (with repo conftest): 15 passed
- `pytest tests/test_startup_checks.py -k env_example` (with the block appended to .env.example): 4 passed
- `ruff check` / `ruff format --check` on the new files with the repo ruff.toml: clean
- `python -m src.notify --check`, no args, `--kind activation --to ...` against the fake server: exit 0, 2 messages received

## Pre-existing failures observed
None checked; full suite not run.

## Not run / blocked
Real Gmail delivery; full `pytest tests`; pyrefly; frontend.

## Decisions and defaults used
Gmail defaults (smtp.gmail.com:587 STARTTLS); owner and sender default to the SMTP user; spaces in the app password are stripped;
default backend is `console` in development and `disabled` in production. A bug found by the timeout test (smtplib wraps read timeouts
in SMTPServerDisconnected) is fixed in `_classify`.

## Requested cross-task changes
Task 9: call `from src.notify import mail` then `await mail.send_access_mail(kind, to, ctx)`; kinds `owner_new_request`, `activation`, `rejected`.
Task 2: add `reports/dev_outbox/` to .gitignore.

## New limitations or risks
The visitor-facing activation link only works from a phone if ACCESS_PUBLIC_BASE_URL is reachable from it (see docs/env/T10.md section 4).
Gmail personal accounts cap at roughly 500 messages/day.

## Next tasks unblocked
9 (access-request backend) can now send real mail.
