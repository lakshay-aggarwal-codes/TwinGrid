"""Task 16: HTTP behaviour of the dataset telemetry routes. SYNTHETIC bundle only (built from a year-2000 panel).

Conformance of the bodies is proven in tests/test_dataset_telemetry_service.py; here: access order, error shapes,
headers, isolation from the live routes. Every successful body is also passed through the reference validator.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio

from api import auth
from api.main import app
from api.services import dataset_bundle_service as svc
from research.danish_aau.contract import telemetry_contract as contract
from src.dataset_bundle.loader import build_bundle
from tests.test_dataset_bundle import _panel

FAC, DS, STREAM = "fac-1", "danish-aau-v5", "import:danish-aau-v5"
T1 = "danish-aau-v5.temperature.mod1.ch1"
Q = {"facility_id": FAC, "stream": STREAM}
BASE = f"/api/datasets/{DS}"


@pytest.fixture
def bundle_path(tmp_path_factory):
    d = tmp_path_factory.mktemp("t16")
    out = d / "bundle" / "danish-aau-v5.sqlite"
    build_bundle(_panel(d), out)
    return out


@pytest.fixture
def served(bundle_path, monkeypatch):
    monkeypatch.setenv(svc.BUNDLE_ENV, str(bundle_path))
    monkeypatch.setenv(svc.FACILITY_ENV, FAC)


@pytest_asyncio.fixture
async def demo_headers(make_user):
    user, _ = await make_user("demo-viewer", "viewer")
    token = jwt.encode(
        {"sub": str(user.id), "role": "viewer", "demo": True, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        auth.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


async def _ok(client, headers, path, **params):
    r = await client.get(path, params={**Q, **params}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "private, no-store"
    return r.json()


# ----------------------------------------------------------------------------------------------- access order
async def test_anonymous_is_401_even_when_no_bundle_is_configured(client, monkeypatch):
    monkeypatch.delenv(svc.BUNDLE_ENV, raising=False)
    assert (await client.get(f"{BASE}/sensors", params=Q)).status_code == 401


async def test_demo_token_is_refused_with_its_own_code_before_anything_else(client, served, demo_headers):
    r = await client.get(f"{BASE}/sensors", params=Q, headers=demo_headers)
    assert r.status_code == 403 and r.json()["type"].endswith("dataset_not_available_to_demo")
    assert (await client.get(f"{BASE}/sensors", headers=demo_headers)).status_code == 403  # even without parameters


async def test_no_bundle_or_no_facility_setting_is_404_like_an_unknown_route(
    client, viewer_headers, monkeypatch, bundle_path
):
    monkeypatch.delenv(svc.BUNDLE_ENV, raising=False)
    monkeypatch.setenv(svc.FACILITY_ENV, FAC)
    a = await client.get(f"{BASE}/sensors", params=Q, headers=viewer_headers)
    unknown = await client.get("/api/datasets-x/nothing", headers=viewer_headers)
    assert a.status_code == 404 and unknown.status_code == 404 and a.json()["detail"] == unknown.json()["detail"]
    monkeypatch.setenv(svc.BUNDLE_ENV, str(bundle_path))
    monkeypatch.delenv(svc.FACILITY_ENV)
    assert (await client.get(f"{BASE}/sensors", params=Q, headers=viewer_headers)).status_code == 404
    monkeypatch.setenv(svc.FACILITY_ENV, FAC)
    monkeypatch.setenv(svc.BUNDLE_ENV, str(bundle_path.with_name("gone.sqlite")))
    assert (await client.get(f"{BASE}/sensors", params=Q, headers=viewer_headers)).status_code == 404


async def test_viewer_and_operator_can_read(client, served, viewer_headers, operator_headers):
    for h in (viewer_headers, operator_headers):
        contract_ok = await _ok(client, h, f"{BASE}/sensors")
        assert contract.validate_envelope(contract_ok) == []


# ----------------------------------------------------------------------------------------------- request identity
@pytest.mark.parametrize(
    "params, status, code",
    [
        ({"stream": STREAM}, 400, "bad_request"),
        ({"facility_id": FAC}, 400, "stream_required"),
        ({"facility_id": "other", "stream": STREAM}, 404, "unknown_facility"),
        ({"facility_id": FAC, "stream": "live"}, 400, "bad_request"),
        ({"facility_id": FAC, "stream": "import:other"}, 400, "bad_request"),
    ],
)
async def test_missing_or_wrong_identity_is_a_contract_error_envelope(
    client, served, viewer_headers, params, status, code
):
    r = await client.get(f"{BASE}/sensors", params=params, headers=viewer_headers)
    body = r.json()
    assert r.status_code == status and body["code"] == code and body["kind"] == "error"
    assert contract.validate_envelope(body) == [] and r.headers["content-type"].startswith("application/json")


async def test_unknown_dataset_and_unknown_entity_use_the_envelope(client, served, viewer_headers):
    r = await client.get("/api/datasets/other/sensors", params=Q, headers=viewer_headers)
    assert (r.status_code, r.json()["code"]) == (404, "unknown_dataset")
    r = await client.get(f"{BASE}/sensors/nope/latest", params=Q, headers=viewer_headers)
    assert (r.status_code, r.json()["code"]) == (404, "unknown_entity")
    r = await client.get(f"{BASE}/racks/9", params=Q, headers=viewer_headers)
    assert (r.status_code, r.json()["code"]) == (404, "unknown_entity")


async def test_bad_parameters_are_400_envelopes_not_utc_guesses(client, served, viewer_headers):
    for p in ({"from_source_text": "2000-01-01T00:00:00Z"}, {"limit": "5000"}, {"cursor": "x"}):
        r = await client.get(f"{BASE}/sensors/{T1}/history", params={**Q, **p}, headers=viewer_headers)
        assert r.status_code == 400 and r.json()["code"] == "bad_request"


# ----------------------------------------------------------------------------------------------- bodies
async def test_every_route_returns_a_contract_valid_body(client, served, viewer_headers):
    h = viewer_headers
    for path in (
        f"{BASE}/sensors",
        f"{BASE}/sensors/{T1}/latest",
        f"{BASE}/sensors/{T1}/history",
        f"{BASE}/racks/1",
        f"{BASE}/racks/5",
        f"{BASE}/derived/derived.rack_power_total_1_6/latest",
        f"{BASE}/derived/derived.rack_power_total_1_6/history",
    ):
        assert contract.validate_envelope(await _ok(client, h, path)) == [], path
    d = await _ok(client, h, BASE)
    assert d["licence"] == "CC BY 4.0" and d["data_status"] == "historical_import_not_live" and d["attribution_text"]


async def test_history_pages_by_cursor_and_two_racks_never_share_records(client, served, viewer_headers):
    page = await _ok(client, viewer_headers, f"{BASE}/sensors/{T1}/history", limit="7")
    assert page["count"] == 7 and page["page"]["next_cursor"]
    nxt = await _ok(
        client, viewer_headers, f"{BASE}/sensors/{T1}/history", limit="7", cursor=page["page"]["next_cursor"]
    )
    assert nxt["records"][0]["ts_source_text"] > page["records"][-1]["ts_source_text"]
    r1, r2 = [await _ok(client, viewer_headers, f"{BASE}/racks/{n}") for n in (1, 2)]
    ids1 = {t["sensor_external_id"] for t in r1["temperature_sensors"]}
    ids2 = {t["sensor_external_id"] for t in r2["temperature_sensors"]}
    assert ids1 and ids2 and not ids1 & ids2
    assert r1["power"]["value"] is None and r1["power"]["split_allowed"] is False


async def test_derived_series_is_not_reachable_through_the_measured_routes(client, served, viewer_headers):
    r = await client.get(f"{BASE}/sensors/derived.rack_power_total_1_6/latest", params=Q, headers=viewer_headers)
    assert (r.status_code, r.json()["code"]) == (404, "unknown_entity")
    r = await client.get(f"{BASE}/derived/{T1}/latest", params=Q, headers=viewer_headers)
    assert (r.status_code, r.json()["code"]) == (404, "unknown_entity")


async def test_the_routes_are_get_only(client, served, viewer_headers):
    for method in ("post", "put", "patch", "delete"):
        r = await getattr(client, method)(f"{BASE}/sensors", params=Q, headers=viewer_headers)
        assert r.status_code in (403, 405)


# ----------------------------------------------------------------------------------------------- isolation
async def test_live_routes_and_the_route_table_are_untouched(client):
    paths = set(app.openapi()["paths"])
    assert "/api/telemetry/sensors/{external_id}/samples" in paths
    assert not any(p.startswith("/api/datasets") and "/api/telemetry" in p for p in paths)
    assert {p for p in paths if p.startswith("/api/datasets")} == {
        "/api/datasets/{dataset_id}",
        "/api/datasets/{dataset_id}/sensors",
        "/api/datasets/{dataset_id}/sensors/{sensor}/latest",
        "/api/datasets/{dataset_id}/sensors/{sensor}/history",
        "/api/datasets/{dataset_id}/racks/{source_rack_id}",
        "/api/datasets/{dataset_id}/derived/{name}/latest",
        "/api/datasets/{dataset_id}/derived/{name}/history",
    }


async def test_a_forged_or_expired_demo_claim_is_a_401(client, served, make_user):
    user, _ = await make_user("u-forged", "viewer")
    forged = jwt.encode({"sub": str(user.id), "demo": True, "exp": time.time() + 600}, "wrong-key", algorithm="HS256")
    r = await client.get(f"{BASE}/sensors", params=Q, headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
