#!/usr/bin/env bash
# Task 22 (viewer workflow e2e) verify step. Run from the TwinGrid repo root AFTER Task 11 is merged.
# Part A (backend, no browser) always runs. Part B (Playwright, real backend) runs only when E2E_ADMIN_USERNAME,
# E2E_ADMIN_PASSWORD and E2E_OUTBOX_DIR are set; otherwise it is reported as SKIPPED, never as passed.
set -uo pipefail
[ -f api/main.py ] || { echo "error: run from the TwinGrid repo root" >&2; exit 1; }
[ -f twin-stream-insight-main/src/features/access/ActivatePage.tsx ] || { echo "error: merge Task 11 first" >&2; exit 1; }
ROOT="$(pwd)"; LOG="$ROOT/reports/task-22"; mkdir -p "$LOG"
SUMMARY=""; note() { SUMMARY="$SUMMARY$1,$2"$'\n'; }

export JWT_SECRET_KEY="${JWT_SECRET_KEY:-ci-test-secret-not-for-production}" ENVIRONMENT=development PYTHONHASHSEED=0
# api tests and root tests must be separate pytest runs (see TASK_9_REPORT: fixture 'client' quirk)
python -m pytest tests/api/test_task22_viewer_workflow.py -q -rs > "$LOG/pytest_task22.log" 2>&1; note pytest_task22 $?
python -m pytest tests/api/test_access_requests.py tests/api/test_demo_session.py -q > "$LOG/pytest_access_demo_regression.log" 2>&1; note pytest_access_demo_regression $?
ruff check tests/api/test_task22_viewer_workflow.py > "$LOG/ruff_check.log" 2>&1; note ruff_check $?
ruff format --check tests/api/test_task22_viewer_workflow.py > "$LOG/ruff_format.log" 2>&1; note ruff_format $?

cd twin-stream-insight-main
[ -d node_modules ] || { npm ci > "$LOG/npm_ci.log" 2>&1; note npm_ci $?; }
npx tsc --noEmit -p tsconfig.json > "$LOG/typecheck.log" 2>&1; note typecheck $?
npx eslint e2e/viewer-workflow.spec.ts > "$LOG/lint.log" 2>&1; note lint_spec $?

if [ -n "${E2E_ADMIN_USERNAME:-}" ] && [ -n "${E2E_ADMIN_PASSWORD:-}" ] && [ -n "${E2E_OUTBOX_DIR:-}" ]; then
  npx playwright test e2e/viewer-workflow.spec.ts > "$LOG/playwright.log" 2>&1; note playwright_viewer_workflow $?
else
  note playwright_viewer_workflow SKIPPED
fi
echo "name,exit_code"; printf "%s" "$SUMMARY"
echo "Logs: $LOG"
