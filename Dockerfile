# syntax=docker/dockerfile:1

# ---- Builder stage: compile/install dependencies, discarded afterward ----
FROM python:3.12-slim AS builder
# Matches runtime.txt (Python 3.12) so container behaviour matches the
# Railway/Nixpacks deployment rather than introducing a second, silently
# different Python version.

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*
    
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
# stable-baselines3 pulls in PyTorch; the default Linux wheel bundles CUDA
# (~2GB+). This API only does CPU inference, so prefer the CPU-only wheel.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt


# ---- Runtime stage: slim image, no build toolchain ----
FROM python:3.12-slim AS runtime

# libpq5 (runtime lib, not -dev) for asyncpg; curl for the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user -- running as root inside the container is an unnecessary
# privilege-escalation surface with no offsetting benefit here.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# .dockerignore excludes realData/ (~3GB, no reason to ship inside an
# image), the local venv, tests, docs, and the two abandoned frontends.
COPY --chown=appuser:appuser . .

RUN mkdir -p /app/logs && chown appuser:appuser /app/logs
USER appuser
EXPOSE 8000

# Hits the unauthenticated liveness endpoint -- NOT /api/health, which
# requires a JWT this healthcheck has no way to obtain (see
# api/routes/health_routes.py).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/healthz || exit 1

# Release step + server. `alembic upgrade head` owns the schema (create_all is
# dev-only, see database.init_db); set RUN_MIGRATIONS=0 to skip it, e.g. when
# migrations run as a separate job. `sh -c` so $PORT (Railway/Render/Heroku) is
# honoured; `exec` keeps uvicorn as PID 1 so it receives SIGTERM directly.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-1}\" = \"1\" ]; then alembic upgrade head; fi && exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]