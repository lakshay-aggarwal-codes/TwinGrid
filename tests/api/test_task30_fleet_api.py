"""Task 30 over HTTP: `GET /api/fleet/sites`."""


async def test_requires_a_signed_in_user(client):
    assert (await client.get("/api/fleet/sites")).status_code == 401


async def test_returns_five_labelled_simulated_ranked_sites(client, viewer_headers):
    r = await client.get("/api/fleet/sites", headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["simulated"] is True and "Not real facilities" in body["label"]
    sites = body["sites"]
    assert len(sites) == 5 and [s["overall_rank"] for s in sites] == sorted(s["overall_rank"] for s in sites)
    assert sorted(s["rank"]["pue"] for s in sites)[0] == 1
    assert all(s["name"].startswith("Simulated site") for s in sites)
    assert body["carbon_note"] and body["alert_note"]


async def test_the_flat_carbon_fallback_is_stated_not_hidden(client, viewer_headers):
    body = (await client.get("/api/fleet/sites", headers=viewer_headers)).json()
    if not body["carbon_data_is_real"]:
        assert "flat assumed grid intensity" in body["carbon_note"]


async def test_the_live_twin_is_not_advanced(client, viewer_headers):
    from api.services import twin_service

    twin = twin_service.get_twin()
    before = twin._time
    await client.get("/api/fleet/sites", headers=viewer_headers)
    assert twin_service.get_twin()._time == before
