"""Task 19: optimizer recommendation, sandbox and the propose -> approve flow (api/plugins/optimizer_proposals.py)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from api.plugins import optimizer_proposals as plugin
from models.db_models import AuditLog, OptimizerProposal
from src import optimizer_proposals as rules

UNAUTH = (401, 403)
CTX = {"utilisation": 0.7, "outside_temp": 24.0, "water_stress": 0.0}
BODY = {**CTX, "chilled_water_temp_c": 11.0, "cooling_mode": "hybrid"}
URL = "/api/optimizer/proposals"


def _run(pue, energy, co2, outlet):
    return {
        "hours": 24,
        "mean_pue": pue,
        "total_energy_kwh": energy,
        "total_co2_kg": co2,
        "max_outlet_temp_C": outlet,
        "carbon_data_is_real": False,
    }


@pytest.fixture
def fake_twin(monkeypatch):
    """SYNTHETIC predictions: the workflow tests do not depend on the physics (the real twin is used further down)."""
    state = {"outlet": 33.0}

    def predict(ctx, chilled_c, mode):
        return rules.predicted_effect(_run(1.5, 1000.0, 400.0, 30.0), _run(1.4, 900.0, 360.0, state["outlet"]), 35.0)

    monkeypatch.setattr(plugin, "_predict", predict)
    return state


async def audit_rows(session_maker, action: str) -> list[AuditLog]:
    async with session_maker() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all())


async def proposals(session_maker) -> list[OptimizerProposal]:
    async with session_maker() as s:
        return list((await s.execute(select(OptimizerProposal).order_by(OptimizerProposal.id))).scalars().all())


# ----------------------------------------------------------------------------- reads need a token only


async def test_reads_need_a_token(client):
    for path in (
        "/api/optimizer/baseline-recommendation",
        "/api/optimizer/sandbox?proposed_chilled_water_temp=10&proposed_mode=hybrid",
        URL,
    ):
        assert (await client.get(path)).status_code in UNAUTH


async def test_baseline_recommendation_is_labelled_and_persists_nothing(client, viewer_headers, count_rows):
    r = await client.get("/api/optimizer/baseline-recommendation", params=CTX, headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["persisted"] is False
    rec = body["recommendation"]
    assert rec["selected"]["name"] in ("pid", "rule") and "not an evaluation" in rec["note"]
    assert 5.0 <= rec["selected"]["chilled_water_temp_C"] <= 15.0
    assert body["predicted"]["label"] == "model estimate on simulated data"
    assert {"mean_pue", "total_energy_kwh", "total_co2_kg", "thermal_margin_C"} <= body["predicted"]["delta"].keys()
    assert await count_rows(OptimizerProposal) == 0


async def test_sandbox_is_read_only_and_validates_its_inputs(client, viewer_headers, count_rows):
    good = {**CTX, "proposed_chilled_water_temp": 9, "proposed_mode": "free_air"}
    ok = await client.get("/api/optimizer/sandbox", params=good, headers=viewer_headers)
    assert ok.status_code == 200 and ok.json()["persisted"] is False
    assert ok.json()["predicted"]["reference"]["max_outlet_temp_C"] > 0
    too_cold_or_hot = {"proposed_chilled_water_temp": 99, "proposed_mode": "hybrid"}
    for bad in (too_cold_or_hot, {"proposed_chilled_water_temp": 9, "proposed_mode": "turbo"}):
        r = await client.get("/api/optimizer/sandbox", params={**CTX, **bad}, headers=viewer_headers)
        assert r.status_code == 422
    assert await count_rows(OptimizerProposal) == 0


# ----------------------------------------------------------------------------- who may propose


async def test_a_viewer_cannot_propose_and_nothing_is_stored(client, viewer_headers, session_maker, fake_twin):
    r = await client.post(URL, json=BODY, headers=viewer_headers)
    assert r.status_code == 403
    assert await proposals(session_maker) == []
    assert await audit_rows(session_maker, "optimizer_proposal_created") == []
    (denied,) = await audit_rows(session_maker, "permission_denied")
    assert denied.outcome == "denied"


async def test_an_operator_proposal_is_stored_pending_with_origin_and_audited(
    client, operator_headers, session_maker, fake_twin
):
    r = await client.post(URL, json={**BODY, "rationale": "  cheaper at this load  "}, headers=operator_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending" and body["proposer"] == "operator1" and body["origin"] == "simulated"
    assert body["chilled_water_temp_C"] == 11.0 and body["cooling_mode"] == "hybrid"
    assert body["rationale"] == "cheaper at this load"
    assert body["predicted"]["within_outlet_limit"] is True
    assert body["predicted"]["label"] == "model estimate on simulated data"
    assert "does not apply" in body["approval_label"]
    (row,) = await proposals(session_maker)
    assert (row.status, row.origin) == ("pending", "simulated")
    (log,) = await audit_rows(session_maker, "optimizer_proposal_created")
    assert log.resource_id == str(row.id) and log.details["cooling_mode"] == "hybrid" and log.outcome == "success"


async def test_the_server_computes_the_prediction_and_ignores_client_numbers(client, operator_headers, fake_twin):
    r = await client.post(URL, json={**BODY, "predicted": {"delta": {"mean_pue": -9}}}, headers=operator_headers)
    assert r.status_code == 422  # unknown field refused: a client cannot supply its own prediction


async def test_a_setting_that_overheats_the_simulated_outlet_is_refused(
    client, operator_headers, session_maker, fake_twin
):
    fake_twin["outlet"] = 36.0  # above the 35 C limit used by the fake
    r = await client.post(URL, json=BODY, headers=operator_headers)
    assert r.status_code == 422 and r.json()["type"] == "urn:twingrid:error:unsafe_prediction"
    assert await proposals(session_maker) == []
    assert await audit_rows(session_maker, "optimizer_proposal_created") == []


@pytest.mark.parametrize(
    "patch",
    [
        {"chilled_water_temp_c": 4.9},
        {"chilled_water_temp_c": 15.1},
        {"cooling_mode": "turbo"},
        {"utilisation": 1.5},
        {"rationale": "x" * 501},
    ],
)
async def test_bad_proposals_are_422(client, operator_headers, fake_twin, patch):
    assert (await client.post(URL, json={**BODY, **patch}, headers=operator_headers)).status_code == 422


# ----------------------------------------------------------------------------- who may decide


async def _propose(client, headers):
    r = await client.post(URL, json=BODY, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_an_operator_cannot_approve(client, operator_headers, session_maker, fake_twin):
    pid = await _propose(client, operator_headers)
    r = await client.post(f"{URL}/{pid}/decision", json={"decision": "approve"}, headers=operator_headers)
    assert r.status_code == 403
    assert (await proposals(session_maker))[0].status == "pending"
    assert await audit_rows(session_maker, "optimizer_proposal_approved") == []


async def test_a_different_admin_approves_and_it_is_audited(
    client, operator_headers, make_user, session_maker, fake_twin
):
    pid = await _propose(client, operator_headers)
    _, admin = await make_user("admin1", "admin")
    decision = {"decision": "approve", "note": "  ok for the trial  "}
    r = await client.post(f"{URL}/{pid}/decision", json=decision, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["decided_by"], body["decision_note"]) == ("approved", "admin1", "ok for the trial")
    assert body["decided_at"] and "does not apply" in body["approval_label"]
    (log,) = await audit_rows(session_maker, "optimizer_proposal_approved")
    assert log.resource_id == str(pid) and log.details["decision"] == "approve" and log.details["note_added"] is True
    assert "trial" not in str(log.details)  # the note text is not copied into the audit row


async def test_rejection_is_recorded_and_audited(client, operator_headers, make_user, session_maker, fake_twin):
    pid = await _propose(client, operator_headers)
    _, admin = await make_user("admin1", "admin")
    r = await client.post(f"{URL}/{pid}/decision", json={"decision": "reject"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert len(await audit_rows(session_maker, "optimizer_proposal_rejected")) == 1


async def test_a_decision_is_final(client, operator_headers, make_user, session_maker, fake_twin):
    pid = await _propose(client, operator_headers)
    _, admin = await make_user("admin1", "admin")
    assert (await client.post(f"{URL}/{pid}/decision", json={"decision": "approve"}, headers=admin)).status_code == 200
    again = await client.post(f"{URL}/{pid}/decision", json={"decision": "reject"}, headers=admin)
    assert again.status_code == 409 and again.json()["type"] == "urn:twingrid:error:not_pending"
    assert (await proposals(session_maker))[0].status == "approved"
    assert await audit_rows(session_maker, "optimizer_proposal_rejected") == []


async def test_an_admin_cannot_decide_their_own_proposal(client, make_user, session_maker, fake_twin):
    _, admin = await make_user("admin1", "admin")
    pid = await _propose(client, admin)  # admins may propose
    r = await client.post(f"{URL}/{pid}/decision", json={"decision": "approve"}, headers=admin)
    assert r.status_code == 403 and r.json()["type"] == "urn:twingrid:error:self_decision"
    assert (await proposals(session_maker))[0].status == "pending"
    assert await audit_rows(session_maker, "optimizer_proposal_approved") == []


async def test_unknown_proposal_and_bad_decision(client, make_user, fake_twin):
    _, admin = await make_user("admin1", "admin")
    assert (await client.post(f"{URL}/424242/decision", json={"decision": "approve"}, headers=admin)).status_code == 404
    assert (await client.post(f"{URL}/1/decision", json={"decision": "maybe"}, headers=admin)).status_code == 422


# ----------------------------------------------------------------------------- listing and source


async def test_listing_filters_by_status_and_is_open_to_every_signed_in_user(
    client, operator_headers, viewer_headers, make_user, fake_twin
):
    first = await _propose(client, operator_headers)
    await _propose(client, operator_headers)
    _, admin = await make_user("admin1", "admin")
    await client.post(f"{URL}/{first}/decision", json={"decision": "approve"}, headers=admin)
    everything = (await client.get(URL, headers=viewer_headers)).json()
    assert len(everything) == 2
    pending = (await client.get(URL, params={"status": "pending"}, headers=viewer_headers)).json()
    assert [p["status"] for p in pending] == ["pending"]
    assert (await client.get(URL, params={"status": "bogus"}, headers=viewer_headers)).status_code == 422


async def test_source_is_the_baseline_only_when_the_setpoints_are_its_recommendation(
    client, operator_headers, monkeypatch, fake_twin
):
    selected = {"name": "pid", "chilled_water_temp_C": 11.0, "cooling_mode": "hybrid"}
    monkeypatch.setattr(plugin, "_recommend", lambda ctx: {"selected": selected, "considered": [], "note": ""})
    same = await client.post(URL, json=BODY, headers=operator_headers)
    edited = await client.post(URL, json={**BODY, "chilled_water_temp_c": 12.5}, headers=operator_headers)
    assert (same.json()["source"], edited.json()["source"]) == ("baseline:pid", "manual")


async def test_no_usable_baseline_means_a_manual_source_and_a_null_recommendation(
    client, operator_headers, viewer_headers, monkeypatch, fake_twin
):
    none_usable = {"selected": None, "considered": [{"name": "pid", "usable": False}], "note": "n"}
    monkeypatch.setattr(plugin, "_recommend", lambda ctx: none_usable)
    assert (await client.post(URL, json=BODY, headers=operator_headers)).json()["source"] == "manual"
    body = (await client.get("/api/optimizer/baseline-recommendation", params=CTX, headers=viewer_headers)).json()
    assert body["recommendation"]["selected"] is None and body["predicted"] is None


async def test_error_bodies_carry_no_internals(client, operator_headers, fake_twin):
    fake_twin["outlet"] = 40.0
    text = (await client.post(URL, json=BODY, headers=operator_headers)).text
    assert "Traceback" not in text and ".py" not in text and "SELECT" not in text
