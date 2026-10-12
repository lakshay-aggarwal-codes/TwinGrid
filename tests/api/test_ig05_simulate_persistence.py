"""IG-05 / UQ-4 (ADR 007): GET /api/simulate/{hours} writes nothing by default; ``persist=true`` is operator-only
and stores rows stamped ``origin='simulated'``."""

from __future__ import annotations

from models.db_models import SensorReading, SimulationRun


async def test_default_request_writes_nothing(client, viewer_headers, count_rows):
    r = await client.get("/api/simulate/3", headers=viewer_headers)
    assert r.status_code == 200 and len(r.json()) > 0
    assert await count_rows(SimulationRun) == 0 and await count_rows(SensorReading) == 0


async def test_a_viewer_cannot_persist_and_nothing_is_written(client, viewer_headers, count_rows):
    r = await client.get("/api/simulate/3?persist=true", headers=viewer_headers)
    assert r.status_code == 403
    assert await count_rows(SimulationRun) == 0 and await count_rows(SensorReading) == 0


async def test_an_operator_persist_stores_one_run_and_one_simulated_row_per_step(
    client, operator_headers, count_rows, session_maker
):
    from sqlalchemy import select

    r = await client.get("/api/simulate/3?persist=true", headers=operator_headers)
    assert r.status_code == 200
    steps = len(r.json())
    assert await count_rows(SimulationRun) == 1
    assert await count_rows(SensorReading) == steps
    async with session_maker() as s:
        rows = (await s.execute(select(SensorReading))).scalars().all()
    assert {x.origin for x in rows} == {"simulated"} and all(x.simulation_run_id is not None for x in rows)


async def test_persist_false_explicitly_is_the_same_as_the_default(client, operator_headers, count_rows):
    assert (await client.get("/api/simulate/2?persist=false", headers=operator_headers)).status_code == 200
    assert await count_rows(SimulationRun) == 0 and await count_rows(SensorReading) == 0
