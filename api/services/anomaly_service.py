"""Anomaly detector singleton + business logic for GET /api/anomaly_score."""

from __future__ import annotations
from api.middleware.metrics import MODEL_INFERENCE_COUNT
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from src.anomaly_detector import AnomalyDetector

logger = logging.getLogger(__name__)


_anomaly_detector: AnomalyDetector | None = None


def get_anomaly_detector() -> AnomalyDetector | None:
    global _anomaly_detector
    if _anomaly_detector is None:
        try:
            detector_path = Path("models/anomaly")
            if detector_path.exists():
                _anomaly_detector = AnomalyDetector.load(detector_path)
        except Exception as e:
            logger.warning("Anomaly detector not available: %s", e)
    return _anomaly_detector


def score_recent_data(recent_data_json: str) -> dict[str, Any]:
    """Returns a dict matching AnomalyScoreResponse's fields."""
    detector = get_anomaly_detector()
    if detector is None:
        return {"score": 0.0, "threshold": 1.0, "alert": False, "type": "normal", "message": "Anomaly detector not available"}

    try:
        data = json.loads(recent_data_json)
        arr = np.array(data, dtype=np.float32)
        if arr.shape != (12, 5):
            raise ValueError(f"Expected shape (12, 5), got {arr.shape}")
        errors, alerts = detector.detect(arr.reshape(1, 12, 5))
        MODEL_INFERENCE_COUNT.labels(model="anomaly_detector").inc()
        score = float(errors[0])
        alert = bool(alerts[0])
        threshold = detector.threshold or 1.0
        if alert:
            if arr[-1, 1] < 2.0:
                anomaly_type, message = "water_leak", "Water pressure anomaly detected - possible leak"
            elif arr[-1, 2] > 45:
                anomaly_type, message = "thermal_spike", "Outlet temperature spike detected"
            else:
                anomaly_type, message = "unknown", "Anomaly detected"
        else:
            anomaly_type, message = "normal", "No anomalies detected"
        return {"score": score, "threshold": threshold, "alert": alert, "type": anomaly_type, "message": message}
    except Exception as e:
        logger.exception("Anomaly detection error: %s", e)
        return {"score": 0.0, "threshold": 1.0, "alert": False, "type": "error", "message": f"Error: {str(e)}"}