"""Run/job contract (BC-10 / G-RUN): submit a scenario, poll its status, fetch its result.

A run is a scenario from the registry (``scenario_registry``, BC-09) executed as a queued job: the API
enqueues ``src.run_jobs.run_whatif_job`` on the existing RQ queue (the one ``docker compose``'s ``worker``
service consumes) and reads the job back. State lives in Redis only: no new table, no migration.

Public status set (exactly these five; the client must treat anything else as unrecognised):

    queued     accepted, no worker has started it
    running    a worker is computing it
    completed  finished; the result is available at ``result_url``
    failed     ``failure_code`` says why (one of FAILURE_CODES)
    cancelled  the job was cancelled/stopped in the queue backend (no API cancels a run today)

There is no ``progress`` field and no ETA: the computation reports none.

Retention: a finished or failed run, with its result, is kept ``RUN_RESULT_TTL_SECONDS`` (default 24 h)
after it ends; after that its id answers 404, the same as an id that never existed.

Access: a run is readable by the user who submitted it and by operators. Anyone else, and any id that is
not a run (for example a training job id), gets 404.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Final

from fastapi import HTTPException, status
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError
from rq.job import Job

from api.schemas.runs import RunCreate
from api.services import scenario_registry as SR
from models.db_models import User
from src import task_queue

CONTRACT: Final[str] = "G-RUN/1"
RUN_KIND: Final[str] = "whatif"
JOB_FUNCTION: Final[str] = "src.run_jobs.run_whatif_job"

STATUS_QUEUED: Final[str] = "queued"
STATUS_RUNNING: Final[str] = "running"
STATUS_COMPLETED: Final[str] = "completed"
STATUS_FAILED: Final[str] = "failed"
STATUS_CANCELLED: Final[str] = "cancelled"
RUN_STATUSES: Final[tuple[str, ...]] = (
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)

FAILURE_CODES: Final[tuple[str, ...]] = ("invalid_input", "timeout", "worker_lost", "internal_error")

# RQ job status -> public run status. Anything RQ adds that is not listed here is reported as a failed
# run with ``internal_error`` (and never as a status the contract does not define).
_RQ_TO_RUN: Final[dict[str, str]] = {
    "created": STATUS_QUEUED,
    "queued": STATUS_QUEUED,
    "deferred": STATUS_QUEUED,
    "scheduled": STATUS_QUEUED,
    "started": STATUS_RUNNING,
    "finished": STATUS_COMPLETED,
    "failed": STATUS_FAILED,
    "stopped": STATUS_CANCELLED,
    "canceled": STATUS_CANCELLED,
}

_RUN_FAILED_RE = re.compile(r"RunFailed:\s*([a-z_]+)\s*$")


def result_ttl_seconds() -> int:
    raw = os.getenv("RUN_RESULT_TTL_SECONDS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return 86400
    return value if value > 0 else 86400


# -----------------------------------------------------------------------------
# Scenario set
# -----------------------------------------------------------------------------


def scenario_set_id() -> str:
    """Identity of the scenario set a run was submitted under: ``sset-<registry_version>-<12 hex>``.

    The hash covers the full registry payload (every descriptor: ids, kinds, sources, parameter schema,
    bounds and preset values), so it changes whenever any preset or bound changes. Two runs with the same
    ``scenario_set_id`` were defined by the same registry content. It says nothing about physics version
    (compare ``physics_version`` on the result) and it is not a hash of the individual run's parameters.
    """
    payload = SR.list_scenarios()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"sset-{payload['registry_version']}-{digest[:12]}"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def resolve_parameters(scenario_id: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """Precedence: explicit override > scenario preset. Same rule as ``GET /api/whatif``."""
    base = SR.scenario_defaults(scenario_id)
    return {k: (overrides[k] if overrides.get(k) is not None else base[k]) for k in base}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:  # RQ stores naive UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _failure_code(exc_info: str | None) -> str:
    lines = [ln for ln in str(exc_info or "").strip().splitlines() if ln.strip()]
    last = lines[-1].strip() if lines else ""
    match = _RUN_FAILED_RE.search(last)
    if match and match.group(1) in FAILURE_CODES:
        return match.group(1)
    if "JobTimeoutException" in last or "TimeoutError" in last:
        return "timeout"
    if "AbandonedJobError" in last or "WorkerLost" in last:
        return "worker_lost"
    return "internal_error"


def _is_run(job: Job) -> bool:
    return isinstance(job.meta, dict) and job.meta.get("contract") == CONTRACT


def _record(job: Job) -> dict[str, Any]:
    meta = job.meta
    rq_status = job.get_status()
    run_status = _RQ_TO_RUN.get(rq_status)
    failure_code: str | None = None
    if run_status is None:
        run_status, failure_code = STATUS_FAILED, "internal_error"
    elif run_status == STATUS_FAILED:
        failure_code = _failure_code(job.exc_info)
    return {
        "run_id": job.id,
        "kind": meta["kind"],
        "status": run_status,
        "scenario_id": meta["scenario_id"],
        "scenario_set_id": meta["scenario_set_id"],
        "registry_version": meta["registry_version"],
        "parameters": copy.deepcopy(meta["parameters"]),
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "ended_at": _iso(job.ended_at),
        "failure_code": failure_code,
        "result_url": f"/api/runs/{job.id}/result" if run_status == STATUS_COMPLETED else None,
    }


def _fetch_run(run_id: str, user: User) -> Job:
    """The run's job, or 404. 404 covers: not a UUID, never existed, expired, not a run, not yours."""
    not_found = HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise not_found from None
    queue = task_queue._get_queue()
    try:
        job = Job.fetch(run_id, connection=queue.connection, serializer=queue.serializer)
    except NoSuchJobError:
        raise not_found from None
    if not _is_run(job):
        raise not_found
    if job.meta.get("owner_id") != user.id and not user.is_operator():
        raise not_found
    return job


