"""T13: startup validation (api/startup_checks.py), compose/Dockerfile safety, .env.example coverage."""

from __future__ import annotations

import ast
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from api import startup_checks as sc
from api.startup_checks import RULES, StartupConfigError

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = ("development", "test", "production")

GOOD_JWT = "0123456789abcdef" * 4
GOOD_METRICS = "fedcba9876543210" * 4
GOOD_OPERATOR = "operator-key-" + "x" * 30
GOOD_DB = "postgresql+asyncpg://app:Zk39xQpL2mVr8@db.internal:5432/digital_twin"
ENV_EXAMPLE_JWT = "your-secret-key-here-change-in-production"
CI_JWT = "ci-test-secret-not-for-production"

MANAGED = (
    "ENVIRONMENT",
    "JWT_SECRET_KEY",
    "JWT_SECRET_KEY_FILE",
    "METRICS_TOKEN",
    "METRICS_TOKEN_FILE",
    "CORS_ALLOWED_ORIGINS",
    "DATABASE_URL",
    "DATABASE_URL_FILE",
    "OPERATOR_REGISTRATION_KEY",
    "OPERATOR_REGISTRATION_KEY_FILE",
    "MOCK_SENSORS",
)


def valid_env(monkeypatch, environment: str = "production") -> None:
    for name in MANAGED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("JWT_SECRET_KEY", GOOD_JWT)
    monkeypatch.setenv("METRICS_TOKEN", GOOD_METRICS)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("DATABASE_URL", GOOD_DB)
    monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", GOOD_OPERATOR)
    monkeypatch.setenv("MOCK_SENSORS", "0")


# rule id -> (mutation that makes exactly that rule fail, the secret-ish value that must never be echoed)
def _set(name, value):
    return lambda mp: mp.setenv(name, value)


def _unset(name):
    return lambda mp: mp.delenv(name, raising=False)


BAD = {
    "R01-env-name": _set("ENVIRONMENT", "prod"),
    "R02-jwt-missing": _unset("JWT_SECRET_KEY"),
    "R03-jwt-known-value": _set("JWT_SECRET_KEY", ENV_EXAMPLE_JWT),
    "R04-jwt-weak": _set("JWT_SECRET_KEY", "short-SECRETVALUE123"),
    "R05-metrics-token-missing": _unset("METRICS_TOKEN"),
    "R06-metrics-token-known-value": _set("METRICS_TOKEN", "change-me-to-a-long-random-metrics-token"),
    "R07-metrics-token-weak": _set("METRICS_TOKEN", "short-SECRETVALUE456"),
    "R08-cors": _set("CORS_ALLOWED_ORIGINS", "https://app.example.com,*"),
    "R09-database-url": _set("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/digital_twin"),
    "R10-operator-key": _set("OPERATOR_REGISTRATION_KEY", "change-me-to-a-long-random-string"),
    "R11-mock-sensors": _set("MOCK_SENSORS", "true"),
}
ALL_ENVIRONMENT_RULES = {"R01-env-name", "R02-jwt-missing"}
PRODUCTION_ONLY = sorted(set(BAD) - ALL_ENVIRONMENT_RULES)


def test_every_rule_has_a_test_case():
    assert {r.id for r in RULES} == set(BAD)


def test_valid_configuration_passes_in_every_environment(monkeypatch):
    for environment in ENVIRONMENTS:
        valid_env(monkeypatch, environment)
        sc.validate_startup_config()


# --------------------------------------------------------------------------- one test per rule x environment


@pytest.mark.parametrize("rule_id", sorted(BAD))
def test_rule_fails_in_production(monkeypatch, rule_id):
    valid_env(monkeypatch, "production")
    BAD[rule_id](monkeypatch)
    # R01 changes ENVIRONMENT itself, so there is no "production" to ask about: the name is invalid.
    assert rule_id in {r.id for r in sc.find_violations()}
    with pytest.raises(StartupConfigError) as info:
        sc.validate_startup_config()
    assert rule_id in str(info.value)
    rule = next(r for r in RULES if r.id == rule_id)
    for name in rule.variables:
        assert name in info.value.variables


@pytest.mark.parametrize("environment", ["development", "test"])
@pytest.mark.parametrize("rule_id", PRODUCTION_ONLY)
def test_production_only_rule_passes_in_development_and_test(monkeypatch, rule_id, environment):
    valid_env(monkeypatch, environment)
    BAD[rule_id](monkeypatch)
    assert rule_id not in {r.id for r in sc.find_violations()}
    sc.validate_startup_config()  # the repo's own dev/CI values are accepted, not the rule weakened


@pytest.mark.parametrize("environment", ["development", "test"])
@pytest.mark.parametrize("rule_id", sorted(ALL_ENVIRONMENT_RULES - {"R01-env-name"}))
def test_all_environment_rule_fails_in_development_and_test(monkeypatch, rule_id, environment):
    valid_env(monkeypatch, environment)
    BAD[rule_id](monkeypatch)
    with pytest.raises(StartupConfigError):
        sc.validate_startup_config()


