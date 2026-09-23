# syntax=docker/dockerfile:1

# ---- Builder stage: compile/install dependencies, discarded afterward ----
FROM python:3.9-slim AS builder
# Matches runtime.txt (Railway's pinned version) exactly, so container
# behaviour matches the existing deployment rather than introducing a
# second, silently different Python version.

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ---- Runtime stage: slim image, no build toolchain ----
FROM python:3.9-slim AS runtime

# libpq5 (runtime lib, not -dev) for asyncpg; curl for the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user -- running as root inside the container is an unnecessary
# privilege-escalation surface with no offsetting benefit here.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# .dockerignore excludes realData/ (~3GB, no reason to ship inside an
# image), the local venv, tests, docs, and the two abandoned frontends.
COPY --chown=appuser:appuser . .

USER appuser
EXPOSE 8000

# Hits the unauthenticated liveness endpoint -- NOT /api/health, which
# requires a JWT this healthcheck has no way to obtain (see
# api/routes/health_routes.py).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]