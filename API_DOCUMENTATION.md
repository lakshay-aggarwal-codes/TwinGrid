# API Documentation

The API reference is generated from the code and lives in [`docs/api/`](docs/api/):

- [`docs/api/README.md`](docs/api/README.md) - endpoints, authentication, rate-limit classes, error shape.
- [`docs/api/openapi.json`](docs/api/openapi.json) - the OpenAPI document.

A running server also serves `/docs` (Swagger UI), `/redoc` and `/openapi.json`.

To regenerate after a route change: `python scripts/gen_api_reference.py`
(`--check` exits 1 if the committed files are stale; `tests/test_task9_api_reference.py` enforces the same).

Token lifecycle and security notes: [`SECURITY.md`](SECURITY.md). All data served is simulated.
