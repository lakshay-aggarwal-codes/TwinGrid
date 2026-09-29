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

import os
from typing import Any

from redis import Redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "twingrid"
JOB_TIMEOUT_SECONDS = 600  # fallback training is capped at FALLBACK_TRAIN_TIMESTEPS, should finish well under this


class JobNotFoundError(LookupError):
    """The job id was never enqueued, or has expired from Redis."""


_redis: Redis | None = None
_queue: Queue | None = None


def _get_queue() -> Queue:
    global _redis, _queue
    if _queue is None:
        _redis = Redis.from_url(REDIS_URL)
        _queue = Queue(QUEUE_NAME, connection=_redis)
    return _queue


def enqueue(func_path: str, *args: Any, **kwargs: Any) -> str:
    """Enqueue a job by import path (e.g. 'src.task_jobs.train_optimizer_job')
    -- RQ needs an importable reference, not a closure, since the worker
    process re-imports it. Returns the job id."""
    job = _get_queue().enqueue(func_path, *args, job_timeout=JOB_TIMEOUT_SECONDS, **kwargs)
    return job.id


def get_status(job_id: str) -> dict[str, Any]:
    """Job status + result (if finished) + error (if failed). Raises if
    job_id was never enqueued or has already expired (JobNotFoundError)."""
    try:
        job = Job.fetch(job_id, connection=_get_queue().connection)
    except NoSuchJobError as exc:
        raise JobNotFoundError(job_id) from exc
    result: dict[str, Any] = {"job_id": job_id, "status": job.get_status()}
    if job.is_finished:
        result["result"] = job.result
    elif job.is_failed:
        result["error"] = str(job.exc_info)[-2000:] if job.exc_info else "Job failed with no traceback recorded"
    return result
