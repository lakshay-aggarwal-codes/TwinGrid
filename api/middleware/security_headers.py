"""Security response headers for the API (Task 6).

Set on every HTTP response, including 4xx/5xx produced by inner middleware (the plugin ``setup`` wraps the finished
middleware stack, so this is the outermost layer):

* ``X-Content-Type-Options: nosniff``
* ``X-Frame-Options: DENY`` and ``Content-Security-Policy: frame-ancestors 'none'`` -- the API is never framed.
  Only ``frame-ancestors`` is sent as CSP: a full ``default-src`` policy would break the Swagger UI at ``/docs``.
* ``Referrer-Policy: no-referrer``
* ``Permissions-Policy`` denying camera, microphone, geolocation, payment, USB
* ``Strict-Transport-Security`` ONLY when the request arrived over HTTPS (the ASGI scheme, or -- with
  ``TRUST_PROXY_HEADERS`` on -- the nearest trusted proxy's ``X-Forwarded-Proto``). Over plain HTTP it is omitted:
  browsers ignore it there and a dev server must not pin itself to HTTPS.

A header a route already set is left alone. WebSocket scopes pass through untouched.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api import config

HSTS_VALUE = "max-age=31536000; includeSubDomains"

STATIC_HEADERS: tuple[tuple[str, str], ...] = (
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("content-security-policy", "frame-ancestors 'none'"),
    ("referrer-policy", "no-referrer"),
    ("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
)


def request_is_https(scope: Scope) -> bool:
    if scope.get("scheme") == "https":
        return True
    if not config.trust_proxy_headers():
        return False
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-proto":
            parts = [p.strip().lower() for p in value.decode("latin-1").split(",") if p.strip()]
            hops = config.trusted_proxy_hops()
            return len(parts) >= hops and parts[-hops] == "https"
    return False


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        https = request_is_https(scope)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra = list(STATIC_HEADERS)
                if https:
                    extra.append(("strict-transport-security", HSTS_VALUE))
                for name, value in extra:
                    if name.encode("latin-1") not in present:
                        headers.append((name.encode("latin-1"), value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
