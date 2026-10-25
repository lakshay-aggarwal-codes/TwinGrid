#!/usr/bin/env sh
# Drill: mail failure. Starts the backend with an SMTP host that refuses connections, submits a request, approves it as admin
# and checks that approval still succeeds, the request shows email "failed" (not "sent"), and no activation link was claimed
# as delivered. Needs ADMIN_USER / ADMIN_PASS (an admin account on the stack) and ACCESS_TOKEN_PEPPER in the stack env.
. "$(dirname "$0")/drill_common.sh"
: "${ADMIN_USER:?set ADMIN_USER}"; : "${ADMIN_PASS:?set ADMIN_PASS}"
# The compose files do not forward ACCESS_NOTIFY_* from the shell, so the failing SMTP settings go in a throw-away override file.
OVR="$ROOT/.drill-mail-failure.override.yml"
cat > "$OVR" <<'YML'
services:
  backend:
    environment:
      ACCESS_NOTIFY_BACKEND: smtp
      ACCESS_NOTIFY_SMTP_HOST: 127.0.0.1
      ACCESS_NOTIFY_SMTP_PORT: "1"
      ACCESS_NOTIFY_SMTP_USER: drill
      ACCESS_NOTIFY_SMTP_PASSWORD: drill
      ACCESS_NOTIFY_FROM: drill@example.com
      ACCESS_NOTIFY_OWNER_EMAIL: owner@example.com
      ACCESS_PUBLIC_BASE_URL: http://localhost:8080
YML
# Always put the stack back (without the failing settings) and wait for it, so the next drill finds a running backend.
trap 'rm -f "$OVR"; compose up -d --force-recreate --wait backend >/dev/null 2>&1' EXIT
compose -f "$OVR" up -d --force-recreate backend >/dev/null 2>&1
wait_for 120 sh -c "[ \$(curl -s -o /dev/null -w '%{http_code}' $API/readyz) = 200 ]" || { check mail_failure backend_up yes no; finish; exit 1; }
EMAIL="drill-$(date +%s)@example.com"
resp=$(curl -s -m 15 -X POST "$API/api/access-requests" -H 'Content-Type: application/json' -d "{\"name\":\"Drill\",\"email\":\"$EMAIL\",\"purpose\":\"mail failure drill\"}")
ref=$(printf '%s' "$resp" | sed -n 's/.*"ref":"\([A-Z2-7]*\)".*/\1/p')
check mail_failure request_accepted yes "$([ -n "$ref" ] && echo yes || echo no)"
tok=$(curl -s -m 15 -X POST "$API/auth/login" -H 'Content-Type: application/json' -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
id=$(curl -s -m 15 "$API/api/admin/access-requests" -H "Authorization: Bearer $tok" | tr '{' '\n' | grep "\"ref\":\"$ref\"" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)
check mail_failure approve_returns_200 200 "$(code -X POST "$API/api/admin/access-requests/$id/approve" -H "Authorization: Bearer $tok" -H 'Content-Type: application/json' -d '{}')"
sleep 5
state=$(curl -s -m 15 "$API/api/admin/access-requests/$id" -H "Authorization: Bearer $tok" | sed -n 's/.*"notify_state":"\([^"]*\)".*/\1/p')
check mail_failure notify_state_is_failed failed "$state"
echo "NOTE the stack is restored on exit (backend recreated without the failing SMTP settings)"
finish
