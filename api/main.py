"""
FastAPI application exposing Digital Twin simulation, optimization, and
anomaly detection.

Thin composition root only -- business logic lives in api/services/,
persistence in api/repositories/, request/response shapes in
api/schemas/, and endpoints in api/routes/ (Phase 9 backend refactor).

Endpoints (unchanged from before the refactor):
- GET /api/health
- GET /api/state
- GET /api/simulate/{hours}
- POST /api/optimize
- GET /api/anomaly_score
- GET /api/alerts
- WebSocket /ws/live
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.config import settings
from api.routes import anomaly_routes, digital_twin_routes, equipment_health_routes, health_routes, optimization_routes, websocket_routes
from api.services.live_broadcast_service import run_broadcast_loop
from database import init_db

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from api.logging_config import setup_api_logging
from api.middleware.metrics import MetricsMiddleware
from api.middleware.request_id import RequestIDMiddleware
from api.routes import metrics_routes
from api.rate_limit import limiter

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables, set up structured logging, and start the shared
    live-broadcast loop on startup; cancel the loop cleanly on shutdown."""
    setup_api_logging()
    await init_db()
    broadcast_task = asyncio.create_task(run_broadcast_loop())
    yield
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass    

app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth_router)
app.include_router(health_routes.router)
app.include_router(digital_twin_routes.router)
app.include_router(optimization_routes.router)
app.include_router(anomaly_routes.router)
app.include_router(websocket_routes.router)
app.include_router(equipment_health_routes.router)
app.include_router(metrics_routes.router)

# NOTE: CORS setting is unchanged from before this refactor (still
# permissive) -- see api/config.py's TODO. Hardening this is Phase 12's
# job, not silently bundled into a structural refactor.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(MetricsMiddleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)

from api.routes import (
    anomaly_routes,
    digital_twin_routes,
    equipment_health_routes,
    health_routes,
    optimization_routes,
    websocket_routes,
)

