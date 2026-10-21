#!/usr/bin/env bash
# Task 22 apply step. Idempotent; run from the TwinGrid repo root after `unzip -o TASK_22.zip` (and after Task 11).
set -euo pipefail
[ -f api/main.py ] || { echo "error: run this from the TwinGrid repo root" >&2; exit 1; }
for f in tests/api/test_task22_viewer_workflow.py twin-stream-insight-main/e2e/viewer-workflow.spec.ts docs/roadmap/task-reports/TASK_22_REPORT.md; do
  [ -f "$f" ] || { echo "missing after extract: $f" >&2; exit 1; }
done
echo "Task 22 files are in place; no post-extract steps needed. Next: bash docs/roadmap/task-scripts/task_22_verify.sh"
