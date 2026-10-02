"""T9 HTTP-level tests: authz, as-of queries, move/identity, overlap rejection.

Uses the shared fixtures in tests/api/conftest.py (in-memory SQLite, rate limiting off).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from models.db_models import Asset, AssetEdge, AssetPose, AuditLog, Facility

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def pick_r1(payload: dict) -> dict:
    """The r1 entry of a GET /api/assets response."""
    return next(a for a in payload["assets"] if a["external_id"] == "r1")


def external_ids(payload: dict) -> list[str]:
    return [a["external_id"] for a in payload["assets"]]


@pytest_asyncio.fixture
async def world(session_maker):
    """Facility + zones A/B + racks r1, r2 (r1 in A at (1,1,0); r2 in B) + a PDU. Valid from T0."""
    async with session_maker() as s:
        f = Facility(name="F", frame_unit="m", frame_note="note")
        s.add(f)
        await s.flush()
        ids = {"facility": f.id}
        for ext, typ in [
            ("zone-a", "zone"),
            ("zone-b", "zone"),
            ("r1", "rack"),
            ("r2", "rack"),
            ("pdu1", "pdu"),
            ("crac1", "crac"),
        ]:
            a = Asset(facility_id=f.id, asset_type=typ, external_id=ext, name=ext)
            s.add(a)
            await s.flush()
            ids[ext] = a.id
        for ext, (x, z) in {"zone-a": (0, 0), "zone-b": (10, 0), "r1": (1, 0), "r2": (10, 0)}.items():
            s.add(
                AssetPose(
                    asset_id=ids[ext], x=x, y=0 if ext.startswith("zone") else 1, z=z, rotation_deg=0, valid_from=T0
                )
            )
        s.add(AssetEdge(parent_asset_id=ids["zone-a"], child_asset_id=ids["r1"], relation="located_in", valid_from=T0))
        s.add(AssetEdge(parent_asset_id=ids["zone-b"], child_asset_id=ids["r2"], relation="located_in", valid_from=T0))
        await s.commit()
    return ids


# ----------------------------------------------------------------- authz
@pytest.mark.parametrize(
    "method,path", [("GET", "/api/facility"), ("GET", "/api/assets"), ("GET", "/api/assets/1/edges")]
)
async def test_reads_require_auth(client, world, method, path):
    assert (await client.request(method, path)).status_code in (401, 403)


async def test_viewer_can_read(client, world, viewer_headers):
    r = await client.get("/api/facility", headers=viewer_headers)
    assert r.status_code == 200 and r.json()["frame_unit"] == "m"
    r = await client.get("/api/assets", headers=viewer_headers)
    assert r.status_code == 200 and r.json()["count"] == 4  # 2 zones + 2 racks with poses; pdu/crac unplaced


async def test_viewer_cannot_write(client, world, viewer_headers, count_rows):
    before = await count_rows(AssetPose)
    r = await client.post(f"/api/assets/{world['r1']}/move", json={"x": 2, "y": 1, "z": 0}, headers=viewer_headers)
    assert r.status_code == 403
    r = await client.post(
        f"/api/assets/{world['r1']}/edges",
        json={"parent_asset_id": world["pdu1"], "relation": "powered_by"},
        headers=viewer_headers,
    )
    assert r.status_code == 403
    r = await client.post("/api/edges/1/close", json={}, headers=viewer_headers)
    assert r.status_code == 403
    assert await count_rows(AssetPose) == before


async def test_writes_require_auth(client, world):
    assert (await client.post(f"/api/assets/{world['r1']}/move", json={"x": 2, "y": 1, "z": 0})).status_code in (
        401,
        403,
    )


# ----------------------------------------------------------------- move / identity
async def test_move_preserves_identity_and_history(client, world, operator_headers, count_rows):
    t1 = T0 + timedelta(days=10)
    r = await client.post(
        f"/api/assets/{world['r1']}/move",
        json={"x": 5.0, "y": 1.0, "z": 3.0, "rotation_deg": 90, "valid_from": iso(t1)},
        headers=operator_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["asset_id"] == world["r1"] and body["external_id"] == "r1" and body["created"] is True
    assert await count_rows(Asset) == 6  # no asset created or deleted by a move
    assert await count_rows(AssetPose, AssetPose.asset_id == world["r1"]) == 2

    before = (
        await client.get("/api/assets", params={"as_of": iso(t1 - timedelta(seconds=1))}, headers=operator_headers)
    ).json()
    after = (await client.get("/api/assets", params={"as_of": iso(t1)}, headers=operator_headers)).json()
    assert (pick_r1(before)["pose"]["x"], pick_r1(before)["pose"]["z"]) == (1, 0)
    assert (pick_r1(after)["pose"]["x"], pick_r1(after)["pose"]["z"]) == (5, 3) and pick_r1(after)["pose"][
        "rotation_deg"
    ] == 90
    assert pick_r1(before)["id"] == pick_r1(after)["id"] == world["r1"]
    # half-open: old pose valid_to == new pose valid_from, no gap, no overlap
    assert pick_r1(before)["pose"]["valid_to"] is not None
    assert pick_r1(before)["pose"]["valid_to"] == pick_r1(after)["pose"]["valid_from"]


async def test_move_with_rehome_swaps_located_in_atomically(client, world, operator_headers, session_maker):
    t1 = T0 + timedelta(days=1)
    r = await client.post(
        f"/api/assets/{world['r1']}/move",
        json={"x": 10.5, "y": 1, "z": 0, "valid_from": iso(t1), "to_parent_id": world["zone-b"]},
        headers=operator_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["located_in"]["parent_external_id"] == "zone-b"
    now = (await client.get("/api/assets", headers=operator_headers)).json()
    old = (
        await client.get("/api/assets", params={"as_of": iso(T0 + timedelta(hours=1))}, headers=operator_headers)
    ).json()
    assert pick_r1(now)["located_in"]["parent_external_id"] == "zone-b"
    assert pick_r1(old)["located_in"]["parent_external_id"] == "zone-a"
    async with session_maker() as s:
        open_edges = (
            await s.execute(
                select(func.count())
                .select_from(AssetEdge)
                .where(
                    AssetEdge.child_asset_id == world["r1"],
                    AssetEdge.relation == "located_in",
                    AssetEdge.valid_to.is_(None),
                )
            )
        ).scalar_one()
    assert open_edges == 1


async def test_move_is_idempotent_by_asset_and_valid_from(client, world, operator_headers, count_rows):
    payload = {"x": 4, "y": 1, "z": 1, "valid_from": iso(T0 + timedelta(days=2))}
    first = await client.post(f"/api/assets/{world['r1']}/move", json=payload, headers=operator_headers)
    again = await client.post(f"/api/assets/{world['r1']}/move", json=payload, headers=operator_headers)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["created"] is False and again.json()["pose"] == first.json()["pose"]
    assert await count_rows(AssetPose, AssetPose.asset_id == world["r1"]) == 2
    assert await count_rows(AuditLog, AuditLog.action == "asset_move") == 1  # replay is not re-audited
    different = await client.post(
        f"/api/assets/{world['r1']}/move", json={**payload, "x": 99}, headers=operator_headers
    )
    assert different.status_code == 409


async def test_move_conflicts_and_validation(client, world, operator_headers, count_rows):
    h = operator_headers
    n = await count_rows(AssetPose)
    # before the current pose's start -> "must be later than the start of the current pose"
    r = await client.post(
        f"/api/assets/{world['r1']}/move",
        json={"x": 2, "y": 1, "z": 0, "valid_from": iso(T0 - timedelta(days=1))},
        headers=h,
    )
    assert r.status_code == 409 and "later than" in r.json()["detail"]
    # same instant as the current pose but different content -> key conflict
    r = await client.post(
        f"/api/assets/{world['r1']}/move", json={"x": 2, "y": 1, "z": 0, "valid_from": iso(T0)}, headers=h
    )
    assert r.status_code == 409 and "already starts" in r.json()["detail"]
    # future-dated
    fut = iso(datetime.now(timezone.utc) + timedelta(days=1))
    assert (
        await client.post(
            f"/api/assets/{world['r1']}/move", json={"x": 2, "y": 1, "z": 0, "valid_from": fut}, headers=h
        )
    ).status_code == 422
    # unknown asset / parent
    assert (await client.post("/api/assets/999999/move", json={"x": 1, "y": 1, "z": 1}, headers=h)).status_code == 404
    assert (
        await client.post(
            f"/api/assets/{world['r1']}/move", json={"x": 1, "y": 1, "z": 1, "to_parent_id": 999999}, headers=h
        )
    ).status_code == 404
    # parent must be a zone
    assert (
        await client.post(
            f"/api/assets/{world['r1']}/move", json={"x": 1, "y": 1, "z": 1, "to_parent_id": world["pdu1"]}, headers=h
        )
    ).status_code == 422
    # non-finite / out-of-range coordinates rejected at the schema
    assert (
        await client.post(
            f"/api/assets/{world['r1']}/move",
            content='{"x": NaN, "y": 1, "z": 1}',
            headers={**h, "Content-Type": "application/json"},
        )
    ).status_code == 422
    assert (
        await client.post(f"/api/assets/{world['r1']}/move", json={"x": 1e12, "y": 1, "z": 1}, headers=h)
    ).status_code == 422
    assert await count_rows(AssetPose) == n  # nothing written by any rejected request


# ----------------------------------------------------------------- edges
async def test_overlapping_open_located_in_rejected(client, world, operator_headers, count_rows):
    n = await count_rows(AssetEdge)
    r = await client.post(
        f"/api/assets/{world['r1']}/edges",
        json={"parent_asset_id": world["zone-b"], "relation": "located_in"},
        headers=operator_headers,
    )
    assert r.status_code == 409
    assert await count_rows(AssetEdge) == n


async def test_serves_and_powered_by_edges(client, world, operator_headers, viewer_headers):
    r = await client.post(
        f"/api/assets/{world['r1']}/edges",
        json={"parent_asset_id": world["pdu1"], "relation": "powered_by", "valid_from": iso(T0)},
        headers=operator_headers,
    )
    assert r.status_code == 201, r.text
    # serves: the cooling asset is the child, the served zone the parent
    r2 = await client.post(
        f"/api/assets/{world['crac1']}/edges",
        json={"parent_asset_id": world["zone-a"], "relation": "serves", "valid_from": iso(T0)},
        headers=operator_headers,
    )
    assert r2.status_code == 201, r2.text
    dup = await client.post(
        f"/api/assets/{world['r1']}/edges",
        json={"parent_asset_id": world["pdu1"], "relation": "powered_by"},
        headers=operator_headers,
    )
    assert dup.status_code == 409
    got = (
        await client.get(
            f"/api/assets/{world['r1']}/edges", params={"as_of": iso(T0 + timedelta(hours=1))}, headers=viewer_headers
        )
    ).json()
    assert {e["relation"] for e in got["edges"]} == {"located_in", "powered_by"}
    # as-of before anything was valid -> empty
    early = (
        await client.get(
            f"/api/assets/{world['r1']}/edges", params={"as_of": iso(T0 - timedelta(days=1))}, headers=viewer_headers
        )
    ).json()
    assert early["edges"] == []


async def test_invalid_relation_and_types(client, world, operator_headers):
    h = operator_headers
    assert (
        await client.post(
            f"/api/assets/{world['r1']}/edges", json={"parent_asset_id": world["pdu1"], "relation": "owns"}, headers=h
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/assets/{world['r1']}/edges",
            json={"parent_asset_id": world["r2"], "relation": "powered_by"},
            headers=h,
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/assets/{world['r1']}/edges",
            json={"parent_asset_id": world["r1"], "relation": "powered_by"},
            headers=h,
        )
    ).status_code == 422
    assert (await client.get("/api/assets", params={"asset_type": "spaceship"}, headers=h)).status_code == 422
    assert (
        await client.get(f"/api/assets/{world['r1']}/edges", params={"relation": "owns"}, headers=h)
    ).status_code == 422


async def test_close_edge_keeps_history(client, world, operator_headers, viewer_headers):
    edge_id = (await client.get(f"/api/assets/{world['r2']}/edges", headers=viewer_headers)).json()["edges"][0]["id"]
    t_close = T0 + timedelta(days=3)
    r = await client.post(f"/api/edges/{edge_id}/close", json={"valid_to": iso(t_close)}, headers=operator_headers)
    assert r.status_code == 200 and r.json()["valid_to"] is not None
    assert (await client.post(f"/api/edges/{edge_id}/close", json={}, headers=operator_headers)).status_code == 409
    assert (await client.post("/api/edges/999999/close", json={}, headers=operator_headers)).status_code == 404
    during = (
        await client.get(
            f"/api/assets/{world['r2']}/edges",
            params={"as_of": iso(t_close - timedelta(seconds=1))},
            headers=viewer_headers,
        )
    ).json()
    after = (
        await client.get(f"/api/assets/{world['r2']}/edges", params={"as_of": iso(t_close)}, headers=viewer_headers)
    ).json()
    hist = (
        await client.get(f"/api/assets/{world['r2']}/edges", params={"include_history": "true"}, headers=viewer_headers)
    ).json()
    assert len(during["edges"]) == 1 and after["edges"] == [] and len(hist["edges"]) == 1
    # once closed, the child may be given a new located_in at/after the close instant
    again = await client.post(
        f"/api/assets/{world['r2']}/edges",
        json={"parent_asset_id": world["zone-a"], "relation": "located_in", "valid_from": iso(t_close)},
        headers=operator_headers,
    )
    assert again.status_code == 201, again.text


# ----------------------------------------------------------------- as-of
async def test_as_of_excludes_assets_with_no_pose_then(client, world, viewer_headers):
    before = (
        await client.get("/api/assets", params={"as_of": iso(T0 - timedelta(days=1))}, headers=viewer_headers)
    ).json()
    assert before["count"] == 0
    with_unplaced = (
        await client.get(
            "/api/assets",
            params={"as_of": iso(T0 - timedelta(days=1)), "include_unplaced": "true"},
            headers=viewer_headers,
        )
    ).json()
    assert with_unplaced["count"] == 6 and all(a["pose"] is None for a in with_unplaced["assets"])


async def test_as_of_naive_timestamp_is_utc(client, world, viewer_headers):
    r = await client.get("/api/assets", params={"as_of": "2026-01-02T00:00:00"}, headers=viewer_headers)
    assert r.status_code == 200 and r.json()["as_of"].startswith("2026-01-02T00:00:00")


async def test_retired_asset_hidden_after_retirement(client, world, viewer_headers, session_maker):
    async with session_maker() as s:
        a = await s.get(Asset, world["r2"])
        a.retired_at = T0 + timedelta(days=5)
        await s.commit()
    assert "r2" in external_ids(
        (await client.get("/api/assets", params={"as_of": iso(T0 + timedelta(days=4))}, headers=viewer_headers)).json()
    )
    assert "r2" not in external_ids(
        (await client.get("/api/assets", params={"as_of": iso(T0 + timedelta(days=5))}, headers=viewer_headers)).json()
    )


async def test_unknown_asset_edges_404(client, world, viewer_headers):
    assert (await client.get("/api/assets/999999/edges", headers=viewer_headers)).status_code == 404


async def test_no_facility_returns_404(client, viewer_headers):
    assert (await client.get("/api/facility", headers=viewer_headers)).status_code == 404
