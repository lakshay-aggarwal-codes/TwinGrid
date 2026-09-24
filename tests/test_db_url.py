"""DATABASE_URL normalisation (shared by database.py and alembic/env.py)."""

import pytest

from db_url import DEFAULT_DATABASE_URL, auto_create_tables_enabled, normalize_database_url


class TestNormalizeDatabaseUrl:
    @pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
    def test_plain_postgres_schemes_get_asyncpg(self, scheme):
        assert (
            normalize_database_url(f"{scheme}://u:p@host:5432/db")
            == "postgresql+asyncpg://u:p@host:5432/db"
        )

    def test_already_async_url_is_untouched(self):
        url = "postgresql+asyncpg://u:p@host/db"
        assert normalize_database_url(url) == url

    def test_default_is_already_normalised(self):
        assert normalize_database_url(DEFAULT_DATABASE_URL) == DEFAULT_DATABASE_URL

    def test_other_schemes_are_left_alone(self):
        assert normalize_database_url("sqlite+aiosqlite:///x.db") == "sqlite+aiosqlite:///x.db"

    def test_whitespace_is_stripped(self):
        assert normalize_database_url("  postgres://u:p@h/db\n") == "postgresql+asyncpg://u:p@h/db"

    def test_sslmode_is_translated_for_asyncpg(self):
        out = normalize_database_url("postgres://u:p@h/db?sslmode=require&application_name=x")
        assert out == "postgresql+asyncpg://u:p@h/db?ssl=require&application_name=x"

    def test_percent_encoded_password_is_preserved(self):
        assert normalize_database_url("postgres://u:p%40ss@h/db") == "postgresql+asyncpg://u:p%40ss@h/db"


class TestAutoCreateTables:
    """create_all is dev-only; production schema comes from `alembic upgrade head`."""

    def test_on_by_default_in_development(self, monkeypatch):
        monkeypatch.delenv("AUTO_CREATE_TABLES", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert auto_create_tables_enabled() is True

    def test_off_by_default_in_production(self, monkeypatch):
        monkeypatch.delenv("AUTO_CREATE_TABLES", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert auto_create_tables_enabled() is False

    @pytest.mark.parametrize("value,expected", [("true", True), ("1", True), ("false", False), ("0", False), ("", False)])
    def test_explicit_flag_wins_over_environment(self, monkeypatch, value, expected):
        monkeypatch.setenv("ENVIRONMENT", "production" if expected else "development")
        monkeypatch.setenv("AUTO_CREATE_TABLES", value)
        assert auto_create_tables_enabled() is expected

    def test_garbage_value_is_an_error_not_silently_false(self, monkeypatch):
        monkeypatch.setenv("AUTO_CREATE_TABLES", "maybe")
        with pytest.raises(ValueError):
            auto_create_tables_enabled()
