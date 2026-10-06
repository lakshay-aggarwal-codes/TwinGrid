"""T13: GET /metrics is bearer-protected; mandatory in production."""

import pytest

TOKEN = "m" * 40


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("METRICS_TOKEN", "METRICS_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


async def test_production_without_token_header_is_401(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("METRICS_TOKEN", TOKEN)
    r = await client.get("/metrics")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert "http_requests_total" not in r.text


@pytest.mark.parametrize(
    "headers",
    [bearer("wrong-" + TOKEN), bearer(""), {"Authorization": TOKEN}, {"Authorization": f"Basic {TOKEN}"}],
)
async def test_production_wrong_or_malformed_credentials_are_401(client, monkeypatch, headers):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("METRICS_TOKEN", TOKEN)
    assert (await client.get("/metrics", headers=headers)).status_code == 401


async def test_production_correct_token_is_200(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("METRICS_TOKEN", TOKEN)
    await client.get("/healthz")
    r = await client.get("/metrics", headers=bearer(TOKEN))
    assert r.status_code == 200
    assert "http_requests_total" in r.text


async def test_production_with_no_token_configured_stays_closed(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers=bearer(""))).status_code == 401
    assert (await client.get("/metrics", headers=bearer("anything"))).status_code == 401


async def test_unrecognised_environment_fails_closed(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    assert (await client.get("/metrics")).status_code == 401


@pytest.mark.parametrize("environment", ["development", "test"])
async def test_non_production_is_open_when_no_token_is_configured(client, monkeypatch, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    assert (await client.get("/metrics")).status_code == 200


@pytest.mark.parametrize("environment", ["development", "test"])
async def test_non_production_enforces_a_configured_token(client, monkeypatch, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("METRICS_TOKEN", TOKEN)
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers=bearer(TOKEN))).status_code == 200


async def test_token_can_come_from_a_file(client, monkeypatch, tmp_path):
    token_file = tmp_path / "metrics_token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("METRICS_TOKEN_FILE", str(token_file))
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers=bearer(TOKEN))).status_code == 200