def _queue_unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job queue unavailable")


# -----------------------------------------------------------------------------
# Operations (blocking Redis calls; the async wrappers run them in a thread)
# -----------------------------------------------------------------------------


def _submit_sync(body: RunCreate, user: User) -> dict[str, Any]:
    descriptor = SR.get_scenario(body.scenario_id)
    if descriptor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown scenario_id: {body.scenario_id!r}")
    parameters = resolve_parameters(body.scenario_id, body.parameters.model_dump(exclude_none=True))
    run_id = str(uuid.uuid4())
    meta = {
        "contract": CONTRACT,
        "kind": RUN_KIND,
        "owner_id": user.id,
        "scenario_id": body.scenario_id,
        "scenario_set_id": scenario_set_id(),
        "registry_version": SR.REGISTRY_VERSION,
        "parameters": parameters,
        "descriptor": {k: descriptor[k] for k in ("kind", "weather_source", "plant", "control")},
    }
    ttl = result_ttl_seconds()
    try:
        task_queue.enqueue(
            JOB_FUNCTION,
            run_id,
            body.scenario_id,
            parameters,
            job_id=run_id,
            meta=meta,
            result_ttl=ttl,
            failure_ttl=ttl,
        )
        queue = task_queue._get_queue()
        job = Job.fetch(run_id, connection=queue.connection, serializer=queue.serializer)
    except RedisError as exc:
        raise _queue_unavailable() from exc
    return _record(job)


def _status_sync(run_id: str, user: User) -> dict[str, Any]:
    try:
        return _record(_fetch_run(run_id, user))
    except RedisError as exc:
        raise _queue_unavailable() from exc


def _result_sync(run_id: str, user: User) -> dict[str, Any]:
    try:
        job = _fetch_run(run_id, user)
        record = _record(job)
        if record["status"] != STATUS_COMPLETED:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Run has no result (status: {record['status']})")
        done = job.result
    except RedisError as exc:
        raise _queue_unavailable() from exc
    if not isinstance(done, dict) or done.get("run_id") != job.id:
        # A result that does not belong to this run is never returned.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Run result unavailable")
    meta = job.meta
    return {
        "run_id": job.id,
        "kind": meta["kind"],
        "scenario_id": meta["scenario_id"],
        "scenario_set_id": meta["scenario_set_id"],
        "registry_version": meta["registry_version"],
        "parameters": copy.deepcopy(meta["parameters"]),
        "started_at": record["started_at"],
        "ended_at": record["ended_at"],
        "provenance": {
            "origin": "simulated",
            "scenario_kind": meta["descriptor"]["kind"],
            "weather_source": meta["descriptor"]["weather_source"],
            "plant": meta["descriptor"]["plant"],
            "control": meta["descriptor"]["control"],
            "physics_version": done["physics_version"],
            "model_version": None,  # a what-if applies no learned model
            "carbon_data_is_real": done["outputs"].get("carbon_data_is_real"),
        },
        "outputs": done["outputs"],
    }


async def submit_run(body: RunCreate, user: User) -> dict[str, Any]:
    return await asyncio.to_thread(_submit_sync, body, user)


async def get_run(run_id: str, user: User) -> dict[str, Any]:
    return await asyncio.to_thread(_status_sync, run_id, user)


async def get_run_result(run_id: str, user: User) -> dict[str, Any]:
    return await asyncio.to_thread(_result_sync, run_id, user)
