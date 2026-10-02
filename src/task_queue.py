"""Thin wrapper around RQ (Redis Queue) for CPU-bound work that shouldn't
run inline in a request, and should survive a process restart or be
picked up by a different instance -- unlike the worker-thread pattern
(ADR 002), which is in-process only.

This is ADDITIVE, not a replacement: `/api/optimize` keeps working exactly
as before (synchronous, worker-thread fallback training). The new
`/api/optimize/async` endpoint is for callers who'd rather get a job_id
back immediately and poll, instead of holding an HTTP connection open for
however long fallback training takes. Nothing switches over to this
automatically -- see ADR 002's expiry condition, which this satisfies.

Requires a Redis instance (REDIS_URL env var, default localhost:6379) and
an `rq worker` process actually running (see docker-compose.yml's new
`worker` service) -- jobs just sit queued forever with no worker running.
Not verified end-to-end in the assistant's sandbox (no Redis, no network
to install redis/rq here); the RQ API used here is small and stable, but
run it locally before trusting it.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from redis import Redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "twingrid"
JOB_TIMEOUT_SECONDS = 600  # fallback training is capped at FALLBACK_TRAIN_TIMESTEPS, should finish well under this


class JobNotFoundError(LookupError):
    """The job id was never enqueued, or has expired from Redis."""


_redis: Redis | None = None
_queue: Queue | None = None

# Absolute filesystem paths (Windows drive paths, or POSIX paths with 2+ segments) in anything
# returned to an API caller are replaced; tracebacks and results can contain them.
_PATH_RE = re.compile(r"(?:(?<![\w])[A-Za-z]:[\\/][^\s'\"]+|(?<![\w.:/])/(?:[\w.@+-]+/)+[\w.@+-]*)")
_ERROR_MAX_CHARS = 300


def scrub_paths(text: str) -> str:
    return _PATH_RE.sub("<path>", text)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_paths(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _json_serializer() -> Any | None:
    """RQ's JSON serializer, so a compromised Redis cannot feed the worker/API pickles.

    NOT VERIFIED against the installed RQ in the assistant's sandbox (rq is not
    installed there). Returns None -- the pickle default -- if this RQ has no
    ``rq.serializers.JSONSerializer``; that is a documented residual risk. The
    worker must use the same serializer (docker-compose.yml passes ``--serializer``).
    """
    try:
        from rq.serializers import JSONSerializer
    except ImportError:
        logger.warning("rq.serializers.JSONSerializer unavailable; job payloads use pickle (residual risk)")
        return None
    return JSONSerializer


def _get_queue() -> Queue:
    global _redis, _queue
    if _queue is None:
        _redis = Redis.from_url(REDIS_URL)
        _queue = Queue(QUEUE_NAME, connection=_redis, serializer=_json_serializer())
    return _queue


def enqueue(func_path: str, *args: Any, **kwargs: Any) -> str:
    """Enqueue a job by import path (e.g. 'src.task_jobs.train_optimizer_job')
    -- RQ needs an importable reference, not a closure, since the worker
    process re-imports it. Returns the job id."""
    job = _get_queue().enqueue(func_path, *args, job_timeout=JOB_TIMEOUT_SECONDS, **kwargs)
    return job.id


def get_status(job_id: str) -> dict[str, Any]:
    """Job status + result (if finished) + error (if failed). Raises if
    job_id was never enqueued or has already expired (JobNotFoundError).
    Result/error text is scrubbed of absolute filesystem paths."""
    try:
        queue = _get_queue()
        job = Job.fetch(job_id, connection=queue.connection, serializer=queue.serializer)
    except NoSuchJobError as exc:
        raise JobNotFoundError(job_id) from exc
    result: dict[str, Any] = {"job_id": job_id, "status": job.get_status()}
    if job.is_finished:
        result["result"] = _scrub(job.result)
    elif job.is_failed:
        # Last traceback line only (the exception summary), with paths removed -- never the stack.
        lines = [ln for ln in str(job.exc_info or "").strip().splitlines() if ln.strip()]
        summary = scrub_paths(lines[-1].strip()) if lines else "Job failed"
        result["error"] = summary[:_ERROR_MAX_CHARS]
    return result
