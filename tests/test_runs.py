"""BC-10 / G-RUN: POST /api/runs, GET /api/runs/{id}, GET /api/runs/{id}/result.

Redis is fakeredis and the worker is a real ``rq.SimpleWorker`` using the same JSON serializer as
docker-compose's ``worker`` service, so a run goes through enqueue -> worker -> result for real.
What this does NOT exercise: a real Redis server, the forking ``rq worker`` process, docker.
"""

from __future__ import annotations

import re
import uuid

import fakeredis
import pytest
from rq import Queue, SimpleWorker
from rq.serializers import JSONSerializer
from rq.timeouts import TimerDeathPenalty

from api.services import run_service
from api.services import scenario_registry as SR
from src import task_queue
from tests.test_api_routes_smoke import _register_and_login, client, operator, viewer  # noqa: F401  (pytest fixtures)

STATUS_KEYS = {
    "run_id",
    "kind",
    "status",
    "scenario_id",
    "scenario_set_id",
    "registry_version",
    "parameters",
    "created_at",
    "started_at",
    "ended_at",
    "failure_code",
    "result_url",
}
PARAM_KEYS = {"utilisation", "outside_temp", "water_stress", "mode", "chilled_water_temp"}


@pytest.fixture
def queue(monkeypatch):
    conn = fakeredis.FakeStrictRedis()
    q = Queue(task_queue.QUEUE_NAME, connection=conn, serializer=JSONSerializer)
    monkeypatch.setattr(task_queue, "_redis", conn)
    monkeypatch.setattr(task_queue, "_queue", q)
    return q


def work(queue) -> None:
    worker = SimpleWorker([queue], connection=queue.connection, serializer=JSONSerializer)
    worker.death_penalty_class = TimerDeathPenalty
    worker.work(burst=True)


async def submit(http, headers, scenario_id="whatif-heat-wave", parameters=None):
    body = {"scenario_id": scenario_id}
    if parameters is not None:
        body["parameters"] = parameters
    return await http.post("/api/runs", headers=headers, json=body)


# ---- scenario set ----------------------------------------------------------------------------


def test_scenario_set_id_is_stable_and_tracks_registry_content(monkeypatch):
    a = run_service.scenario_set_id()
    assert a == run_service.scenario_set_id()
    assert re.fullmatch(r"sset-1-[0-9a-f]{12}", a)
    changed = SR.list_scenarios()
    changed["scenarios"][0]["label"] = "changed"
    monkeypatch.setattr(SR, "list_scenarios", lambda: changed)
    assert run_service.scenario_set_id() != a


def test_resolve_parameters_precedence_is_override_then_preset():
    p = run_service.resolve_parameters("whatif-heat-wave", {"outside_temp": 30.0, "mode": "free_air"})
    assert p == {
        "utilisation": 0.65,
        "outside_temp": 30.0,
        "water_stress": 0.0,
        "mode": "free_air",
        "chilled_water_temp": 7.0,
    }
    assert run_service.resolve_parameters("whatif-heat-wave", {})["outside_temp"] == 38.0


# ---- auth and validation ---------------------------------------------------------------------


async def test_runs_require_auth(client, queue):  # noqa: F811
    assert (await client.post("/api/runs", json={"scenario_id": "whatif-baseline"})).status_code in (401, 403)
    rid = str(uuid.uuid4())
    assert (await client.get(f"/api/runs/{rid}")).status_code in (401, 403)
    assert (await client.get(f"/api/runs/{rid}/result")).status_code in (401, 403)


async def test_unknown_scenario_is_404_and_enqueues_nothing(client, viewer, queue):  # noqa: F811
    r = await submit(client, viewer, "nope")
    assert r.status_code == 404
    assert queue.count == 0


@pytest.mark.parametrize(
    "parameters",
    [
        {"utilisation": 2},
        {"outside_temp": 99},
        {"water_stress": -0.1},
        {"chilled_water_temp": 4},
        {"mode": "teleport"},
        {"bogus": 1},
    ],
)
async def test_out_of_range_or_unknown_parameter_is_422(client, viewer, queue, parameters):  # noqa: F811
    r = await submit(client, viewer, "whatif-baseline", parameters)
    assert r.status_code == 422
    assert queue.count == 0


async def test_missing_scenario_id_and_extra_fields_are_422(client, viewer, queue):  # noqa: F811
    assert (await client.post("/api/runs", headers=viewer, json={})).status_code == 422
    r = await client.post("/api/runs", headers=viewer, json={"scenario_id": "whatif-baseline", "x": 1})
    assert r.status_code == 422


