"""Carry a request id into work that outlives the request (Task 7).

The request id lives in ``api.middleware.request_id.request_id_var`` (set by RequestIDMiddleware for HTTP and WebSocket
scopes). An RQ job runs in another process, so the id travels with the job as ``job.meta["request_id"]`` and the job
function is wrapped with ``with_request_id`` to restore it. The RQ worker must not need FastAPI (see src/task_jobs.py), so
nothing here imports ``api`` at import time; if the context variable cannot be imported the id still appears in the
two lines this module logs.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

META_KEY = "request_id"
_VALID = re.compile(r"[A-Za-z0-9._-]{6,64}")  # same rule as api.middleware.request_id


def _var() -> Any | None:
    try:
        from api.middleware.request_id import request_id_var

        return request_id_var
    except Exception:  # pragma: no cover - worker image without the api package
        return None


def current_request_id() -> str | None:
    """The id of the request being served, or None outside a request (the variable's default is ``-``)."""
    var = _var()
    value = var.get() if var is not None else None
    return value if isinstance(value, str) and _VALID.fullmatch(value) else None


def job_meta() -> dict[str, str]:
    """``meta`` for ``Queue.enqueue``: the current request id, or nothing."""
    rid = current_request_id()
    return {META_KEY: rid} if rid else {}


def _current_job() -> Any | None:
    try:
        from rq import get_current_job

        return get_current_job()
    except Exception:
        return None


def request_id_of(job: Any | None) -> str | None:
    meta = getattr(job, "meta", None)
    rid = meta.get(META_KEY) if isinstance(meta, dict) else None
    return rid if isinstance(rid, str) and _VALID.fullmatch(rid) else None


def with_request_id(func: Callable[..., T]) -> Callable[..., T]:
    """Run ``func`` with the enqueuing request's id restored, and log its start/end with that id."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        rid = request_id_of(_current_job())
        var = _var()
        token = var.set(rid) if (var is not None and rid) else None
        logger.info("job %s started request_id=%s", func.__name__, rid or "-")
        try:
            result = func(*args, **kwargs)
        except Exception:
            logger.error("job %s failed request_id=%s", func.__name__, rid or "-")
            raise
        else:
            logger.info("job %s finished request_id=%s", func.__name__, rid or "-")
            return result
        finally:
            if token is not None and var is not None:
                var.reset(token)

    return wrapper
