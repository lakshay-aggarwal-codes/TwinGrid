"""Validation for webhook subscriber URLs (SSRF guard).

A webhook URL is a server-side request target chosen by a caller, so it must
never be allowed to point at the server's own network: loopback, private
ranges, link-local (cloud metadata at 169.254.169.254), etc.

Rules:
* https only (set WEBHOOK_ALLOW_HTTP=1 to also allow http, e.g. local dev).
* A hostname is required; embedded credentials are rejected.
* Every address the host resolves to must be globally routable. If ANY
  resolved address is private/loopback/link-local/reserved, the URL is rejected.

Known limitation: the check resolves DNS at validation time and again at
dispatch time, but the HTTP client resolves once more when it connects, so a
DNS-rebinding attacker with a very short TTL is not fully stopped. Closing that
gap needs connecting to the pre-resolved IP (a custom transport adapter).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048


class WebhookURLError(ValueError):
    """The URL is malformed or points somewhere webhooks may not go."""


def _allow_http() -> bool:
    return os.getenv("WEBHOOK_ALLOW_HTTP", "0").strip().lower() in ("1", "true", "yes")


def _resolve_host(host: str, port: int) -> list[str]:
    """Resolve ``host`` to IP strings. Separate function so tests can stub DNS."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebhookURLError(f"Cannot resolve host {host!r}") from exc
    return [info[4][0] for info in infos]


def _check_ip(raw: str) -> None:
    ip = ipaddress.ip_address(raw.split("%", 1)[0])  # drop IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        raise WebhookURLError("Webhook target resolves to a non-public address")


def validate_webhook_url(url: str) -> str:
    """Return ``url`` if it is safe to POST to, else raise WebhookURLError."""
    if not url or len(url) > MAX_URL_LENGTH:
        raise WebhookURLError("URL is empty or too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise WebhookURLError("Malformed URL") from exc

    allowed = {"https", "http"} if _allow_http() else {"https"}
    if parts.scheme not in allowed:
        raise WebhookURLError(f"Scheme must be one of: {', '.join(sorted(allowed))}")
    host = parts.hostname
    if not host:
        raise WebhookURLError("URL has no host")
    if parts.username or parts.password:
        raise WebhookURLError("Credentials in the URL are not allowed")
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise WebhookURLError("Webhook target resolves to a non-public address")

    try:
        addresses = [str(ipaddress.ip_address(host))]  # IP literal: no DNS needed
    except ValueError:
        addresses = _resolve_host(host, port or (443 if parts.scheme == "https" else 80))
    if not addresses:
        raise WebhookURLError(f"Cannot resolve host {host!r}")
    for address in addresses:
        _check_ip(address)
    return url
