# API Documentation

The API reference is generated from the code and lives in [`docs/api/`](docs/api/):

- [`docs/api/README.md`](docs/api/README.md) - endpoints, authentication, rate-limit classes, error shape.
- [`docs/api/openapi.json`](docs/api/openapi.json) - the OpenAPI document.

A running server also serves `/docs` (Swagger UI), `/redoc` and `/openapi.json`.

To regenerate after a route change: `python scripts/gen_api_reference.py`
(`--check` exits 1 if the committed files are stale; `tests/test_task9_api_reference.py` enforces the same).

Token lifecycle and security notes: [`SECURITY.md`](SECURITY.md). All data served is simulated.

## What-if responses (R3 Tasks 1 and 2)

`GET /api/whatif` and `GET /api/whatif/sensitivity` take `chilled_water_temp` in the range of the active physics version:
5 to 15 C under `legacy-0`, 16 to 25 C under physics `1`. The query itself allows 5 to 25 C; a value outside the active
range returns 422 with the accepted range in the message.

`/api/whatif` responses carry `physics_version` and a `provenance` object with `origin`, `scenario_kind`, `weather_source`,
`plant`, `control`, `model_version`, `registry_version` and `api_version`. `api_version` is the application version, not a
build id. A preset scenario and the equivalent raw request return the same numbers; only `provenance.scenario_kind` differs.
The field-level contract is in `twin-stream-insight-main/docs/frontend/contracts/G-SCN.md` and `G-RUN.md`.