# ---- lifecycle -------------------------------------------------------------------------------


async def test_submit_returns_202_queued_record(client, viewer, queue):  # noqa: F811
    r = await submit(client, viewer, parameters={"outside_temp": 30})
    assert r.status_code == 202
    body = r.json()
    assert set(body) == STATUS_KEYS
    assert body["status"] == "queued"
    assert body["kind"] == "whatif"
    assert body["scenario_id"] == "whatif-heat-wave"
    assert body["scenario_set_id"] == run_service.scenario_set_id()
    assert set(body["parameters"]) == PARAM_KEYS
    assert body["parameters"]["outside_temp"] == 30.0  # explicit override beats the 38.0 preset
    assert body["parameters"]["utilisation"] == 0.65
    assert body["started_at"] is None and body["ended_at"] is None
    assert body["failure_code"] is None and body["result_url"] is None
    assert body["created_at"].endswith("+00:00")
    assert r.headers["location"] == f"/api/runs/{body['run_id']}"
    assert "progress" not in body
    uuid.UUID(body["run_id"])


async def test_full_lifecycle_queued_then_completed_with_result(client, viewer, queue):  # noqa: F811
    run = (await submit(client, viewer)).json()
    rid = run["run_id"]
    assert (await client.get(f"/api/runs/{rid}", headers=viewer)).json()["status"] == "queued"

    not_ready = await client.get(f"/api/runs/{rid}/result", headers=viewer)
    assert not_ready.status_code == 409  # a submitted job is not a result

    work(queue)

    st = (await client.get(f"/api/runs/{rid}", headers=viewer)).json()
    assert set(st) == STATUS_KEYS
    assert st["status"] == "completed"
    assert st["started_at"] and st["ended_at"] and st["failure_code"] is None
    assert st["result_url"] == f"/api/runs/{rid}/result"
    assert st["created_at"] <= st["started_at"] <= st["ended_at"]

    res = (await client.get(st["result_url"], headers=viewer)).json()
    assert res["run_id"] == rid
    assert res["scenario_id"] == "whatif-heat-wave"
    assert res["scenario_set_id"] == run["scenario_set_id"]
    assert res["parameters"] == run["parameters"]
    assert res["provenance"]["origin"] == "simulated"
    assert res["provenance"]["weather_source"] == "constant_input"
    assert res["provenance"]["plant"] == "simulated"
    assert res["provenance"]["control"] == "none"
    assert res["provenance"]["model_version"] is None
    assert res["provenance"]["physics_version"] in ("legacy-0", "1", "2")
    assert "inputs" not in res["outputs"]


async def test_result_equals_the_synchronous_whatif(client, viewer, queue):  # noqa: F811
    rid = (await submit(client, viewer, "whatif-peak-workload")).json()["run_id"]
    work(queue)
    res = (await client.get(f"/api/runs/{rid}/result", headers=viewer)).json()
    direct = (await client.get("/api/whatif", headers=viewer, params={"scenario_id": "whatif-peak-workload"})).json()
    direct.pop("scenario_id")
    direct.pop("inputs")
    assert res["outputs"] == direct


async def test_failed_run_reports_only_a_code(client, viewer, queue, monkeypatch):  # noqa: F811
    from api.services import twin_service

    def boom(*a, **k):
        raise RuntimeError("secret detail at /srv/app/private/path.py")

    monkeypatch.setattr(twin_service, "compute_whatif", boom)
    rid = (await submit(client, viewer)).json()["run_id"]
    work(queue)
    st = (await client.get(f"/api/runs/{rid}", headers=viewer)).json()
    assert st["status"] == "failed"
    assert st["failure_code"] == "internal_error"
    assert st["result_url"] is None
    assert "secret" not in str(st) and "/srv" not in str(st)
    r = await client.get(f"/api/runs/{rid}/result", headers=viewer)
    assert r.status_code == 409 and "secret" not in r.text


async def test_invalid_input_in_worker_maps_to_invalid_input(client, viewer, queue, monkeypatch):  # noqa: F811
    from api.services import twin_service
    from src.digital_twin import InvalidInputError

    def bad(*a, **k):
        raise InvalidInputError("x", field="utilisation")

    monkeypatch.setattr(twin_service, "compute_whatif", bad)
    rid = (await submit(client, viewer)).json()["run_id"]
    work(queue)
    assert (await client.get(f"/api/runs/{rid}", headers=viewer)).json()["failure_code"] == "invalid_input"