@pytest.mark.parametrize("value", ["prod", "staging", "Production-1", ""])
def test_unknown_environment_fails_in_every_case(monkeypatch, value):
    valid_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", value)
    # "" is treated like any other value that is not a valid name
    with pytest.raises(StartupConfigError) as info:
        sc.validate_startup_config()
    assert "ENVIRONMENT" in info.value.variables


def test_environment_name_is_normalised_and_unset_means_development(monkeypatch):
    valid_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "  Production ")
    sc.validate_startup_config()
    monkeypatch.delenv("ENVIRONMENT")
    assert sc.raw_environment() == "development"
    sc.validate_startup_config()


@pytest.mark.parametrize("secret", [ENV_EXAMPLE_JWT, CI_JWT])
def test_env_example_and_ci_secrets_fail_in_production_only(monkeypatch, secret):
    for environment, should_fail in (("production", True), ("development", False), ("test", False)):
        valid_env(monkeypatch, environment)
        monkeypatch.setenv("JWT_SECRET_KEY", secret)
        if should_fail:
            with pytest.raises(StartupConfigError):
                sc.validate_startup_config()
        else:
            sc.validate_startup_config()


def test_error_lists_names_never_values(monkeypatch):
    valid_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET_KEY", "short-SECRETVALUE123")
    monkeypatch.setenv("METRICS_TOKEN", "short-SECRETVALUE456")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@db-host-SECRETHOST/x")
    with pytest.raises(StartupConfigError) as info:
        sc.validate_startup_config()
    text = str(info.value)
    assert info.value.variables == ["CORS_ALLOWED_ORIGINS", "DATABASE_URL", "JWT_SECRET_KEY", "METRICS_TOKEN"]
    for leaked in ("SECRETVALUE123", "SECRETVALUE456", "SECRETHOST", "postgres:postgres"):
        assert leaked not in text
    assert isinstance(info.value, RuntimeError)


def test_secret_files_are_honoured(monkeypatch, tmp_path):
    valid_env(monkeypatch)
    token_file = tmp_path / "metrics_token"
    token_file.write_text(CI_JWT + "\n", encoding="utf-8")
    monkeypatch.delenv("METRICS_TOKEN")
    monkeypatch.setenv("METRICS_TOKEN_FILE", str(token_file))
    with pytest.raises(StartupConfigError) as info:
        sc.validate_startup_config()
    assert "METRICS_TOKEN" in info.value.variables
    token_file.write_text(GOOD_METRICS, encoding="utf-8")
    sc.validate_startup_config()


def test_unreadable_secret_file_names_the_variable_not_the_path(monkeypatch, tmp_path):
    valid_env(monkeypatch)
    monkeypatch.delenv("METRICS_TOKEN")
    monkeypatch.setenv("METRICS_TOKEN_FILE", str(tmp_path / "missing-SECRETPATH"))
    with pytest.raises(StartupConfigError) as info:
        sc.validate_startup_config()
    assert "METRICS_TOKEN_FILE" in info.value.variables
    assert "SECRETPATH" not in str(info.value)


# --------------------------------------------------------------------------- delegation from auth / config


def _reload_auth():
    import api.auth as auth_module

    return importlib.reload(auth_module)


def test_auth_delegates_the_secret_check(monkeypatch):
    valid_env(monkeypatch, "production")
    monkeypatch.setenv("JWT_SECRET_KEY", ENV_EXAMPLE_JWT)
    try:
        with pytest.raises(StartupConfigError) as info:
            _reload_auth()
        assert info.value.variables == ["JWT_SECRET_KEY"]
        assert ENV_EXAMPLE_JWT not in str(info.value)

        monkeypatch.setenv("ENVIRONMENT", "development")
        assert _reload_auth().SECRET_KEY == ENV_EXAMPLE_JWT  # accepted outside production
    finally:
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-suite-only")
        _reload_auth()


def test_config_cors_error_is_a_startup_config_error(monkeypatch):
    import api.config as config_module

    valid_env(monkeypatch)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS")
    try:
        with pytest.raises(StartupConfigError) as info:
            importlib.reload(config_module)
        assert info.value.variables == ["CORS_ALLOWED_ORIGINS"]
    finally:
        monkeypatch.setenv("ENVIRONMENT", "development")
        importlib.reload(config_module)


# --------------------------------------------------------------------------- container behaviour


def _run_checks(extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "api.startup_checks"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
    )


GOOD_PROD = {
    "ENVIRONMENT": "production",
    "JWT_SECRET_KEY": GOOD_JWT,
    "METRICS_TOKEN": GOOD_METRICS,
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
    "DATABASE_URL": GOOD_DB,
}


