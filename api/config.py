"""
Application configuration.
"""

from __future__ import annotations

import os


def _parse_origins(raw: str | None) -> list[str]:
    if not raw:
        if os.getenv("ENVIRONMENT", "development").strip().lower() == "production":
            # Same reasoning as JWT_SECRET_KEY in api/auth.py: no silent
            # hardcoded fallback in production. A frontend origin baked into
            # this codebase is either stale (this deployment serves a
            # different frontend, and requests from it will be silently
            # rejected by the browser with a confusing CORS error) or, worse,
            # masks someone forgetting to set CORS_ALLOWED_ORIGINS at all.
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS is not set and ENVIRONMENT=production. Set it "
                "explicitly to a comma-separated list of allowed frontend origins, e.g.: "
                "CORS_ALLOWED_ORIGINS=https://your-frontend.example.com"
            )
        # Fallback to the one known deployed frontend rather than "*" --
        # still a single hardcoded default, but a scoped one, not a
        # wildcard. Non-production only (see above); production always
        # requires CORS_ALLOWED_ORIGINS set explicitly.
        return ["https://digital-twin-dc-conservation.lovable.app"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class Settings:
    CORS_ALLOW_ORIGINS: list[str] = _parse_origins(os.getenv("CORS_ALLOWED_ORIGINS"))
    CORS_ALLOW_CREDENTIALS: bool = True
    APP_TITLE: str = "Digital Twin API"
    APP_DESCRIPTION: str = "Data centre digital twin simulation and optimization API"
    APP_VERSION: str = "1.0.0"


settings = Settings()