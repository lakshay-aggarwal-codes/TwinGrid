"""Plugin: explainability and the Model Passport (Task 18). Read-only; nothing is written.

* ``GET /api/models/passport``              -- any signed-in user: one passport per model in ``models/registry.json``
  (status, data origin, headline metrics labelled "synthetic-data result", limitations, claim boundary) and, for PPO
  models, the STORED evaluation decision (for example ``NOT_EVALUATED``). Rules live in ``src/model_passport.py``.
* ``GET /api/alerts/{alert_id}/explanation`` -- any signed-in user: why a stored anomaly alert fired, from what the
  database and the detector config hold: score vs threshold and the deterministic range deviation of the linked sensor
  reading (``src/alert_explain.py``). The detector's reconstruction-error shares are not stored with an alert; they are
  live in the WebSocket frame while an episode is open, and the response says so.

Rate limit: the existing ``general`` class (no new setting). Errors carry fixed text; no path, SQL or traceback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.errors import ApiError
from api.rate_limit import http_limit
from api.repositories import data_repository
from api.services import anomaly_service, evaluation_service
from database import get_db
from models.db_models import SensorReading, User
from src import alert_explain, model_registry
from src.model_passport import build_passport

logger = logging.getLogger(__name__)
router = APIRouter(tags=["explainability"])


def detector_dir() -> Path:
    """The detector artifact directory (the pipeline's own setting). Tests point this at a temporary directory."""
    return Path(anomaly_service.ANOMALY_DETECTOR_PATH)


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("explainability: %s unreadable", path.name)
        return None
    return data if isinstance(data, dict) else None


def detector_info() -> Optional[dict[str, Any]]:
    """Threshold, input columns, training ranges and percentile of the configured detector, or None if unreadable."""
    base = detector_dir()
    cfg = _read_json(base / "config.json")
    scaler = _read_json(base / "scaler.json")
    if cfg is None or scaler is None:
        return None
    try:
        arrays = scaler["arrays"]
        lo = [float(x) for x in arrays["data_min_"]["values"]]
        hi = [float(x) for x in arrays["data_max_"]["values"]]
        cols = [str(c) for c in cfg["feature_columns"]]
        threshold = float(cfg["threshold"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (len(cols) == len(lo) == len(hi)):
        return None
    info: dict[str, Any] = {
        "threshold": threshold,
        "feature_columns": cols,
        "train_min": lo,
        "train_max": hi,
        "scaler": "MinMaxScaler",
    }
    if isinstance(cfg.get("percentile"), (int, float)):
        info["threshold_percentile"] = float(cfg["percentile"])
    return info


def latest_decision() -> Optional[dict[str, Any]]:
    """The decision of the newest stored evaluation report (with its id), or None when there is none."""
    try:
        listing = evaluation_service.list_evaluations()["evaluations"]
        if not listing:
            return None
        newest = listing[0]["evaluation_id"]
        decision = evaluation_service.get_evaluation(newest).get("decision")
    except Exception:  # a broken report must not take the passport down; the PPO state then says "not evaluated"
        logger.warning("explainability: evaluation decision unreadable", exc_info=True)
        return None
    return {**decision, "evaluation_id": newest} if isinstance(decision, dict) else None


@router.get("/api/models/passport", dependencies=[Depends(http_limit("general"))])
async def model_passport(_user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    try:
        entries = model_registry.read_registry()
    except (OSError, ValueError):
        logger.warning("explainability: registry unreadable", exc_info=True)
        raise ApiError(503, "registry_unavailable", "The model registry is not available") from None
    info = detector_info()
    detector = (
        {
            "threshold": info["threshold"],
            "threshold_percentile": info.get("threshold_percentile"),
            "feature_columns": info["feature_columns"],
        }
        if info
        else None
    )
    return build_passport(entries, decision=latest_decision(), detector=detector)


@router.get("/api/alerts/{alert_id}/explanation", dependencies=[Depends(http_limit("general"))])
async def alert_explanation(
    alert_id: int, _user: Annotated[User, Depends(get_current_user)], db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    alert = await data_repository.get_alert(db, alert_id)
    if alert is None:
        raise ApiError(404, "not_found", "Alert not found")
    body: dict[str, Any] = {
        "alert_id": alert.id,
        "model_version": alert.model_version,
        "method": alert_explain.METHOD,
        "method_text": alert_explain.METHOD_TEXT,
        "threshold_basis": "the alert threshold of the currently configured detector, not necessarily the one in force when the alert was raised",
        "score_vs_threshold": None,
        "features": None,
        "unavailable": [],
        "reading_origin": None,
    }
    info = detector_info()
    if info is None:
        body["unavailable"].append(
            "The detector configuration is not readable, so no threshold or training range is available."
        )
        return body
    try:
        body["score_vs_threshold"] = alert_explain.score_vs_threshold(float(alert.score), info["threshold"])
    except ValueError:
        body["unavailable"].append("The stored score is not a usable number.")
    reading = None
    if alert.sensor_reading_id is not None:
        reading = (
            await db.execute(select(SensorReading).where(SensorReading.id == alert.sensor_reading_id))
        ).scalar_one_or_none()
    if reading is None:
        body["unavailable"].append(
            "This alert is not linked to a stored sensor reading, so the per-signal deviation cannot be computed."
        )
    else:
        values = {c: getattr(reading, c, None) for c in info["feature_columns"]}
        try:
            body["features"] = alert_explain.feature_deviations(
                values, info["feature_columns"], info["train_min"], info["train_max"]
            )
            body["reading_origin"] = getattr(reading, "origin", None)
        except ValueError:
            body["unavailable"].append("The linked reading does not hold every detector input.")
    body["unavailable"].append(
        "The detector's own reconstruction-error shares are not stored with an alert; they are shown only while the anomaly episode is live."
    )
    return body
