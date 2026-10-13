"""Task 9: the committed API reference (docs/api/) matches what the code generates now.

Regenerates in memory with scripts/gen_api_reference.py and compares with the committed files. If this fails,
a route changed: run ``python scripts/gen_api_reference.py`` and commit docs/api/. No network, no database.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-suite-only")
os.environ["ENVIRONMENT"] = "development"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_api_reference_under_test", ROOT / "scripts" / "gen_api_reference.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated():
    gen = _load_generator()
    return gen, *gen.generate()


def _committed(path: str) -> str:
    file = ROOT / path
    assert file.exists(), f"{path} is missing: run `python scripts/gen_api_reference.py` and commit docs/api/"
    return file.read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_openapi_json_is_not_stale(generated):
    _, openapi_text, _ = generated
    assert (
        _committed("docs/api/openapi.json") == openapi_text
    ), "docs/api/openapi.json is stale: run `python scripts/gen_api_reference.py` and commit docs/api/"


def test_readme_is_not_stale(generated):
    _, _, readme_text = generated
    assert (
        _committed("docs/api/README.md") == readme_text
    ), "docs/api/README.md is stale: run `python scripts/gen_api_reference.py` and commit docs/api/"


def test_generation_is_deterministic(generated):
    gen, openapi_text, readme_text = generated
    again_openapi, again_readme = gen.generate()
    assert again_openapi == openapi_text
    assert again_readme == readme_text


def test_output_shape_and_no_secret_leak(generated):
    _, openapi_text, readme_text = generated
    spec = json.loads(openapi_text)
    assert openapi_text.endswith("\n") and "\r" not in openapi_text
    assert spec["paths"], "no paths documented"
    assert "/auth/login" in spec["paths"]
    assert "/api/state" in spec["paths"]
    for section in ("## Authentication", "## Rate-limit classes", "## Error shape", "## Endpoints"):
        assert section in readme_text
    assert "urn:twingrid:error:" in readme_text
    assert "gen-api-reference-placeholder-not-a-secret" not in openapi_text + readme_text
    assert os.environ["JWT_SECRET_KEY"] not in openapi_text + readme_text


def test_readme_lists_every_openapi_operation(generated):
    _, openapi_text, readme_text = generated
    spec = json.loads(openapi_text)
    for path, item in spec["paths"].items():
        for method in item:
            if method in {"get", "put", "post", "delete", "patch"}:
                assert f"| {method.upper()} | `{path}` |" in readme_text


def test_operator_routes_and_rate_classes_are_reported(generated):
    _, _, readme_text = generated
    assert "| POST | `/api/optimize` | bearer, role `operator` |" in readme_text
    assert "| GET | `/api/state` | bearer (any valid user) |" in readme_text
    assert "NOT DETERMINED" not in readme_text


def test_api_documentation_is_a_pointer():
    text = (ROOT / "API_DOCUMENTATION.md").read_text(encoding="utf-8")
    assert "docs/api/README.md" in text
    assert len(text.splitlines()) < 30
