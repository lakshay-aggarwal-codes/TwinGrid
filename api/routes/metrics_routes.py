"""
GET /metrics -- Prometheus scrape endpoint, protected by a bearer token (T13).

* ``ENVIRONMENT=production`` (or any unrecognised value): ``Authorization: Bearer <METRICS_TOKEN>`` is mandatory.
  A missing or wrong token -> 401. If no token is configured at all the endpoint stays closed (401); startup
  validation (api/startup_checks.py) already refuses to boot in that state.
* ``development`` / ``test``: open when ``METRICS_TOKEN`` is unset (unchanged behaviour); enforced when it is set.

``METRICS_TOKEN`` may be supplied as ``METRICS_TOKEN_FILE``. It is read on every request so rotation needs no restart.
Prometheus: ``authorization: {type: Bearer, credentials_file: ...}`` in the scrape config.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api.middleware.metrics import render_metrics
from api.secrets import read_secret
from api.startup_checks import requires_strict_checks

router = APIRouter(tags=["observability"])


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Metrics token required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_metrics_token(request: Request) -> None:
    try:
        expected = (read_secret("METRICS_TOKEN") or "").strip()
    except RuntimeError:
        expected = ""
        if not requires_strict_checks():
            raise  # a configured-but-unreadable token file is a deployment error outside production too
    if not expected:
        if requires_strict_checks():
            raise _unauthorized()  # production without a configured token: closed
        return  # development/test with no token configured: open, as before
    scheme, _, provided = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not provided.strip():
        raise _unauthorized()
    if not hmac.compare_digest(provided.strip().encode("utf-8"), expected.encode("utf-8")):
        raise _unauthorized()


@router.get("/metrics", dependencies=[Depends(require_metrics_token)])
async def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
