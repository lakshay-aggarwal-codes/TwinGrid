"""GET /api/anomaly_score is pure (T3); alert severity mapping."""

import pytest
from fastapi import Response

from api.routes import anomaly_routes
from api.services import anomaly_service


class FakeSession:
    pass


def _result(**over):
    base = {"score": 0.001, "threshold": 0.006, "alert": False, "type": "normal", "message": "No anomalies detected"}
    base.update(over)
    return base


class TestAlertSeverity:
    def test_warning_up_to_twice_the_threshold(self):
        assert anomaly_service.alert_severity(0.0061, 0.006) == "WARNING"
        assert anomaly_service.alert_severity(0.012, 0.006) == "WARNING"  # exactly 2x is not "> 2x"

    def test_critical_above_twice_the_threshold(self):
        assert anomaly_service.alert_severity(0.0121, 0.006) == "CRITICAL"


class TestAnomalyRouteIsPure:
    """T3: GET /api/anomaly_score scores a caller-supplied window and NOTHING else."""

    @staticmethod
    async def _call(monkeypatch, result, *, dispatched=None):
        saved = []

        async def fake_save_alert(session, *a, **k):
            saved.append((a, k))

        async def fake_dispatch(payload):
            if dispatched is not None:
                dispatched.append(payload)

        monkeypatch.setattr(anomaly_service, "score_recent_data", lambda _raw: result)
        monkeypatch.setattr(anomaly_routes.data_repository, "save_alert", fake_save_alert)
        monkeypatch.setattr(anomaly_routes.webhook_service, "dispatch_alert", fake_dispatch)
        response = await anomaly_routes.anomaly_score(
            _user=object(), response=Response(), session=FakeSession(), recent_data="[]"
        )
        return response, saved

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "result",
        [
            _result(),
            _result(score=0.0, threshold=1.0, type="unavailable", message="Anomaly detector not available"),
            _result(score=0.008, alert=True, type="thermal_spike", message="Outlet temperature spike detected"),
            _result(score=0.05, alert=True, type="unknown", message="Anomaly detected"),
        ],
    )
    async def test_nothing_is_persisted_or_dispatched(self, monkeypatch, result):
        dispatched = []
        response, saved = await self._call(monkeypatch, result, dispatched=dispatched)
        assert saved == [] and dispatched == []
        assert response.alert is result["alert"]

    @pytest.mark.asyncio
    async def test_response_is_marked_deprecated(self, monkeypatch):
        monkeypatch.setattr(anomaly_service, "score_recent_data", lambda _raw: _result())
        resp = Response()
        await anomaly_routes.anomaly_score(_user=object(), response=resp, session=FakeSession(), recent_data="[]")
        assert resp.headers["deprecation"] == "true"
        assert "/api/anomaly/status" in resp.headers["link"]

    @pytest.mark.asyncio
    async def test_development_rollback_lever_restores_legacy_persistence(self, monkeypatch):
        monkeypatch.setenv("ANOMALY_SERVER_SIDE", "false")
        monkeypatch.setenv("ENVIRONMENT", "development")
        dispatched = []
        _, saved = await self._call(
            monkeypatch, _result(score=0.008, alert=True, type="thermal_spike", message="x"), dispatched=dispatched
        )
        assert len(saved) == 1 and saved[0][1]["severity"] == "WARNING" and len(dispatched) == 1

    @pytest.mark.asyncio
    async def test_rollback_lever_is_inert_outside_development(self, monkeypatch):
        monkeypatch.setenv("ANOMALY_SERVER_SIDE", "false")
        monkeypatch.setenv("ENVIRONMENT", "production")
        _, saved = await self._call(monkeypatch, _result(score=0.05, alert=True, type="unknown", message="x"))
        assert saved == []
