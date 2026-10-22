#!/usr/bin/env sh
# Drill: large data (>= 5,000 stored samples per sensor, R1 Task 11). Seeds SIMULATOR-produced samples on a fresh
# `import:drill-large-<epoch>` stream through scripts/perf_seed_history.py (real ingest path, origin 'simulated', back-dated),
# then pages the REAL history endpoint from inside the backend container. Truthful behaviour: every page is bounded by `limit`,
# pages chain by next_cursor with no duplicate and no skipped row, the total equals what was stored, and out-of-range limits,
# cursors and windows are refused with 422 (never a 5xx, never an unbounded response).
# Needs: the demo stack (sh scripts/demo.sh), the five feature sensors seeded, ADMIN_USER / ADMIN_PASS (any valid account).
# Observed sizes and timings are printed as INFO lines (no pass criterion: budgets belong to the Task 12 performance baseline).
. "$(dirname "$0")/drill_common.sh"
: "${ADMIN_USER:?set ADMIN_USER}"; : "${ADMIN_PASS:?set ADMIN_PASS}"
TICKS="${TICKS:-5200}"
STREAM="import:drill-large-$(date +%s)"
if ! compose exec -T backend python scripts/perf_seed_history.py --ticks "$TICKS" --stream "$STREAM"; then
  check large_data seed_stored_samples yes no
  echo "NOTE seeding failed: is the stack up and are the five sensors seeded (python scripts/seed_facility.py --seed-sensors)?"
  finish; exit 1
fi
tmp="$(mktemp)"
compose exec -T -e ADMIN_USER="$ADMIN_USER" -e ADMIN_PASS="$ADMIN_PASS" -e DRILL_STREAM="$STREAM" -e DRILL_MIN=5000 backend python - >"$tmp" <<'PY'
import json, os, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from api import config

API, STREAM, MIN = "http://localhost:8000", os.environ["DRILL_STREAM"], int(os.environ["DRILL_MIN"])
Z = "%Y-%m-%dT%H:%M:%SZ"


def call(path, token=None, body=None):
    req = urllib.request.Request(API + path, data=None if body is None else json.dumps(body).encode(), method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    return code, raw, time.time() - t0


def chk(check, expected, observed, ok):
    print(f"DRILL large_data | {check} | expected={expected} | observed={observed} | {'PASS' if ok else 'FAIL'}")


code, raw, _ = call("/auth/login", body={"username": os.environ["ADMIN_USER"], "password": os.environ["ADMIN_PASS"]})
token = json.loads(raw).get("access_token") if code == 200 else None
chk("login", 200, code, code == 200)
if not token:
    raise SystemExit(0)

now = datetime.now(timezone.utc)
win = f"from={(now - timedelta(hours=8)).strftime(Z)}&to={(now + timedelta(minutes=5)).strftime(Z)}&stream={urllib.parse.quote(STREAM)}"
sensors = list(config.telemetry_feature_sensors().values())


def page_through(sensor, limit):
    pages, items, cursor, max_bytes, max_s, bad = 0, [], None, 0, 0.0, []
    while True:
        q = f"/api/telemetry/sensors/{sensor}/samples?{win}&limit={limit}" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        code, raw, secs = call(q, token)
        if code != 200:
            bad.append(code)
            break
        body = json.loads(raw)
        pages += 1
        items += [i["ts_event"] for i in body["items"]]
        max_bytes, max_s = max(max_bytes, len(raw)), max(max_s, secs)
        if len(body["items"]) > limit:
            bad.append("page_over_limit")
        cursor = body["next_cursor"]
        if cursor is None:
            break
        if len(body["items"]) != limit:
            bad.append("short_page_with_cursor")
    return pages, items, max_bytes, max_s, bad


counts = {}
for s in sensors:
    _, items, _, _, bad = page_through(s, 5000)
    counts[s] = len(items)
chk("every_sensor_has_at_least_5000_samples", f">={MIN}", min(counts.values()), min(counts.values()) >= MIN)

first = sensors[0]
pages, items, max_bytes, max_s, bad = page_through(first, 1000)
chk("paged_by_cursor_at_limit_1000", ">=5 pages, no bad page", f"{pages} pages, bad={bad or 'none'}", pages >= 5 and not bad)
chk("no_duplicate_or_unordered_rows", "strictly increasing ts", "yes" if all(a < b for a, b in zip(items, items[1:])) else "no", all(a < b for a, b in zip(items, items[1:])))
chk("paged_total_equals_one_big_pass", counts[first], len(items), len(items) == counts[first])
_, big, big_bytes, big_s, big_bad = page_through(first, 5000)
chk("max_limit_pages_are_bounded", "<=5000 items per page", f"bad={big_bad or 'none'}", not big_bad)
print(f"DRILL large_data | INFO page_1000 | bytes_max={max_bytes} | seconds_max={max_s:.3f}")
print(f"DRILL large_data | INFO page_5000 | bytes_max={big_bytes} | seconds_max={big_s:.3f}")

base = f"/api/telemetry/sensors/{first}/samples?{win}"
for name, q in [
    ("limit_5001_refused", base + "&limit=5001"),
    ("limit_0_refused", base + "&limit=0"),
    ("garbage_cursor_refused", base + "&cursor=not-a-cursor"),
    ("window_over_max_span_refused", f"/api/telemetry/sensors/{first}/samples?from={(now - timedelta(hours=400)).strftime(Z)}&to={now.strftime(Z)}&stream={urllib.parse.quote(STREAM)}"),
]:
    code, _, _ = call(q, token)
    chk(name, 422, code, code == 422)
PY
cat "$tmp"
FAILS=$((FAILS + $(grep -c '| FAIL$' "$tmp")))
[ -s "$tmp" ] || { check large_data checker_produced_output yes no; }
rm -f "$tmp"
echo "NOTE the stream $STREAM stays in the demo database (retention removes it per the telemetry retention policy)."
finish
