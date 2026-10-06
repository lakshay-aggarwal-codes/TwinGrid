"""Anomaly detector singleton, pure scoring, and the server-owned anomaly pipeline.

* ``score_recent_data`` -- PURE scoring of a caller-supplied window (GET /api/anomaly_score,
  deprecated). It never persists anything and never dispatches a webhook.
* ``AnomalyPipeline`` (T3) -- the only thing that creates alerts. It scores the SERVER-held
  telemetry window once per live tick, fails closed, and keeps one alert per anomaly episode.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
from prometheus_client import Counter

from api.middleware.metrics import MODEL_INFERENCE_COUNT, registry
from api.repositories import data_repository
from api.services import telemetry_window, webhook_service
from src.anomaly_detector import AnomalyDetector
from src.anomaly_explain import explain

logger = logging.getLogger(__name__)

# models/anomaly must contain config.json + model.keras + scaler.joblib together.
ANOMALY_DETECTOR_PATH = Path(os.getenv("ANOMALY_DETECTOR_PATH", "models/anomaly"))

DETECTOR_ID = "lstm_autoencoder"
# D-4: the shipped detector is trained on synthetic data only. Reported in every status
# object until real data replaces it; do not change without changing the training data.
TRAINED_ON = "synthetic"

STATUS_WARMING_UP = "warming_up"
STATUS_OK = "ok"
STATUS_ANOMALOUS = "anomalous"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"

# PROPOSED (roadmap T3): an episode closes after K consecutive normal windows.
DEFAULT_EPISODE_CLOSE_AFTER = 3
DEFAULT_SCORE_TIMEOUT_S = 2.0
DETECTOR_RETRY_INTERVAL_S = 30.0

ANOMALY_SCORING_ERRORS = Counter(
    "anomaly_scoring_errors_total", "Anomaly scoring attempts that failed (status=error)", registry=registry
)
ANOMALY_ALERTS_CREATED = Counter(
    "anomaly_alerts_created_total", "Alerts persisted by the anomaly pipeline", ["type"], registry=registry
)

_anomaly_detector: Optional[AnomalyDetector] = None
_last_load_attempt: Optional[float] = None
_model_version_cache: dict[str, str] = {}


def server_side_enabled() -> bool:
    """ANOMALY_SERVER_SIDE=false turns the pipeline off (DEVELOPMENT ONLY rollback lever)."""
    return os.getenv("ANOMALY_SERVER_SIDE", "true").strip().lower() not in ("0", "false", "no")


def _is_development() -> bool:
    return os.getenv("ENVIRONMENT", "").strip().lower() == "development"


def legacy_route_persistence_enabled() -> bool:
    """Rollback only: with ANOMALY_SERVER_SIDE=false AND ENVIRONMENT=development the deprecated
    score route persists/dispatches again. That re-enables alert forgery, so never in production."""
    return (not server_side_enabled()) and _is_development()


def get_anomaly_detector() -> Optional[AnomalyDetector]:
    global _anomaly_detector, _last_load_attempt
    if _anomaly_detector is None:
        now = time.monotonic()
        # A missing/corrupt artifact must not be re-loaded (possibly importing TensorFlow) every tick.
        if _last_load_attempt is not None and now - _last_load_attempt < DETECTOR_RETRY_INTERVAL_S:
            return None
        _last_load_attempt = now
        try:
            if ANOMALY_DETECTOR_PATH.exists():
                _anomaly_detector = AnomalyDetector.load(ANOMALY_DETECTOR_PATH)
        except Exception as e:
            logger.warning("Anomaly detector not available: %s", e)
    return _anomaly_detector


def get_model_version() -> str:
    """Stable id of the loaded artifact: sha256 over config.json + model.keras (first 12 hex).
    Not a registry version (that is T6); it changes whenever the artifact changes."""
    key = str(ANOMALY_DETECTOR_PATH)
    cached = _model_version_cache.get(key)
    if cached:
        return cached
    h = hashlib.sha256()
    found = False
    for name in ("config.json", "model.keras"):
        f = ANOMALY_DETECTOR_PATH / name
        if f.is_file():
            found = True
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
    version = f"sha256-{h.hexdigest()[:12]}" if found else "unknown"
    if found:
        _model_version_cache[key] = version
    return version


def alert_severity(score: float, threshold: float) -> str:
    """CRITICAL when the reconstruction error is more than twice the trained
    alert threshold, otherwise WARNING. Only meaningful for real alerts."""
    return "CRITICAL" if score > 2 * threshold else "WARNING"


def score_window_features(features: Any) -> dict[str, Any]:
    """Score one (12, 5) window. Blocking (model inference): call from a worker thread.

    Fails CLOSED -- the returned ``status`` is one of ok | anomalous | unavailable | error and
    unavailable/error are never reported as normal. Never raises. Does not persist anything.
    """
    detector = get_anomaly_detector()
    if detector is None:
        return {
            "status": STATUS_UNAVAILABLE,
            "score": None,
            "threshold": None,
            "alert": False,
            "type": "unavailable",
            "message": "Anomaly detector not available",
            "explanation": None,
            "model_version": None,
        }
    try:
        arr = np.array(features, dtype=np.float32)
        if arr.shape != (12, 5):
            raise ValueError(f"Expected shape (12, 5), got {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise ValueError("Window contains non-finite values")
        errors, alerts = detector.detect(arr.reshape(1, 12, 5))
        MODEL_INFERENCE_COUNT.labels(model="anomaly_detector").inc()
        score = float(errors[0])
        alert = bool(alerts[0])
        threshold = detector.threshold or 1.0
        explanation = None
        if alert:
            # Only explain real alerts -- a second forward pass through the model.
            explanation = explain(detector, arr.reshape(1, 12, 5))[0]
            if arr[-1, 1] < 2.0:
                anomaly_type, message = "water_leak", "Water pressure anomaly detected - possible leak"
            elif arr[-1, 2] > 45:
                anomaly_type, message = "thermal_spike", "Outlet temperature spike detected"
            else:
                anomaly_type, message = "unknown", "Anomaly detected"
        else:
            anomaly_type, message = "normal", "No anomalies detected"
        return {
            "status": STATUS_ANOMALOUS if alert else STATUS_OK,
            "score": score,
            "threshold": threshold,
            "alert": alert,
            "type": anomaly_type,
            "message": message,
            "explanation": explanation,
            "model_version": get_model_version(),
        }
    except Exception as e:
        logger.exception("Anomaly detection error: %s", e)
        ANOMALY_SCORING_ERRORS.inc()
        return {
            "status": STATUS_ERROR,
            "score": None,
            "threshold": None,
            "alert": False,
            "type": "error",
            "message": f"Error: {str(e)}",
            "explanation": None,
            "model_version": None,
        }


def score_recent_data(recent_data_json: str) -> dict[str, Any]:
    """PURE scoring of a caller-supplied window (deprecated GET /api/anomaly_score).
    Returns a dict matching AnomalyScoreResponse's fields. No persistence, no webhook.
    A missing detector is type "unavailable" and a failure is type "error" -- never "normal"."""
    try:
        data = json.loads(recent_data_json)
    except Exception as e:
        ANOMALY_SCORING_ERRORS.inc()
        return {
            "score": 0.0,
            "threshold": 1.0,
            "alert": False,
            "type": "error",
            "message": f"Error: {str(e)}",
            "explanation": None,
        }
    r = score_window_features(data)
    return {
        "score": r["score"] if r["score"] is not None else 0.0,
        "threshold": r["threshold"] if r["threshold"] is not None else 1.0,
        "alert": r["alert"],
        "type": r["type"],
        "message": r["message"],
        "explanation": r["explanation"],
    }


# ----------------------------------------------------------------------------- pipeline
def _iso_now() -> str:
    return datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()


_SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


@dataclass
class _Episode:
    kind: str  # "anomaly" | "outage"
    start_seq: int
    dedupe_key: str
    type: str
    message: str
    severity: str
    score: float
    origin: str
    model_version: Optional[str]
    alert_id: Optional[int] = None
    persisted: bool = False
    normal_streak: int = 0


class AnomalyPipeline:
    """Server-owned anomaly scoring. ``process`` is called ONCE per live tick by ``_tick`` (not per
    client), so any number of connected WebSocket clients yields one score and at most one alert per
    episode.

    Episode rules (roadmap T3): an episode opens when the score crosses the (unchanged) trained
    threshold and persists one Alert; it closes after ``close_after`` consecutive normal windows;
    a higher severity UPDATES the open alert; a detector outage opens one ``detector_unavailable``
    alert per outage. ``error`` results never create alerts and never count as normal.
    """

    def __init__(self, close_after: Optional[int] = None) -> None:
        self.close_after = close_after or int(os.getenv("ANOMALY_EPISODE_CLOSE_AFTER", DEFAULT_EPISODE_CLOSE_AFTER))
        self._episode: Optional[_Episode] = None
        self._outage: Optional[_Episode] = None
        self._latest: Optional[dict[str, Any]] = None
        self._inflight: Optional[asyncio.Future] = None
        self.pending: set[asyncio.Task] = set()  # fire-and-forget webhook deliveries
        self.last_window: Optional[telemetry_window.WindowEvaluation] = (
            None  # T17: why the last tick was/was not scored
        )

    # -- public ---------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Latest status object (warming_up with the current fill before the first score)."""
        if self._latest is not None:
            return dict(self._latest)
        n = (
            len(telemetry_window.get_window_provider().window(telemetry_window.WINDOW_SIZE))
            if telemetry_window.effective_window_source() == "memory"
            else 0  # store source: the fill is only known after a tick has read the store
        )
        return self._status(STATUS_WARMING_UP, "Collecting telemetry window", filled=n)

    async def process(
        self, *, session_factory: Callable[[], Any], sensor_reading_id: Optional[int] = None
    ) -> dict[str, Any]:
        """Score the server-held window (if full), update episodes, return the status object."""
        # T17: the window comes from STORED samples (TELEMETRY_WINDOW_SOURCE=store, default) and is scorable only
        # when contiguous, valid, single-origin and at the model cadence; ``memory`` is the rollback source.
        window = await telemetry_window.current_window(session_factory)
        self.last_window = window
        samples = window.samples
        filled = window.filled

        if not server_side_enabled():
            return self._remember(
                self._status(STATUS_UNAVAILABLE, "Server-side anomaly pipeline disabled", filled=filled)
            )
        if not window.scorable:
            # No score, no episode change. The reason is carried in ``message`` (the status object's keys are unchanged).
            message = (
                "Collecting telemetry window"
                if window.reason == telemetry_window.REASON_INSUFFICIENT
                else f"Telemetry window not scorable (reason: {window.reason})"
            )
            return self._remember(self._status(STATUS_WARMING_UP, message, filled=filled))

        seq = samples[-1].seq
        origin = telemetry_window.lowest_evidence_origin([x.origin for x in samples])
        result = await self._score([list(x.features) for x in samples])
        status = result["status"]

        if status in (STATUS_OK, STATUS_ANOMALOUS):
            await self._close_outage()
        if status == STATUS_UNAVAILABLE:
            await self._open_outage(seq, origin, session_factory, sensor_reading_id)
        elif status == STATUS_ANOMALOUS:
            await self._on_anomalous(result, seq, origin, session_factory, sensor_reading_id)
        elif status == STATUS_OK:
            await self._on_normal(session_factory, sensor_reading_id)
        # STATUS_ERROR: no alert, no episode change (an error is neither anomalous nor normal).

        # Retry persistence of an episode whose alert could not be saved (idempotent on dedupe_key).
        for ep in (self._episode, self._outage):
            if ep is not None and not ep.persisted:
                await self._persist(ep, session_factory, sensor_reading_id)

        return self._remember(
            self._status(
                status,
                result["message"],
                filled=filled,
                seq=seq,
                origin=origin,
                score=result["score"],
                threshold=result["threshold"],
                type_=result["type"],
                explanation=result["explanation"],
                model_version=result.get("model_version"),
            )
        )

    # -- scoring (worker thread, bounded) --------------------------------------------------
    async def _score(self, features: list[list[float]]) -> dict[str, Any]:
        if self._inflight is not None and not self._inflight.done():
            ANOMALY_SCORING_ERRORS.inc()
            return self._error("Scoring skipped: previous scoring still running")
        fut = asyncio.ensure_future(asyncio.to_thread(score_window_features, features))
        self._inflight = fut
        timeout = float(os.getenv("ANOMALY_SCORE_TIMEOUT_S", DEFAULT_SCORE_TIMEOUT_S))
        try:
            # shield: on timeout the thread keeps running; _inflight blocks a concurrent second call.
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            ANOMALY_SCORING_ERRORS.inc()
            return self._error(f"Scoring timed out after {timeout:g}s")
        except Exception as e:  # defensive: score_window_features never raises
            logger.exception("Unexpected scoring failure")
            ANOMALY_SCORING_ERRORS.inc()
            return self._error(f"Error: {e}")

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {
            "status": STATUS_ERROR,
            "score": None,
            "threshold": None,
            "alert": False,
            "type": "error",
            "message": message,
            "explanation": None,
            "model_version": None,
        }

    # -- episodes --------------------------------------------------------------------------
    async def _on_anomalous(self, r, seq, origin, session_factory, reading_id) -> None:
        severity = alert_severity(r["score"], r["threshold"])
        ep = self._episode
        if ep is None:
            version = r.get("model_version") or "unknown"
            self._episode = _Episode(
                kind="anomaly",
                start_seq=seq,
                dedupe_key=f"{DETECTOR_ID}:{version}:{seq}",
                type=r["type"],
                message=r["message"],
                severity=severity,
                score=r["score"],
                origin=origin,
                model_version=version,
            )
            await self._persist(self._episode, session_factory, reading_id)
            return
        ep.normal_streak = 0
        if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(ep.severity, 0):
            ep.severity, ep.score, ep.message = severity, r["score"], r["message"]
            if ep.persisted:
                await self._update_severity(ep, session_factory)

    async def _on_normal(self, session_factory, reading_id) -> None:
        ep = self._episode
        if ep is None:
            return
        ep.normal_streak += 1
        if ep.normal_streak >= self.close_after:
            logger.info("Anomaly episode %s closed", ep.dedupe_key)
            self._episode = None

    async def _open_outage(self, seq, origin, session_factory, reading_id) -> None:
        if self._outage is not None:
            return
        self._outage = _Episode(
            kind="outage",
            start_seq=seq,
            dedupe_key=f"{DETECTOR_ID}:unavailable:{seq}",
            type="detector_unavailable",
            message="Anomaly detector unavailable - anomalies cannot be detected",
            severity="WARNING",
            score=0.0,
            origin=origin,
            model_version=None,
        )
        await self._persist(self._outage, session_factory, reading_id)

    async def _close_outage(self) -> None:
        if self._outage is not None:
            logger.info("Detector outage %s ended", self._outage.dedupe_key)
            self._outage = None

    # -- persistence + webhook -------------------------------------------------------------
    async def _persist(self, ep: _Episode, session_factory, reading_id) -> None:
        try:
            async with session_factory() as session:
                alert = await data_repository.save_alert(
                    session,
                    ep.score,
                    True,
                    ep.type,
                    ep.message,
                    ep.severity,
                    dedupe_key=ep.dedupe_key,
                    model_version=ep.model_version,
                    origin=ep.origin,
                    sensor_reading_id=reading_id,
                )
                await session.commit()
                ep.alert_id = getattr(alert, "id", None)
        except Exception:
            logger.exception("Could not persist alert %s -- will retry next tick", ep.dedupe_key)
            return
        ep.persisted = True
        ANOMALY_ALERTS_CREATED.labels(type=ep.type).inc()
        if webhook_service.webhook_allowed_for_origin(ep.origin):
            payload = {
                "score": ep.score,
                "type": ep.type,
                "message": ep.message,
                "severity": ep.severity,
                "origin": ep.origin,
                "dedupe_key": ep.dedupe_key,
                "model_version": ep.model_version,
            }
            task = asyncio.ensure_future(webhook_service.dispatch_alert(payload))
            self.pending.add(task)
            task.add_done_callback(self.pending.discard)

    async def _update_severity(self, ep: _Episode, session_factory) -> None:
        try:
            async with session_factory() as session:
                await data_repository.update_alert_severity(session, ep.dedupe_key, ep.severity, ep.score, ep.message)
                await session.commit()
        except Exception:
            logger.exception("Could not escalate alert %s", ep.dedupe_key)

    # -- status object ---------------------------------------------------------------------
    def _remember(self, status: dict[str, Any]) -> dict[str, Any]:
        self._latest = status
        return dict(status)

    def _status(
        self,
        status,
        message,
        *,
        filled,
        seq=None,
        origin=None,
        score=None,
        threshold=None,
        type_=None,
        explanation=None,
        model_version=None,
    ) -> dict[str, Any]:
        ep = self._episode
        return {
            "status": status,
            "message": message,
            "score": score,
            "threshold": threshold,
            "type": type_,
            "explanation": explanation,
            "window_size": telemetry_window.WINDOW_SIZE,
            "window_filled": filled,
            "seq": seq,
            "origin": origin,
            "detector_id": DETECTOR_ID,
            "model_version": model_version,
            "trained_on": TRAINED_ON,
            "episode": {
                "open": ep is not None,
                "dedupe_key": ep.dedupe_key if ep else None,
                "alert_id": ep.alert_id if ep else None,
                "start_seq": ep.start_seq if ep else None,
                "severity": ep.severity if ep else None,
            },
            "scored_at": _iso_now(),
        }


_pipeline: AnomalyPipeline = AnomalyPipeline()


def get_pipeline() -> AnomalyPipeline:
    return _pipeline
