#!/usr/bin/env bash
# Task 11 (AUTH-C Visitor UX) apply step. Idempotent; run from the repo root after `unzip -o TASK_11.zip`.
set -euo pipefail
if [ ! -f api/main.py ]; then
  echo "error: run this from the TwinGrid repo root (api/main.py not found)" >&2
  exit 1
fi
missing=0
for f in twin-stream-insight-main/src/features/access/api.ts \
         twin-stream-insight-main/src/features/access/PendingPage.tsx \
         twin-stream-insight-main/src/features/access/ActivatePage.tsx \
         twin-stream-insight-main/src/components/DemoBanner.tsx \
         twin-stream-insight-main/src/contract/fixtures-access/index.ts; do
  [ -f "$f" ] || { echo "missing after extract: $f" >&2; missing=1; }
done
[ "$missing" -eq 0 ] || exit 1
echo "Task 11 files are in place; no post-extract steps needed."
