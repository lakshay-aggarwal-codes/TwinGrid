#!/usr/bin/env sh
# RC step 1: migrations on an empty database (up, check, down to base, up again) and scripts/demo.sh twice (second run must be
# idempotent). Run from a CLEAN unzip with the lockfile install done. Needs Docker and the repo's Python environment.
. "$(dirname "$0")/drill_common.sh"
compose down -v >/dev/null 2>&1
compose up -d --wait db >/dev/null 2>&1
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:$(sed -n 's/^POSTGRES_PASSWORD=//p' "$ENV_FILE")@localhost:5432/twingrid}"
for step in "upgrade head" "heads" "check" "downgrade base" "upgrade head"; do
  alembic $step >/dev/null 2>&1; check clean_install "alembic $step" 0 $?
done
sh scripts/demo.sh >/dev/null 2>&1; check clean_install demo_run_1 0 $?
sh scripts/demo.sh >/dev/null 2>&1; check clean_install demo_run_2_idempotent 0 $?
check clean_install single_alembic_head 1 "$(alembic heads 2>/dev/null | grep -c head)"
finish
