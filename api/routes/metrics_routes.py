"""
GET /metrics -- Prometheus scrape endpoint.

Deliberately unauthenticated, matching standard Prometheus convention
(metrics endpoints are protected at the network/ingress level in real
deployments, not behind application auth) -- same reasoning as /healthz
in Phase 14. Known simplification at this project's scale: there is no
separate internal network to restrict this to here; a production
deployment with a real ingress/VPC would scope this differently.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from api.middleware.metrics import render_metrics

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)