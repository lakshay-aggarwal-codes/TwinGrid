"""Plugin: login lockout/backoff for ``POST /auth/login`` (Task 6). Policy and env vars: src/login_lockout.py.

Pure ASGI, wrapped around the finished middleware stack (so it sees the real status code the login handler
produced, and a locked-out request never reaches the handler or the password hash). It:

* buffers at most 4 KiB of the request body to read ``username`` and replays it untouched; a larger, non-JSON or
  username-less body is passed through unguarded (the route's own validation and body limit handle it);
* answers 429 (problem+json, ``Retry-After``) while the (client IP, username) pair is locked;
* counts a 401 from the handler as a failure and a 200 as a success.

By default it follows the shared ``limiter`` switch (the existing test/rollback switch for rate limiting);
``LOGIN_LOCKOUT_ENABLED=true|false`` overrides that (src/login_lockout.py).
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.errors import problem_response
from api.rate_limit import client_ip, limiter
from src import login_lockout as guard

LOGIN_PATH = "/auth/login"
_BODY_PEEK_LIMIT = 4096


def _client_ip(scope: Scope) -> str:
    return client_ip(Request(scope))


class LoginLockoutMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != LOGIN_PATH
            or not guard.active(limiter.enabled)
        ):
            await self.app(scope, receive, send)
            return

        buffered: list[Message] = []
        body = b""
        complete = False
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                break  # disconnect before the body finished
            body += message.get("body", b"")
            if len(body) > _BODY_PEEK_LIMIT:
                break
            if not message.get("more_body", False):
                complete = True
                break

        replay = iter(buffered)

        async def replaying_receive() -> Message:
            try:
                return next(replay)
            except StopIteration:
                return await receive()

        username = None
        if complete:
            try:
                parsed = json.loads(body)
                candidate = parsed.get("username") if isinstance(parsed, dict) else None
                username = candidate if isinstance(candidate, str) and candidate else None
            except ValueError:
                username = None
        if username is None:
            await self.app(scope, replaying_receive, send)
            return

        key = guard.make_key(_client_ip(scope), username)
        wait = guard.retry_after(key)
        if wait is not None:
            response = problem_response(
                scope,
                429,
                f"Too many failed sign-in attempts. Retry in {wait} seconds.",
                code="login_locked",
                headers={"Retry-After": str(wait)},
            )
            await response(scope, replaying_receive, send)
            return

        async def observing_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status = message["status"]
                if status == 401:
                    guard.record_failure(key)
                elif status == 200:
                    guard.record_success(key)
            await send(message)

        await self.app(scope, replaying_receive, observing_send)


def setup(app: FastAPI) -> None:
    previous = app.build_middleware_stack

    def build() -> ASGIApp:
        return LoginLockoutMiddleware(previous())

    app.build_middleware_stack = build  # type: ignore[method-assign]
