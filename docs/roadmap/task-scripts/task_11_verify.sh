#!/usr/bin/env bash
# Task 11 verify step. Writes logs to reports/task-11/ and prints a name,exit_code summary.
set -uo pipefail
[ -f api/main.py ] || { echo "error: run from the TwinGrid repo root" >&2; exit 1; }
ROOT="$(pwd)"
LOG="$ROOT/reports/task-11"
mkdir -p "$LOG"
cd twin-stream-insight-main
SUMMARY=""
note() { SUMMARY="$SUMMARY$1,$2"$'\n'; }
if [ ! -d node_modules ]; then
  npm ci > "$LOG/npm_ci.log" 2>&1; note npm_ci $?
else
  echo "skipped: npm ci (node_modules already present)"
fi
npm run typecheck > "$LOG/typecheck.log" 2>&1; note typecheck $?
npm run lint:ci   > "$LOG/lint.log" 2>&1;      note lint_ci $?
npx vitest run src/features/access src/components src/authClient.test.ts src/authClient.demo.test.ts src/features > "$LOG/test_task11_scope.log" 2>&1; note test_task11_scope $?
npm run test      > "$LOG/test_all.log" 2>&1;  note test_all $?
npm run build     > "$LOG/build.log" 2>&1;     note build $?
# zero new suppressions in Task 11 files
if grep -rnE "@ts-ignore|@ts-expect-error|eslint-disable|: any\b|as any\b" src/features/access src/contract/fixtures-access src/components/DemoBanner.tsx src/components/LoginScreen.tsx src/authClient.demo.test.ts > "$LOG/suppressions.log" 2>&1; then note no_new_suppressions 1; else note no_new_suppressions 0; fi
echo "name,exit_code"
printf "%s" "$SUMMARY"
echo "Logs: $LOG. Nothing else skipped; bundleScan.test.ts runs inside test_all (it performs two production builds)."
