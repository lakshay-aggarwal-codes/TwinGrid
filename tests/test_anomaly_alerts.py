"""Alert persistence for GET /api/anomaly_score: only real alerts are stored."""

import pytest

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


class TestAnomalyRoutePersistence:
    @staticmethod
    async def _call(monkeypatch, result):
        saved = []

        async def fake_save_alert(session, score, alert, type_, message, severity=None):
            saved.append({"score": score, "alert": alert, "type": type_, "message": message, "severity": severity})

        monkeypatch.setattr(anomaly_service, "score_recent_data", lambda _raw: result)
        monkeypatch.setattr(anomaly_routes.data_repository, "save_alert", fake_save_alert)
        response = await anomaly_routes.anomaly_score(_user=object(), session=FakeSession(), recent_data="[]")
        return response, saved

    @pytest.mark.asyncio
    async def test_normal_result_is_not_persisted(self, monkeypatch):
        response, saved = await self._call(monkeypatch, _result())
        assert saved == []
        assert response.alert is False

    @pytest.mark.asyncio
    async def test_detector_unavailable_is_not_persisted(self, monkeypatch):
        _, saved = await self._call(
            monkeypatch, _result(score=0.0, threshold=1.0, message="Anomaly detector not available")
        )
        assert saved == []

    @pytest.mark.asyncio
    async def test_alert_is_persisted_with_warning_severity(self, monkeypatch):
        _, saved = await self._call(
            monkeypatch, _result(score=0.008, alert=True, type="thermal_spike", message="Outlet temperature spike detected")
        )
        assert len(saved) == 1 and saved[0]["severity"] == "WARNING" and saved[0]["alert"] is True

    @pytest.mark.asyncio
    async def test_strong_alert_is_persisted_as_critical(self, monkeypatch):
        _, saved = await self._call(monkeypatch, _result(score=0.05, alert=True, type="unknown", message="Anomaly detected"))
        assert len(saved) == 1 and saved[0]["severity"] == "CRITICAL"
