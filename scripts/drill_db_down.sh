#!/usr/bin/env sh
# Drill: database down. Truthful behaviour: /livez stays 200 (process alive), /readyz is 503 and names the database, a data
# route answers an error (never an empty "all normal" 200), and after the database returns /readyz recovers by itself.
. "$(dirname "$0")/drill_common.sh"
compose stop db >/dev/null 2>&1
sleep 3
check db_down livez 200 "$(code "$API/livez")"
check db_down readyz 503 "$(code "$API/readyz")"
body=$(curl -s -m 10 "$API/readyz" 2>/dev/null)
case "$body" in *'"database"'*fail*) check db_down readyz_names_database yes yes ;; *) check db_down readyz_names_database yes no ;; esac
case "$body" in *postgres*|*password*|*Traceback*) check db_down readyz_leaks_nothing yes no ;; *) check db_down readyz_leaks_nothing yes yes ;; esac
check db_down alerts_without_token_is_401_not_200 401 "$(code "$API/api/alerts")"
compose start db >/dev/null 2>&1
if wait_for 90 sh -c "[ \$(curl -s -o /dev/null -w '%{http_code}' $API/readyz) = 200 ]"; then check db_down recovers_by_itself 200 200; else check db_down recovers_by_itself 200 "$(code "$API/readyz")"; fi
finish