def test_startup_check_command_exits_non_zero_on_bad_env_and_zero_on_good():
    bad = _run_checks({**GOOD_PROD, "ENVIRONMENT": "prod", "JWT_SECRET_KEY": "short-SECRETVALUE123"})
    assert bad.returncode == 1
    assert "ENVIRONMENT" in bad.stderr and "JWT_SECRET_KEY" in bad.stderr
    assert "SECRETVALUE123" not in bad.stdout + bad.stderr

    assert _run_checks(GOOD_PROD).returncode == 0
    assert _run_checks({"ENVIRONMENT": "development", "JWT_SECRET_KEY": CI_JWT}).returncode == 0
    assert _run_checks({"ENVIRONMENT": "test", "JWT_SECRET_KEY": CI_JWT}).returncode == 0
    assert _run_checks({"ENVIRONMENT": "production", "JWT_SECRET_KEY": CI_JWT}).returncode == 1


def test_dockerfile_validates_before_migrations_and_defaults_to_production():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cmd = next(line for line in text.splitlines() if line.startswith("CMD "))
    assert "python -m api.startup_checks" in cmd
    assert cmd.index("python -m api.startup_checks") < cmd.index("alembic upgrade head") < cmd.index("uvicorn")
    assert re.search(r"^\s+ENVIRONMENT=production\s*$", text, re.MULTILINE)
    assert "USER appuser" in text


# --------------------------------------------------------------------------- compose


def _service_blocks(text: str) -> dict[str, str]:
    text = "\n" + text.replace("\r\n", "\n")
    services = text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    blocks: dict[str, str] = {}
    current = None
    for line in services.splitlines():
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            blocks[current] = ""
        elif current:
            blocks[current] += line + "\n"
    return blocks


def test_compose_does_not_publish_postgres_by_default():
    blocks = _service_blocks((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "ports:" not in blocks["db"]
    assert "profiles:" not in blocks["db"]
    for name, block in blocks.items():
        if name == "debug-db":
            continue
        assert not re.search(r'^\s*-\s*"?[\d.:]*5432:', block, re.MULTILINE), name


def test_compose_debug_db_profile_binds_loopback_only():
    block = _service_blocks((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["debug-db"]
    assert 'profiles: ["debug-db"]' in block
    ports = re.findall(r'^\s*-\s*"([^"]+)"\s*$', block.split("ports:", 1)[1], re.MULTILINE)
    assert ports and all(p.startswith("127.0.0.1:") for p in ports)


def test_compose_requires_postgres_password_and_has_no_default_credentials():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    blocks = _service_blocks(text)
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in blocks["db"]
    assert "postgres:postgres@" not in text
    assert "POSTGRES_PASSWORD: postgres" not in text
    assert "${POSTGRES_PASSWORD:?" in blocks["backend"]
    assert "ENVIRONMENT: ${ENVIRONMENT:-production}" in blocks["backend"]
    assert "METRICS_TOKEN" in blocks["backend"]


# --------------------------------------------------------------------------- .env.example coverage

_READERS = {"getenv", "get", "read_secret", "_secret", "_env_positive_int"}


def _env_names_read(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            arg = node.args[0]
            if fname in _READERS and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if re.fullmatch(r"[A-Z][A-Z0-9_]+", arg.value):
                    names.add(arg.value)
    return names


def test_env_example_contains_every_variable_read_by_startup_checks_and_config():
    from api import config

    declared = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    read = _env_names_read(ROOT / "api" / "startup_checks.py") | _env_names_read(ROOT / "api" / "config.py")
    read |= {env for env, _default in config.RATE_LIMIT_DEFAULTS.values()}
    read |= set(sc.ENV_VARS_READ)
    read -= {"METRICS_TOKEN_FILE"}  # `_FILE` forms are documented in prose, not as separate entries
    assert read, "scanner found nothing"
    assert {"ENVIRONMENT", "METRICS_TOKEN", "CORS_ALLOWED_ORIGINS", "TRUST_PROXY_HEADERS"} <= read
    assert sorted(read - declared) == []


def test_env_example_placeholders_are_rejected_in_production(monkeypatch):
    """The shipped example file must not be a working production configuration."""
    values = dict(re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    for name in MANAGED:
        monkeypatch.delenv(name, raising=False)
    for name in ("ENVIRONMENT", "JWT_SECRET_KEY", "METRICS_TOKEN", "CORS_ALLOWED_ORIGINS", "DATABASE_URL"):
        monkeypatch.setenv(name, values[name])
    monkeypatch.setenv("OPERATOR_REGISTRATION_KEY", values["OPERATOR_REGISTRATION_KEY"])
    with pytest.raises(StartupConfigError) as info:
        sc.validate_startup_config()
    assert {"JWT_SECRET_KEY", "METRICS_TOKEN", "DATABASE_URL", "OPERATOR_REGISTRATION_KEY"} <= set(info.value.variables)
    monkeypatch.setenv("ENVIRONMENT", "development")
    sc.validate_startup_config()