@pytest.mark.parametrize(
    "exc_info, code",
    [
        ("Traceback...\nsrc.run_jobs.RunFailed: invalid_input", "invalid_input"),
        ("Traceback...\nsrc.run_jobs.RunFailed: nonsense_code", "internal_error"),
        ("Traceback...\nrq.timeouts.JobTimeoutException: Task exceeded maximum timeout value (600 seconds)", "timeout"),
        ("Traceback...\nrq.exceptions.AbandonedJobError: Job was abandoned", "worker_lost"),
        ("ValueError: anything else", "internal_error"),
        (None, "internal_error"),
    ],
)
def test_failure_code_mapping(exc_info, code):
    assert run_service._failure_code(exc_info) == code


@pytest.mark.parametrize(
    "rq_status, expected",
    [
        ("created", "queued"),
        ("queued", "queued"),
        ("deferred", "queued"),
        ("scheduled", "queued"),
        ("started", "running"),
        ("finished", "completed"),
        ("failed", "failed"),
        ("stopped", "cancelled"),
        ("canceled", "cancelled"),
    ],
)
def test_every_rq_status_maps_into_the_public_set(rq_status, expected):
    assert run_service._RQ_TO_RUN[rq_status] == expected
    assert expected in run_service.RUN_STATUSES


async def test_running_status_is_reported_while_a_worker_holds_the_job(client, viewer, queue):  # noqa: F811
    rid = (await submit(client, viewer)).json()["run_id"]
    from rq.job import Job, JobStatus

    job = Job.fetch(rid, connection=queue.connection, serializer=JSONSerializer)
    job.set_status(JobStatus.STARTED)
    st = (await client.get(f"/api/runs/{rid}", headers=viewer)).json()
    assert st["status"] == "running"
    assert st["result_url"] is None


# ---- 404 and isolation -----------------------------------------------------------------------


@pytest.mark.parametrize("rid", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
async def test_unknown_run_is_404(client, viewer, queue, rid):  # noqa: F811
    assert (await client.get(f"/api/runs/{rid}", headers=viewer)).status_code == 404
    assert (await client.get(f"/api/runs/{rid}/result", headers=viewer)).status_code == 404


async def test_a_non_run_job_id_is_404(client, viewer, queue):  # noqa: F811
    """The training-job id space (POST /api/optimize/train_async) must not be readable through /api/runs."""
    job_id = task_queue.enqueue("src.task_jobs.train_optimizer_job", 0.5, 0.3, 0.2, 0.0, job_id=str(uuid.uuid4()))
    assert (await client.get(f"/api/runs/{job_id}", headers=viewer)).status_code == 404


async def test_other_viewer_gets_404_but_operator_can_read(client, viewer, operator, queue):  # noqa: F811
    rid = (await submit(client, viewer)).json()["run_id"]
    work(queue)
    other = await _register_and_login(client, "viewer2")
    other_h = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get(f"/api/runs/{rid}", headers=other_h)).status_code == 404
    assert (await client.get(f"/api/runs/{rid}/result", headers=other_h)).status_code == 404
    assert (await client.get(f"/api/runs/{rid}", headers=operator)).status_code == 200
    assert (await client.get(f"/api/runs/{rid}/result", headers=operator)).status_code == 200


async def test_result_from_another_run_is_never_returned(client, viewer, queue, monkeypatch):  # noqa: F811
    rid = (await submit(client, viewer)).json()["run_id"]
    work(queue)
    from rq.job import Job

    real = Job.result
    monkeypatch.setattr(Job, "result", property(lambda self: {**real.fget(self), "run_id": str(uuid.uuid4())}))
    assert (await client.get(f"/api/runs/{rid}/result", headers=viewer)).status_code == 500


async def test_queue_down_is_503(client, viewer, queue, monkeypatch):  # noqa: F811
    from redis.exceptions import ConnectionError as RedisConnectionError

    def down(*a, **k):
        raise RedisConnectionError("redis://:secret@host down")

    monkeypatch.setattr(task_queue, "enqueue", down)
    r = await submit(client, viewer)
    assert r.status_code == 503 and "secret" not in r.text


async def test_run_does_not_touch_whatif_or_scenarios_contract(client, viewer, queue):  # noqa: F811
    assert (await client.get("/api/scenarios", headers=viewer)).json() == SR.list_scenarios()
