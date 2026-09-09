"""
FastAPI application exposing Digital Twin simulation, optimization, and anomaly detection.

Endpoints:
- GET /api/state - Get current state
- GET /api/simulate/{hours} - Run simulation
- POST /api/optimize - RL optimization
- GET /api/anomaly_score - Anomaly detection
- WebSocket /ws/live - Live state updates
- GET /api/health - Health check
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import decode_token, get_current_user, require_operator, router as auth_router
from database import get_db, get_session, init_db
from models.db_models import Alert, OptimizationResult, SensorReading, SimulationRun, User
from src.anomaly_detector import AnomalyDetector
from src.digital_twin import CoolingMode, DigitalTwin
from src.optimizer import JointOptimizer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup (use Alembic in production)."""
    await init_db()
    yield


app = FastAPI(
    title="Digital Twin API",
    description="Data centre digital twin simulation and optimization API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth_router)

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
_twin: DigitalTwin | None = None
_optimizer: JointOptimizer | None = None
_anomaly_detector: AnomalyDetector | None = None


def get_twin() -> DigitalTwin:
    """Get or create DigitalTwin instance."""
    global _twin
    if _twin is None:
        _twin = DigitalTwin()
    return _twin


def get_optimizer() -> JointOptimizer:
    """Get or create JointOptimizer instance."""
    global _optimizer
    if _optimizer is None:
        _optimizer = JointOptimizer()
    return _optimizer


def get_anomaly_detector() -> AnomalyDetector | None:
    """Get AnomalyDetector if available."""
    global _anomaly_detector
    if _anomaly_detector is None:
        try:
            from pathlib import Path
            detector_path = Path("models/anomaly")
            if detector_path.exists():
                _anomaly_detector = AnomalyDetector.load(detector_path)
        except Exception as e:
            logger.warning("Anomaly detector not available: %s", e)
    return _anomaly_detector


# =============================================================================
# Pydantic Models
# =============================================================================


class OptimizeRequest(BaseModel):
    """Request body for optimization endpoint."""

    alpha: float = Field(0.5, ge=0, le=1, description="WUE weight")
    beta: float = Field(0.3, ge=0, le=1, description="(PUE-1) weight")
    gamma: float = Field(0.2, ge=0, le=1, description="Cooling power weight")
    water_stress: float = Field(0.0, ge=0, le=1, description="Water stress level")
    hours: int = Field(24, ge=1, le=168, description="Simulation hours")


class AnomalyScoreResponse(BaseModel):
    """Response for anomaly detection."""

    score: float = Field(description="Reconstruction error score")
    alert: bool = Field(description="True if anomaly detected")
    type: str = Field(description="Anomaly type or 'normal'")
    message: str = Field(description="Human-readable message")


# =============================================================================
# Endpoints
# =============================================================================


@app.get("/api/health")
async def health_check(
    _user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """Health check endpoint. Requires valid JWT."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/state")
async def get_state(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    utilisation: float = Query(0.5, ge=0, le=1, description="Server utilisation [0-1]"),
    outside_temp: float = Query(25.0, ge=-10, le=50, description="Outside temp (°C)"),
    water_stress: float = Query(0.0, ge=0, le=1, description="Water stress [0-1]"),
    mode: str = Query("auto", description="Cooling mode: auto, free_air, closed_loop, evaporative, hybrid"),
) -> dict[str, Any]:
    """
    Get current state after one step.

    If mode='auto', uses rule-based selection. Otherwise uses specified mode.
    """
    twin = get_twin()
    action: dict[str, Any] = {
        "utilisation": utilisation,
        "outside_temp_C": outside_temp,
    }
    if mode == "auto":
        cooling_mode = twin.select_cooling_mode(outside_temp, water_stress)
    else:
        try:
            cooling_mode = CoolingMode(mode)
        except ValueError:
            cooling_mode = CoolingMode.CLOSED_LOOP
    action["cooling_mode"] = cooling_mode
    state = twin.step(action)
    result = state.to_dict()
    session.add(SensorReading.from_state_dict(result, "api"))
    await session.flush()
    if "timestamp" in result and isinstance(result["timestamp"], datetime):
        result["timestamp"] = result["timestamp"].isoformat()
    return result


@app.get("/api/simulate/{hours}")
async def simulate(
    hours: int,
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    utilisation: float = Query(0.7, ge=0, le=1),
    stress: float = Query(0.3, ge=0, le=1, description="Water stress"),
) -> list[dict[str, Any]]:
    """
    Simulate for N hours, returning hourly snapshots.

    Args:
        hours: Number of hours to simulate (1-168).
        utilisation: Server utilisation [0-1].
        stress: Water stress level [0-1].
    """
    if hours < 1 or hours > 168:
        raise ValueError("hours must be between 1 and 168")
    twin = get_twin()
    steps_per_hour = 12  # 5-min intervals
    n_steps = hours * steps_per_hour
    util_profile = [utilisation] * n_steps
    temp_profile = [25.0] * n_steps  # Constant temp for simplicity
    df = twin.run_scenario(
        n_steps=n_steps,
        util_profile=util_profile,
        temp_profile=temp_profile,
        use_auto_cooling=True,
        water_stress=stress,
    )
    hourly = df.iloc[::steps_per_hour].to_dict("records")
    run = SimulationRun(hours=hours, utilisation=utilisation, stress=stress, result_snapshot=hourly)
    session.add(run)
    await session.flush()
    for record in hourly:
        session.add(
            SensorReading.from_state_dict(record, "simulation", simulation_run_id=run.id)
        )
    for record in hourly:
        if "timestamp" in record and isinstance(record["timestamp"], datetime):
            record["timestamp"] = record["timestamp"].isoformat()
    return hourly


@app.post("/api/optimize")
async def optimize(
    request: OptimizeRequest,
    _user: Annotated[User, Depends(require_operator)],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Run RL optimization and return results.

    Uses JointOptimizer with specified weights to minimize J = α·W + β·E + γ·C.
    """
    optimizer = get_optimizer()
    optimizer._alpha = request.alpha
    optimizer._beta = request.beta
    optimizer._gamma = request.gamma
    if optimizer._model is None:
        logger.info("Training optimizer (quick training for demo)...")
        optimizer.train(total_timesteps=5000, n_envs=2, water_stress=request.water_stress)
    from src.optimizer import DataCentreEnv
    steps_per_hour = 12
    n_steps = request.hours * steps_per_hour
    env = DataCentreEnv(
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        water_stress=request.water_stress,
        max_steps=n_steps,
    )
    obs, _ = env.reset()
    rows = []
    for _ in range(n_steps):
        if optimizer._model is None:
            action = env.action_space.sample()
        else:
            action, _ = optimizer._model.predict(obs, deterministic=True)
        next_obs, reward, term, trunc, info = env.step(action)
        state = info["state"]
        chilled, mode = env._action_to_control(action)
        rows.append({
            **state,
            "chilled_water_temp_C": chilled,
            "cooling_mode": mode,
            "reward": reward,
        })
        obs = next_obs
        if term or trunc:
            break
    env.close()
    df = pd.DataFrame(rows)
    results = df.to_dict("records")
    summary = {
        "mean_pue": float(df["pue"].mean()),
        "mean_wue": float(df["wue"].mean()),
        "mean_cooling_power_kw": float(df["cooling_power"].mean()),
        "total_water_consumed_L": float(df["water_consumed"].sum()),
        "total_reward": float(df["reward"].sum()),
        "safety_violations": int((df["outlet_temp"] > 45).sum()),
    }
    for record in results:
        if "timestamp" in record and isinstance(record.get("timestamp"), datetime):
            record["timestamp"] = record["timestamp"].isoformat()
    opt = OptimizationResult(
        alpha=request.alpha,
        beta=request.beta,
        gamma=request.gamma,
        water_stress=request.water_stress,
        hours=request.hours,
        mean_pue=summary["mean_pue"],
        mean_wue=summary["mean_wue"],
        mean_cooling_power_kw=summary["mean_cooling_power_kw"],
        total_water_consumed_L=summary["total_water_consumed_L"],
        total_reward=summary["total_reward"],
        safety_violations=summary["safety_violations"],
        results_json=results,
    )
    session.add(opt)
    await session.flush()
    return {"results": results, "summary": summary}


@app.get("/api/anomaly_score")
async def anomaly_score(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    recent_data: str = Query(..., description="JSON array of recent sensor readings"),
) -> AnomalyScoreResponse:
    """
    Compute anomaly score from recent sensor data.

    Args:
        recent_data: JSON string of array with 12×5 features:
                     [water_flow_lpm, water_pressure_bar, server_outlet_temp_C,
                      it_power_kw, humidity_pct] × 12 timesteps
    """
    detector = get_anomaly_detector()
    if detector is None:
        return AnomalyScoreResponse(
            score=0.0,
            alert=False,
            type="normal",
            message="Anomaly detector not available",
        )
    try:
        data = json.loads(recent_data)
        arr = np.array(data, dtype=np.float32)
        if arr.shape != (12, 5):
            raise ValueError(f"Expected shape (12, 5), got {arr.shape}")
        errors, alerts = detector.detect(arr.reshape(1, 12, 5))
        score = float(errors[0])
        alert = bool(alerts[0])
        if alert:
            if arr[-1, 1] < 2.0:
                anomaly_type = "water_leak"
                message = "Water pressure anomaly detected - possible leak"
            elif arr[-1, 2] > 45:
                anomaly_type = "thermal_spike"
                message = "Outlet temperature spike detected"
            else:
                anomaly_type = "unknown"
                message = "Anomaly detected"
        else:
            anomaly_type = "normal"
            message = "No anomalies detected"
        session.add(
            Alert(score=score, alert=alert, type=anomaly_type, message=message)
        )
        await session.flush()
        return AnomalyScoreResponse(
            score=score,
            alert=alert,
            type=anomaly_type,
            message=message,
        )
    except Exception as e:
        logger.exception("Anomaly detection error: %s", e)
        session.add(
            Alert(score=0.0, alert=False, type="error", message=str(e))
        )
        await session.flush()
        return AnomalyScoreResponse(
            score=0.0,
            alert=False,
            type="error",
            message=f"Error: {str(e)}",
        )


@app.get("/api/alerts")
async def list_alerts(
    _user: Annotated[User, Depends(get_current_user)],
    session: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200, description="Max number of alerts to return"),
) -> list[dict[str, Any]]:
    """
    List recent alerts from PostgreSQL (dashboard notifications).
    Ordered by created_at descending.
    """
    result = await session.execute(
        select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    )
    alerts = result.scalars().all()
    return [
        {
            "id": a.id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "type": a.type,
            "message": a.message,
            "severity": a.severity or "INFO",
            "score": a.score,
            "alert": a.alert,
        }
        for a in alerts
    ]


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket, token: str = Query(..., alias="token")):
    """
    WebSocket endpoint sending live state updates every 3 seconds.

    Requires JWT in query: /ws/live?token=<access_token>.
    Sends JSON with current state from DigitalTwin. Each state is stored in DB.
    """
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4001)
        return
    await websocket.accept()
    twin = get_twin()
    try:
        while True:
            import random
            hour = datetime.now().hour + datetime.now().minute / 60
            utilisation = 0.4 + 0.5 * np.sin((hour - 6) * np.pi / 12)
            utilisation = max(0, min(1, utilisation))
            outside_temp = 22 + 5 * np.sin(2 * np.pi * (hour - 14) / 24) + random.uniform(-1, 1)
            water_stress = random.uniform(0, 0.5)
            action = {
                "utilisation": utilisation,
                "outside_temp_C": outside_temp,
                "cooling_mode": twin.select_cooling_mode(outside_temp, water_stress),
            }
            state = twin.step(action)
            state_dict = state.to_dict()
            async with get_session() as session:
                session.add(SensorReading.from_state_dict(state_dict, "ws"))
                await session.commit()
            if "timestamp" in state_dict and isinstance(state_dict["timestamp"], datetime):
                state_dict["timestamp"] = state_dict["timestamp"].isoformat()
            await websocket.send_json(state_dict)
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
        await websocket.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
