# syntax=docker/dockerfile:1

# Base image: Python 3.12.10 (matches runtime.txt, so container behaviour matches the Railway/Nixpacks
# deployment). T11 requires it pinned BY DIGEST. The digest could not be resolved when this file was written
# (no registry access), so the default below is still the tag; the CI `docker` job fails until it reads
#   ARG PYTHON_IMAGE=python:3.12.10-slim@sha256:<64 hex>
# Get the value from the `bootstrap` job summary, or: docker buildx imagetools inspect python:3.12.10-slim
ARG PYTHON_IMAGE=python:3.12.10-slim

# ---- Builder stage: compile/install dependencies, discarded afterward ----
FROM ${PYTHON_IMAGE} AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.lock .
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
# T29: the API image has NO PyTorch and NO stable-baselines3 -- it serves a promoted policy through the NumPy runtime
# (src/rl/numpy_policy.py). requirements.txt no longer lists them, so a lock regenerated from it (the CI `bootstrap` job)
# does not contain them. A lock generated BEFORE the split still does; this step removes those requirement blocks (and
# the packages only they need) so the image is correct either way, and the check after the install fails the build if
# either package is importable. It is a no-op on a regenerated lock.
RUN python - <<'PY'
import re
import pathlib

drop = {"torch", "stable-baselines3", "filelock", "fsspec", "jinja2", "mpmath", "networkx", "sympy"}
lock = pathlib.Path("requirements.lock")
blocks, current = [], []
for line in lock.read_text(encoding="utf-8").splitlines(keepends=True):
    if line.strip() and not line[0].isspace() and not line.startswith("#"):
        blocks.append(current)
        current = []
    current.append(line)
blocks.append(current)
kept = []
for block in blocks:
    head = block[0] if block else ""
    match = re.match(r"([A-Za-z0-9_.\-]+)==", head)
    if match and re.sub(r"[-_.]+", "-", match.group(1)).lower() in drop:
        continue
    kept.extend(block)
lock.write_text("".join(kept), encoding="utf-8")
PY
# requirements.lock is hash-pinned (pip-compile --generate-hashes); --require-hashes rejects anything else.
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
RUN python -c "import importlib.util as u, sys; bad = [m for m in ('torch', 'stable_baselines3') if u.find_spec(m)]; sys.exit('training packages in the API image: ' + ', '.join(bad)) if bad else print('API image has no torch / stable-baselines3')"


# ---- Runtime stage: slim image, no build toolchain ----
FROM ${PYTHON_IMAGE} AS runtime

# Commit the image was built from (read by src/model_registry.py). Pass --build-arg GIT_SHA=$(git rev-parse HEAD).
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

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
    PORT=8000 \
    ENVIRONMENT=production

# .dockerignore excludes realData/ (~3GB, no reason to ship inside an
# image), the local venv, tests, docs, and the two abandoned frontends.
COPY --chown=appuser:appuser . .

# Training outputs (SB3 zips, train_config.json) are never loaded by the API (T29); keep them out of the image.
RUN rm -rf /app/artifacts_training /app/requirements-train.txt && mkdir -p /app/logs && chown appuser:appuser /app/logs
USER appuser
EXPOSE 8000

# Hits the unauthenticated liveness endpoint -- NOT /api/health, which
# requires a JWT this healthcheck has no way to obtain (see
# api/routes/health_routes.py).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/healthz || exit 1

# Startup validation FIRST (api/startup_checks.py): an unsafe production configuration exits non-zero here,
# before migrations touch the database. Then the release step + server. `alembic upgrade head` owns the schema
# (create_all is dev-only, see database.init_db); set RUN_MIGRATIONS=0 to skip it, e.g. when migrations run as a
# separate job. `sh -c` so $PORT (Railway/Render/Heroku) is honoured; `exec` keeps uvicorn as PID 1 so it
# receives SIGTERM directly.
CMD ["sh", "-c", "python -m api.startup_checks && if [ \"${RUN_MIGRATIONS:-1}\" = \"1\" ]; then alembic upgrade head; fi && exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
