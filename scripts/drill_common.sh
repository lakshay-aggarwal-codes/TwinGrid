#!/usr/bin/env sh
# Shared helpers for scripts/drill_*.sh (Task 31). Source it; do not run it. Needs Docker, curl and the demo stack
# (sh scripts/demo.sh). Every drill prints one line per check: DRILL <name> <check> <expected> <observed> PASS|FAIL
# and exits non-zero if any check failed. Nothing is faked: the drills stop and start the real compose services.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
ENV_FILE="${ENV_FILE:-.env.demo}"
API="${API:-http://localhost:8000}"
FAILS=0
compose() { docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.demo.yml "$@"; }
code() { curl -s -o /dev/null -m 10 -w '%{http_code}' "$@" 2>/dev/null || echo 000; }
check() { # name check expected observed
  if [ "$3" = "$4" ]; then r=PASS; else r=FAIL; FAILS=$((FAILS+1)); fi
  echo "DRILL $1 | $2 | expected=$3 | observed=$4 | $r"
}
wait_for() { # seconds command...
  n="$1"; shift; i=0
  while [ "$i" -lt "$n" ]; do "$@" >/dev/null 2>&1 && return 0; i=$((i+1)); sleep 1; done; return 1
}
finish() { echo "DRILL SUMMARY failures=$FAILS"; [ "$FAILS" -eq 0 ]; }
