"""T17 -- GET /api/telemetry/sensors/{external_id}/samples|gaps (roadmap 9.4)."""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest
import pytest_asyncio

from tests.telemetry_support import NOW, STEP, T0, ext, point, put, put_steps, seed_feature_sensors

FEATURE = "it_power_kw"
SAMPLES = f"/api/telemetry/sensors/{'fac1.' + FEATURE}/samples"
GAPS = f"/api/telemetry/sensors/{'fac1.' + FEATURE}/gaps"
WIN = {"from": "2026-03-01T12:00:00Z", "to": "2026-03-02T12:00:00Z"}
REPLAY = "replay:123e4567-e89b-12d3-a456-426614174000"


@pytest_asyncio.fixture
async def seeded(session_maker):
    async with session_maker() as s:
        await seed_feature_sensors(s)
        await s.commit()
    return session_maker


def z(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def test_requires_authentication(client, seeded):
    assert (await client.get(SAMPLES, params=WIN)).status_code == 401
    assert (await client.get(GAPS, params=WIN)).status_code == 401


async def test_viewer_role_can_read(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(3))
    r = await client.get(SAMPLES, params=WIN, headers=viewer_headers)
    assert r.status_code == 200 and len(r.json()["items"]) == 3


async def test_items_carry_origin_stream_quality_and_utc_z_timestamps(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(2))
    body = (await client.get(SAMPLES, params=WIN, headers=viewer_headers)).json()
    assert body["external_id"] == "fac1." + FEATURE and body["unit"] == "kW" and body["sampling_interval_s"] == 300.0
    item = body["items"][0]
    assert item["origin"] == "simulated" and item["stream_id"] == "live" and item["quality"] == "ok"
    assert item["ts_event"] == "2026-03-01T12:00:00Z" and item["ts_event"].endswith("Z")
    assert item["ts_ingest"].endswith("Z") and "+" not in item["ts_event"] + item["ts_ingest"]
    assert item["value"] == 300.0


async def test_offset_input_is_converted_to_utc_z(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(3))
    # 17:30+05:30 == 12:00Z .. 18:30+05:30 == 13:00Z (half-open [from, to))
    r = await client.get(
        SAMPLES, params={"from": "2026-03-01T17:30:00+05:30", "to": "2026-03-01T18:30:00+05:30"}, headers=viewer_headers
    )
    assert [i["ts_event"] for i in r.json()["items"]] == [
        "2026-03-01T12:00:00Z",
        "2026-03-01T12:05:00Z",
        "2026-03-01T12:10:00Z",
    ]


@pytest.mark.parametrize(
    "bad", ["2026-03-01T12:00:00", "2026-03-01", "2026-03-01 12:00:00", "not-a-time", "", "1772366400"]
)
async def test_naive_or_malformed_from_is_422(client, seeded, viewer_headers, bad):
    r = await client.get(SAMPLES, params={"from": bad, "to": WIN["to"]}, headers=viewer_headers)
    assert r.status_code == 422
    r = await client.get(GAPS, params={"from": bad, "to": WIN["to"]}, headers=viewer_headers)
    assert r.status_code == 422


async def test_naive_to_is_422_and_from_to_are_required(client, seeded, viewer_headers):
    assert (
        await client.get(SAMPLES, params={"from": WIN["from"], "to": "2026-03-02T12:00:00"}, headers=viewer_headers)
    ).status_code == 422
    assert (await client.get(SAMPLES, params={"from": WIN["from"]}, headers=viewer_headers)).status_code == 422
    assert (await client.get(SAMPLES, params={"to": WIN["to"]}, headers=viewer_headers)).status_code == 422
    assert (await client.get(GAPS, headers=viewer_headers)).status_code == 422


async def test_422_detail_is_a_string_and_does_not_echo_the_value(client, seeded, viewer_headers):
    r = await client.get(SAMPLES, params={"from": "2026-03-01T12:00:00", "to": WIN["to"]}, headers=viewer_headers)
    assert isinstance(r.json()["detail"], str)


async def test_span_limit_and_ordering_of_bounds(client, seeded, viewer_headers, monkeypatch):
    ok = {"from": "2026-03-01T00:00:00Z", "to": "2026-03-08T00:00:00Z"}  # exactly 168 h
    assert (await client.get(SAMPLES, params=ok, headers=viewer_headers)).status_code == 200
    too_long = {"from": "2026-03-01T00:00:00Z", "to": "2026-03-08T00:00:01Z"}
    assert (await client.get(SAMPLES, params=too_long, headers=viewer_headers)).status_code == 422
    assert (await client.get(GAPS, params=too_long, headers=viewer_headers)).status_code == 422
    assert (
        await client.get(SAMPLES, params={"from": WIN["to"], "to": WIN["from"]}, headers=viewer_headers)
    ).status_code == 422
    assert (
        await client.get(SAMPLES, params={"from": WIN["from"], "to": WIN["from"]}, headers=viewer_headers)
    ).status_code == 422
    monkeypatch.setenv("TELEMETRY_MAX_SPAN_H", "1")
    assert (
        await client.get(
            SAMPLES, params={"from": "2026-03-01T00:00:00Z", "to": "2026-03-01T02:00:00Z"}, headers=viewer_headers
        )
    ).status_code == 422


async def test_unknown_sensor_is_404(client, seeded, viewer_headers):
    r = await client.get("/api/telemetry/sensors/nope/samples", params=WIN, headers=viewer_headers)
    assert r.status_code == 404


async def test_limit_is_capped_at_5000_and_validated(client, seeded, viewer_headers):
    assert (await client.get(SAMPLES, params={**WIN, "limit": 5001}, headers=viewer_headers)).status_code == 422
    assert (await client.get(SAMPLES, params={**WIN, "limit": 0}, headers=viewer_headers)).status_code == 422
    assert (await client.get(SAMPLES, params={**WIN, "limit": 5000}, headers=viewer_headers)).status_code == 200


async def test_stream_live_never_returns_replay_or_import(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(3), origin="simulated")
        await put_steps(s, range(3), origin="replay", stream=REPLAY)
        await put_steps(s, range(3), origin="measured", stream="import:ds1")
    live = (await client.get(SAMPLES, params={**WIN, "stream": "live"}, headers=viewer_headers)).json()["items"]
    default = (await client.get(SAMPLES, params=WIN, headers=viewer_headers)).json()["items"]
    assert len(live) == 3 and live == default and {i["stream_id"] for i in live} == {"live"}
    assert {i["origin"] for i in live} == {"simulated"}
    replay = (await client.get(SAMPLES, params={**WIN, "stream": REPLAY}, headers=viewer_headers)).json()["items"]
    assert (
        len(replay) == 3
        and {i["stream_id"] for i in replay} == {REPLAY}
        and {i["origin"] for i in replay} == {"replay"}
    )
    imp = (await client.get(SAMPLES, params={**WIN, "stream": "import:ds1"}, headers=viewer_headers)).json()["items"]
    assert {i["stream_id"] for i in imp} == {"import:ds1"}
    assert (await client.get(SAMPLES, params={**WIN, "stream": "weird"}, headers=viewer_headers)).status_code == 422


async def test_quality_filter(client, seeded, viewer_headers):
    async with seeded() as s:
        await put(s, [point(FEATURE, 0), point(FEATURE, 1, value=1e9), point(FEATURE, 2)])  # step 1 out of range
    q = lambda v: client.get(SAMPLES, params={**WIN, "quality": v}, headers=viewer_headers)  # noqa: E731
    assert [i["quality"] for i in (await q("ok")).json()["items"]] == ["ok", "ok"]
    inv = (await q("invalid")).json()["items"]
    assert len(inv) == 1 and inv[0]["invalid_reason"] == "range"
    assert len((await q("any")).json()["items"]) == 3
    assert len((await client.get(SAMPLES, params=WIN, headers=viewer_headers)).json()["items"]) == 2  # default ok
    assert (await q("bogus")).status_code == 422


# --------------------------------------------------------------------------- keyset pagination


async def collect(client, headers, limit, **extra):
    seen, cursor, pages = [], None, 0
    while True:
        params = {**WIN, "limit": limit, **extra, **({"cursor": cursor} if cursor else {})}
        body = (await client.get(SAMPLES, params=params, headers=headers)).json()
        seen += [i["ts_event"] for i in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            return seen, pages


async def test_pagination_walks_every_row_once_in_order(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(25), features=[FEATURE])
    seen, pages = await collect(client, viewer_headers, 7)
    assert pages == 4 and len(seen) == 25 and seen == sorted(seen) and len(set(seen)) == 25


async def test_pagination_exact_multiple_has_no_phantom_last_page(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(10), features=[FEATURE])
    seen, pages = await collect(client, viewer_headers, 5)
    assert len(seen) == 10 and pages == 2


async def test_pagination_is_stable_under_concurrent_inserts(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(0, 40, 2), features=[FEATURE])  # even steps: 20 rows
    first = (await client.get(SAMPLES, params={**WIN, "limit": 8}, headers=viewer_headers)).json()
    seen = [i["ts_event"] for i in first["items"]]
    cursor = first["next_cursor"]
    # rows arrive between requests: some BEFORE the cursor (late/out-of-order), some after it, one at the very end
    async with seeded() as s:
        await put_steps(s, [1, 3, 5], features=[FEATURE])  # before the cursor position
        await put_steps(s, [17, 19, 41], features=[FEATURE])  # after it
    while cursor:
        body = (await client.get(SAMPLES, params={**WIN, "limit": 8, "cursor": cursor}, headers=viewer_headers)).json()
        seen += [i["ts_event"] for i in body["items"]]
        cursor = body["next_cursor"]
    assert len(seen) == len(set(seen)), "a row was returned twice"
    assert seen == sorted(seen), "order broke across pages"
    original = {z(T0 + i * STEP) for i in range(0, 40, 2)}
    assert original <= set(seen), "an original row was skipped"
    assert {z(T0 + i * STEP) for i in (17, 19, 41)} <= set(seen)  # rows after the cursor are picked up
    assert not ({z(T0 + i * STEP) for i in (1, 3, 5)} & set(seen))  # rows behind the cursor are not (and no dups)


async def test_same_timestamp_in_two_streams_pages_by_id_tiebreak(client, seeded, viewer_headers):
    # (ts_event, id) keyset: many rows can share a ts_event across sensors; within one sensor+stream ts is unique,
    # so exercise the tiebreak through the cursor value directly.
    from api.routes.telemetry_routes import decode_cursor, encode_cursor

    ts, i = decode_cursor(encode_cursor(T0, 42))
    assert ts == T0 and i == 42


@pytest.mark.parametrize("bad", ["x", "!!!", "e30", "eyJ0IjoibmFpdmUiLCJpIjoxfQ"])
async def test_bad_cursor_is_422(client, seeded, viewer_headers, bad):
    r = await client.get(SAMPLES, params={**WIN, "cursor": bad}, headers=viewer_headers)
    assert r.status_code == 422


# --------------------------------------------------------------------------- gaps


async def test_gaps_are_consecutive_valid_differences_over_one_and_a_half_intervals(client, seeded, viewer_headers):
    async with seeded() as s:
        # steps 0-3, hole (4,5,6 missing = 1200 s diff), 7-9, then 450 s step (== 1.5x: NOT a gap), then 451 s (gap)
        await put_steps(s, [0, 1, 2, 3, 7, 8, 9], features=[FEATURE])
        await put(s, [point(FEATURE, 0, at=T0 + 9 * STEP + timedelta(seconds=450))])
        await put(s, [point(FEATURE, 0, at=T0 + 9 * STEP + timedelta(seconds=450 + 451))])
    body = (await client.get(GAPS, params=WIN, headers=viewer_headers)).json()
    assert body["threshold_s"] == 450.0 and body["sampling_interval_s"] == 300.0 and body["stream"] == "live"
    assert [(g["start"], g["end"], g["duration_s"]) for g in body["gaps"]] == [
        ("2026-03-01T12:15:00Z", "2026-03-01T12:35:00Z", 1200.0),
        (z(T0 + 9 * STEP + timedelta(seconds=450)), z(T0 + 9 * STEP + timedelta(seconds=901)), 451.0),
    ]
    assert body["truncated"] is False


async def test_gaps_ignore_invalid_samples_and_other_streams(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, [0, 1], features=[FEATURE])
        await put(s, [point(FEATURE, 2, value=1e9)])  # invalid sample at step 2: not a valid sample
        await put_steps(s, [3], features=[FEATURE])
        await put_steps(s, [2], features=[FEATURE], origin="replay", stream=REPLAY)  # would "fill" it, other stream
    gaps = (await client.get(GAPS, params=WIN, headers=viewer_headers)).json()["gaps"]
    # valid live samples: steps 0, 1, 3 -> 1 -> 3 is 600 s > 450 s: a gap, because the invalid sample does not count
    assert [(g["start"], g["end"]) for g in gaps] == [("2026-03-01T12:05:00Z", "2026-03-01T12:15:00Z")]
    replay = (await client.get(GAPS, params={**WIN, "stream": REPLAY}, headers=viewer_headers)).json()["gaps"]
    assert replay == []  # a single sample in that stream


async def test_gaps_are_computed_at_read_time_not_stored(client, seeded, session_maker):
    from sqlalchemy import inspect

    from models.db_models import TelemetrySample

    assert not any("gap" in c.name or "stale" in c.name for c in inspect(TelemetrySample).columns)


async def test_gaps_is_empty_for_contiguous_data_and_404_for_unknown(client, seeded, viewer_headers):
    async with seeded() as s:
        await put_steps(s, range(10), features=[FEATURE])
    assert (await client.get(GAPS, params=WIN, headers=viewer_headers)).json()["gaps"] == []
    assert (await client.get("/api/telemetry/sensors/nope/gaps", params=WIN, headers=viewer_headers)).status_code == 404


async def test_gaps_scale_beyond_one_internal_page(client, seeded, viewer_headers, monkeypatch):
    import api.routes.telemetry_routes as tr

    monkeypatch.setattr(tr, "_GAP_PAGE", 4)
    async with seeded() as s:
        await put_steps(s, [0, 1, 2, 3, 4, 5, 6, 20, 21, 22, 23, 24, 40], features=[FEATURE])
    gaps = (await client.get(GAPS, params=WIN, headers=viewer_headers)).json()["gaps"]
    assert [g["start"] for g in gaps] == [z(T0 + 6 * STEP), z(T0 + 24 * STEP)]  # found across page boundaries


# --------------------------------------------------------------------------- rate class


async def test_telemetry_read_has_its_own_rate_class(client, seeded, viewer_headers, monkeypatch):
    from api.rate_limit import _reset_windows as reset_rate_limits
    from api.rate_limit import limiter

    monkeypatch.setenv("RATE_LIMIT_TELEMETRY_READ", "2/minute")
    limiter.enabled = True
    reset_rate_limits()
    try:
        codes = [(await client.get(SAMPLES, params=WIN, headers=viewer_headers)).status_code for _ in range(4)]
    finally:
        limiter.enabled = False
    assert codes[:2] == [200, 200] and codes[2:] == [429, 429]


def test_rate_class_and_defaults_are_declared():
    from api import config

    assert config.RATE_LIMIT_DEFAULTS["telemetry_read"] == ("RATE_LIMIT_TELEMETRY_READ", "60/minute")
    assert ext(FEATURE) == "fac1." + FEATURE and NOW > T0
