"""Task 14: POST /api/copilot/ask (api/plugins/copilot.py). Rule-based, read-only, bounded, evidence-cited.

Lives beside the other ``test_copilot_*`` files (the card's verify glob) and re-uses the HTTP fixtures of ``tests/api``.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from api.rate_limit import limiter
from models.db_models import Alert, AuditLog, SensorReading
from tests.api import conftest as _http
from tests.api import test_task18_explainability as _t18

# Fixtures of tests/api, re-exported by assignment (an import would be flagged as shadowed by every test parameter).
client, engine, session_maker, make_user = _http.client, _http.engine, _http.session_maker, _http.make_user
viewer_headers, operator_headers, count_rows = _http.viewer_headers, _http.operator_headers, _http.count_rows
detector_dir, seed = _t18.detector_dir, _t18.seed

URL = "/api/copilot/ask"
EVIDENCE_KEYS = {"id", "source", "entity", "field", "value", "unit", "observed_at", "origin", "freshness"}


def body(question="Why is this alert red?", kind="alert", cid="1", **extra):
    return {"question": question, "context": {"kind": kind, "id": cid}, **extra}


async def test_it_needs_a_token(client):
    assert (await client.post(URL, json=body())).status_code in (401, 403)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 501},
        {"question": "ok", "extra": 1},
        {"question": "ok", "context": {"kind": "nonsense"}},
        {"question": "ok", "context": {"kind": "alert", "id": "x" * 65}},
        {"question": "ok", "context": {"kind": "alert", "oops": 1}},
        {"question": "ok", "history": [{"role": "user", "text": "h"}] * 7},
        {"question": "ok", "history": [{"role": "system", "text": "h"}]},
        {"question": "ok", "history": [{"role": "user", "text": "x" * 501}]},
    ],
)
async def test_invalid_requests_are_422(client, viewer_headers, payload):
    r = await client.post(URL, json=payload, headers=viewer_headers)
    assert r.status_code == 422


async def test_an_unknown_alert_is_404_and_a_known_one_is_answered(client, viewer_headers, session_maker, detector_dir):
    missing = await client.post(URL, json=body(cid="999"), headers=viewer_headers)
    assert missing.status_code == 404 and missing.json()["type"].endswith("not_found")
    await seed(session_maker, score=0.03)
    async with session_maker() as s:
        alert_id = (await s.execute(select(Alert.id))).scalar_one()
    r = await client.post(URL, json=body(cid=str(alert_id)), headers=viewer_headers)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"request_id", "mode", "answer", "evidence", "unknowns", "warnings", "links", "limits"}
    assert data["mode"] == "rule_based" and data["limits"] == {"provider_configured": False}
    assert data["request_id"] == r.headers["x-request-id"]
    assert len(data["answer"]) <= 1500 and data["evidence"] and all(set(e) == EVIDENCE_KEYS for e in data["evidence"])
    score = next(e for e in data["evidence"] if e["field"] == "score")
    assert (
        score["value"] == pytest.approx(0.03)
        and score["origin"] == "simulated"
        and f"[{score['id']}]" in data["answer"]
    )
    assert any("Root cause is not determined" in u for u in data["unknowns"])


async def test_every_role_may_ask_and_nothing_is_written(
    client, viewer_headers, operator_headers, session_maker, count_rows
):
    before = [await count_rows(m) for m in (Alert, SensorReading, AuditLog)]
    for headers in (viewer_headers, operator_headers):
        r = await client.post(URL, json=body("What is the what-if lab?", "general", None), headers=headers)
        assert r.status_code == 200 and r.json()["links"] == [{"label": "What-if lab", "path": "/whatif-lab"}]
    assert [await count_rows(m) for m in (Alert, SensorReading, AuditLog)] == before


async def test_a_signal_without_samples_is_an_unknown_not_a_404(client, viewer_headers):
    r = await client.post(
        URL, json=body("What is the current status?", "signal", "no-such-sensor"), headers=viewer_headers
    )
    assert r.status_code == 200 and r.json()["evidence"] == [] and r.json()["unknowns"]


async def test_the_question_and_the_alert_text_are_never_logged(client, viewer_headers, caplog):
    secret = "zebra-quartz-7731"
    with caplog.at_level(logging.DEBUG):
        r = await client.post(URL, json=body(f"Tell me about {secret}", "general", None), headers=viewer_headers)
    assert r.status_code == 200 and secret not in caplog.text
    assert any("copilot_ask request_id=" in rec.getMessage() for rec in caplog.records)


async def test_it_is_rate_limited_with_the_existing_limiter(client):
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [(await client.post(URL, json=body())).status_code for _ in range(31)]
    finally:
        limiter.reset()
        limiter.enabled = False
    assert codes[0] in (401, 403) and codes[-1] == 429


async def test_the_openapi_document_describes_the_contract(client):
    spec = (await client.get("/openapi.json")).json()
    assert "post" in spec["paths"][URL] and "get" not in spec["paths"][URL]
    schemas = spec["components"]["schemas"]
    assert schemas["AskRequest"]["additionalProperties"] is False and schemas["AskRequest"]["required"] == ["question"]
    assert schemas["AskRequest"]["properties"]["question"]["maxLength"] == 500
    assert set(schemas["AskResponse"]["properties"]) == {
        "request_id",
        "mode",
        "answer",
        "evidence",
        "unknowns",
        "warnings",
        "links",
        "limits",
    }
