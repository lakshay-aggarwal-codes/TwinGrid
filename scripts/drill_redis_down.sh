#!/usr/bin/env sh
# Drill: Redis down (tickets / limits). Truthful behaviour per api/routes/health_routes.py: /readyz stays 200 but reports redis
# under "degraded"; sign-in still works; the API does not hang. A ticket-only production config is covered by startup rule R13.
. "$(dirname "$0")/drill_common.sh"
compose stop redis >/dev/null 2>&1
sleep 3
check redis_down readyz 200 "$(code "$API/readyz")"
body=$(curl -s -m 10 "$API/readyz" 2>/dev/null)
case "$body" in *redis*) check redis_down readyz_reports_redis_degraded yes yes ;; *) check redis_down readyz_reports_redis_degraded yes no ;; esac
t0=$(date +%s); c=$(code -X POST "$API/auth/demo-session"); t1=$(date +%s)
[ "$c" = 200 ] || [ "$c" = 404 ] || [ "$c" = 503 ] && check redis_down demo_session_answers_not_hangs yes yes || check redis_down demo_session_answers_not_hangs yes "http_$c"
[ $((t1-t0)) -le 10 ] && check redis_down answered_within_10s yes yes || check redis_down answered_within_10s yes "$((t1-t0))s"
compose start redis >/dev/null 2>&1
wait_for 60 sh -c "[ \$(curl -s -o /dev/null -w '%{http_code}' $API/readyz) = 200 ]" && check redis_down recovers 200 200 || check redis_down recovers 200 "$(code "$API/readyz")"
finish
