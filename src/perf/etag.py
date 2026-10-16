"""Weak ETags and ``If-None-Match`` -> 304 for a short list of read-only GET endpoints (pure ASGI, no dependencies).

The ETag is a hash of the response body, so it is correct for any endpoint; whether a client ever gets a 304 depends
on the body being stable between requests (``/api/scenarios`` is; a body that carries a fresh timestamp is not).
It is *weak* (``W/"..."``) because the gzip layer outside this one changes the bytes but not the representation.
The route (and its auth) always runs first: a 304 saves bandwidth, never authorisation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

DEFAULT_PATHS: tuple[str, ...] = (
    "/api/scenarios",
    "/api/state",
    "/api/whatif",
    "/api/benchmark",
    "/api/simulate/",  # trailing slash = prefix (the hours are a path parameter)
)
DEFAULT_MAX_BODY = 1 << 20  # larger bodies are streamed through untouched

_TAG = re.compile(r'(?:W/)?"[^"]*"')


def compute_etag(body: bytes) -> str:
    return 'W/"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def _opaque(tag: str) -> str:
    return tag[2:] if tag.startswith("W/") else tag


def if_none_match_matches(header: str | None, etag: str) -> bool:
    """RFC 9110 weak comparison; ``*`` matches anything."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    mine = _opaque(etag)
    return any(_opaque(t) == mine for t in _TAG.findall(header))


def path_selected(path: str, paths: Iterable[str]) -> bool:
    return any(path.startswith(p) if p.endswith("/") else path == p for p in paths)


class ETagMiddleware:
    def __init__(self, app, paths: Iterable[str] = DEFAULT_PATHS, max_body: int = DEFAULT_MAX_BODY) -> None:
        self.app = app
        self.paths = tuple(paths)
        self.max_body = max_body

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET" or not path_selected(scope["path"], self.paths):
            await self.app(scope, receive, send)
            return
        inm = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"if-none-match"), None)
        start: dict | None = None
        chunks: list[bytes] = []
        size = 0
        passthrough = False

        async def wrapped(message) -> None:
            nonlocal start, size, passthrough
            if passthrough:
                await send(message)
                return
            if message["type"] == "http.response.start":
                names = {k for k, _ in message.get("headers", [])}
                if message["status"] != 200 or b"etag" in names or b"content-encoding" in names:
                    passthrough = True
                    await send(message)
                    return
                start = message
                return
            if message["type"] != "http.response.body" or start is None:
                await send(message)
                return
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            more = bool(message.get("more_body", False))
            if size > self.max_body:  # too big to hash: send what we hold and stream the rest through
                passthrough = True
                await send(start)
                await send({"type": "http.response.body", "body": b"".join(chunks), "more_body": more})
                return
            if more:
                return
            body = b"".join(chunks)
            etag = compute_etag(body)
            headers = list(start.get("headers", []))
            if if_none_match_matches(inm, etag):
                keep = {b"cache-control", b"vary", b"date", b"expires"}
                kept = [(k, v) for k, v in headers if k in keep]
                kept = _with_vary(_with_cache_control(kept), b"Authorization")
                kept.append((b"etag", etag.encode()))
                await send({"type": "http.response.start", "status": 304, "headers": kept})
                await send({"type": "http.response.body", "body": b""})
                return
            headers = _with_vary(_with_cache_control(headers), b"Authorization")
            headers.append((b"etag", etag.encode()))
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, wrapped)


def _with_cache_control(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    if any(k == b"cache-control" for k, _ in headers):
        return headers
    return [*headers, (b"cache-control", b"private, no-cache")]


def _with_vary(headers: list[tuple[bytes, bytes]], token: bytes) -> list[tuple[bytes, bytes]]:
    out, found = [], False
    for k, v in headers:
        if k == b"vary":
            found = True
            if token.lower() not in v.lower():
                v = v + b", " + token
        out.append((k, v))
    return out if found else [*out, (b"vary", token)]
