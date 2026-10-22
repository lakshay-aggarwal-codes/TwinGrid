#!/usr/bin/env sh
# Drill: history gap (R1 Task 11). Stores SIMULATOR-produced samples (same DigitalTwin.step + ingest_samples path as
# scripts/perf_seed_history.py, origin 'simulated', back-dated, on a fresh `import:drill-gap-<epoch>` stream) with TWO deliberate holes:
# 600 s (above the backend's gap threshold of 1.5 x the 300 s sampling interval = 450 s) and 420 s (below it). Then reads the REAL
# /gaps and /samples endpoints. Truthful behaviour (RT-001 item 5): exactly the 600 s hole is reported, the 420 s hole is not (the UI
# says so: HistoryView.tsx "Gaps shorter than ... are not marked"), and no value is invented inside either hole.
# This checks the SERVER side of the gap path. The browser merge of recovered samples (Task 23: backfill consumer in
# src/telemetry/history/backfillMerge.ts, features/realtime-resilience/BackfillHost.tsx) is covered by its unit tests; a browser leg on
# this stream is not written (the history screen reads the default `live` stream).
# Needs: the demo stack, the five feature sensors seeded, ADMIN_USER / ADMIN_PASS (any valid account).
. "$(dirname "$0")/drill_common.sh"
: "${ADMIN_USER:?set ADMIN_USER}"; : "${ADMIN_PASS:?set ADMIN_PASS}"
STREAM="import:drill-gap-$(date +%s)"
tmp="$(mktemp)"
compose exec -T -e ADMIN_USER="$ADMIN_USER" -e ADMIN_PASS="$ADMIN_PASS" -e DRILL_STREAM="$STREAM" backend python - >"$tmp" <<'PY'
import asyncio, json, math, os, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from api import config
from database import get_session
from src.digital_twin import DigitalTwin
from src.telemetry.ingest import ingest_samples

API, STREAM = "http://localhost:8000", os.environ["DRILL_STREAM"]
Z = "%Y-%m-%dT%H:%M:%SZ"
STEP, SEG = 3, 200  # seconds between ticks, ticks per segment (200 ticks x 5 sensors = the 1000-sample ingest batch limit)
HOLE_BIG, HOLE_SMALL = 600, 420


def chk(check, expected, observed, ok):
    print(f"DRILL history_gap | {check} | expected={expected} | observed={observed} | {'PASS' if ok else 'FAIL'}")


def call(path, token=None, body=None):
    req = urllib.request.Request(API + path, data=None if body is None else json.dumps(body).encode(), method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


async def seed():
    mapping = config.telemetry_feature_sensors()
    twin = DigitalTwin()
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)
    starts = [t0]
    starts.append(starts[0] + timedelta(seconds=STEP * (SEG - 1) + HOLE_BIG))  # first sample of segment B
    starts.append(starts[1] + timedelta(seconds=STEP * (SEG - 1) + HOLE_SMALL))  # first sample of segment C
    stored = 0
    n = 0
    for start in starts:
        batch = []
        for i in range(SEG):
            hour = (n * STEP / 3600.0) % 24.0
            utilisation = 0.55 + 0.25 * math.sin(2 * math.pi * (hour - 9) / 24)  # fixed daily pattern, as perf_seed_history.py
            outside = 22.0 + 6.0 * math.sin(2 * math.pi * (hour - 15) / 24)
            mode = twin.select_cooling_mode(outside, 0.1)
            state = twin.step({"utilisation": utilisation, "outside_temp_C": outside, "water_stress": 0.1, "cooling_mode": mode}).to_dict()
            n += 1
            for feature, external_id in mapping.items():
                batch.append({"external_id": external_id, "ts_event": start + timedelta(seconds=STEP * i), "value": float(state[feature]), "sim_time": state["timestamp"]})
        async with get_session() as session:
            result = await ingest_samples(session, batch, stream_id=STREAM, origin="simulated")
            await session.commit()
        stored += result.stored
    return starts, stored, list(mapping.values())[0]


starts, stored, sensor = asyncio.run(seed())
chk("seeded_all_samples", 3 * SEG * 5, stored, stored == 3 * SEG * 5)
a_last = starts[0] + timedelta(seconds=STEP * (SEG - 1))
b_first, b_last = starts[1], starts[1] + timedelta(seconds=STEP * (SEG - 1))
c_first, c_last = starts[2], starts[2] + timedelta(seconds=STEP * (SEG - 1))

code, raw = call("/auth/login", body={"username": os.environ["ADMIN_USER"], "password": os.environ["ADMIN_PASS"]})
token = raw.get("access_token") if code == 200 and raw else None
chk("login", 200, code, code == 200)
if not token:
    raise SystemExit(0)
win = f"from={(starts[0] - timedelta(minutes=1)).strftime(Z)}&to={(c_last + timedelta(minutes=1)).strftime(Z)}&stream={urllib.parse.quote(STREAM)}"

code, gaps = call(f"/api/telemetry/sensors/{sensor}/gaps?{win}", token)
chk("gaps_endpoint", 200, code, code == 200)
if gaps:
    chk("threshold_is_450s", 450.0, gaps["threshold_s"], gaps["threshold_s"] == 450.0)
    chk("exactly_one_gap_reported", 1, len(gaps["gaps"]), len(gaps["gaps"]) == 1)
    if len(gaps["gaps"]) == 1:
        g = gaps["gaps"][0]
        want = (a_last.strftime(Z), b_first.strftime(Z), float(HOLE_BIG))
        got = (g["start"], g["end"], g["duration_s"])
        chk("reported_gap_is_the_600s_hole", want, got, got == want)
    chk("420s_hole_is_not_reported", "no gap starting at the end of segment B", "none" if all(x["start"] != b_last.strftime(Z) for x in gaps["gaps"]) else "reported", all(x["start"] != b_last.strftime(Z) for x in gaps["gaps"]))
    chk("not_truncated", False, gaps["truncated"], gaps["truncated"] is False)

items, cursor = [], None
while True:
    code, body = call(f"/api/telemetry/sensors/{sensor}/samples?{win}&limit=1000" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""), token)
    if code != 200:
        break
    items += [i["ts_event"] for i in body["items"]]
    cursor = body["next_cursor"]
    if not cursor:
        break
chk("no_value_invented_in_holes", 3 * SEG, len(items), len(items) == 3 * SEG)
PY
cat "$tmp"
FAILS=$((FAILS + $(grep -c '| FAIL$' "$tmp")))
[ -s "$tmp" ] || { check history_gap checker_produced_output yes no; }
rm -f "$tmp"
echo "NOTE the stream $STREAM stays in the demo database (retention removes it per the telemetry retention policy)."
finish
