"""Task 1: the backend plugin loader (api/plugins). Uses the fixture package in tests/plugin_fixtures."""

from __future__ import annotations

import logging
import sys

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.plugins import PluginResult, load_plugins

FIXTURES = "tests.plugin_fixtures"


def _fresh_app() -> FastAPI:
    app = FastAPI()

    @app.get("/existing")
    def existing() -> dict[str, str]:
        return {"ok": "core"}

    return app


def _skips(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == "api.plugins"
        and r.getMessage().startswith("plugin ")
        and "skipped" in r.getMessage()
        and r.levelno >= logging.WARNING
    ]


def _by_name(results: list[PluginResult]) -> dict[str, PluginResult]:
    return {r.name: r for r in results}


@pytest.fixture(autouse=True)
def _forget_fixture_modules():
    yield
    for name in [m for m in sys.modules if m.startswith(FIXTURES + ".")]:
        del sys.modules[name]


def test_discovery_loads_router_and_setup_plugins_and_skips_the_rest():
    app = _fresh_app()
    results = _by_name(load_plugins(app, package=FIXTURES))

    assert results["ok_router"].status == "loaded"
    assert results["ok_setup"].status == "loaded"
    assert results["broken_import"] == PluginResult("broken_import", "skipped", "import_failed")
    assert results["broken_setup"] == PluginResult("broken_setup", "skipped", "setup_failed")
    assert results["bad_router"] == PluginResult("bad_router", "skipped", "invalid_router")
    assert results["zz_colliding"] == PluginResult("zz_colliding", "skipped", "route_collision")
    assert results["no_entry"] == PluginResult("no_entry", "skipped", "no_entry_point")
    assert "_private_helper" not in results  # underscore modules are never imported

    client = TestClient(app)
    assert client.get("/api/_fixture/ping").json() == {"pong": "router"}  # first plugin wins, not the colliding one
    assert client.get("/api/_fixture/setup").json() == {"pong": "setup"}
    assert client.get("/existing").json() == {"ok": "core"}
    assert app.state.fixture_setup_ran is True


def test_failed_plugin_registers_nothing_and_does_not_break_the_app():
    app = _fresh_app()
    load_plugins(app, package=FIXTURES)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/_fixture/never-registered" not in paths  # setup raised -> its router was not included
    assert TestClient(app).get("/existing").status_code == 200


def test_failure_details_never_reach_clients_or_results():
    app = _fresh_app()
    results = load_plugins(app, package=FIXTURES)
    blob = repr(results)
    assert "postgres://" not in blob and "secret-looking-detail" not in blob and "exploded" not in blob
    body = TestClient(app).get("/api/_fixture/never-registered").text
    assert "Traceback" not in body and "exploded" not in body


def test_failures_log_at_warning_in_development(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "development")
    with caplog.at_level(logging.DEBUG, logger="api.plugins"):
        load_plugins(_fresh_app(), package=FIXTURES)
    failing = _skips(caplog)
    assert failing, "skips must be logged"
    assert {r.levelno for r in failing} == {logging.WARNING}


def test_failures_log_at_error_in_production(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with caplog.at_level(logging.DEBUG, logger="api.plugins"):
        load_plugins(_fresh_app(), package=FIXTURES)
    failing = _skips(caplog)
    assert {r.levelno for r in failing} == {logging.ERROR}
    assert len(failing) == 4  # broken_import, broken_setup, bad_router, zz_colliding (no_entry is INFO)


def test_second_call_changes_nothing():
    app = _fresh_app()
    first = load_plugins(app, package=FIXTURES)
    n_routes = len(app.routes)
    second = load_plugins(app, package=FIXTURES)
    assert second == first
    assert len(app.routes) == n_routes


def test_plugin_cannot_reregister_a_router_the_app_already_includes():
    from tests.plugin_fixtures.ok_router import router as already_included

    app = _fresh_app()
    app.include_router(already_included)  # stands in for a core router wired in api/main.py
    result = _by_name(load_plugins(app, package=FIXTURES))["ok_router"]
    assert result == PluginResult("ok_router", "skipped", "route_collision")
    assert TestClient(app).get("/api/_fixture/ping").json() == {"pong": "router"}  # still served exactly once


def test_default_dependencies_are_applied_to_plugin_routers():
    calls: list[str] = []

    def dep() -> None:
        calls.append("dep")

    app = _fresh_app()
    load_plugins(app, package=FIXTURES, dependencies=[Depends(dep)])
    assert TestClient(app).get("/api/_fixture/ping").status_code == 200
    assert calls == ["dep"]


def test_missing_plugin_package_is_isolated(caplog):
    app = _fresh_app()
    with caplog.at_level(logging.DEBUG, logger="api.plugins"):
        assert load_plugins(app, package="tests.does_not_exist") == []
    assert app.state.plugin_results == ()


def test_real_app_loads_the_shipped_plugin_package_and_keeps_every_route_limited():
    from api.main import app

    assert app.state.plugin_results is not None  # load_plugins ran exactly once on the real app
    assert not [r for r in app.state.plugin_results if r.status != "loaded"], "a shipped plugin failed to load"
    assert not any(getattr(r, "path", "").startswith("/api/_fixture") for r in app.routes)  # fixtures never ship
