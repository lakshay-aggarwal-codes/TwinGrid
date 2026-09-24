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
- GET /api/whatif
- POST /api/optimize
- GET /api/anomaly_score
- GET /api/alerts
- GET /api/equipment/health
- WebSocket /ws/live
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.auth import router as auth_router
from api.config import settings
from api.logging_config import setup_api_logging
from api.middleware.metrics import MetricsMiddleware
from api.middleware.request_id import RequestIDMiddleware
from api.rate_limit import limiter
from api.routes import (
    anomaly_routes,
    digital_twin_routes,
    equipment_health_routes,
    health_routes,
    metrics_routes,
    optimization_routes,
    websocket_routes,
)
from api.services import optimization_service
from api.services.live_broadcast_service import run_broadcast_loop
from database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables, set up structured logging, and start the shared
    live-broadcast loop on startup; cancel background tasks cleanly on shutdown.

    The optimizer warm-up runs as a background task (loading PPO imports torch,
    which takes seconds) so it never delays the server becoming healthy.
    """
    setup_api_logging()
    await init_db()
    background_tasks = [
        asyncio.create_task(run_broadcast_loop()),
        asyncio.create_task(optimization_service.warm_up()),
    ]
    yield
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)


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

# CORS origins come from CORS_ALLOWED_ORIGINS (comma-separated) -- see api/config.py.
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

    # Import string (not the app object) -- uvicorn requires it for reload=True.
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENVIRONMENT", "development") != "production",
    )
