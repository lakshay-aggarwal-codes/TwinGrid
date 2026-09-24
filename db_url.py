"""Database URL normalisation, shared by database.py and alembic/env.py.

Managed Postgres providers (Railway, Render, Heroku, Neon...) hand out URLs
that start with ``postgres://`` or ``postgresql://``. SQLAlchemy's async engine
needs an explicit async driver, so both are rewritten to
``postgresql+asyncpg://``. This module is deliberately dependency-free so it
can be imported (and unit-tested) without SQLAlchemy or asyncpg installed.
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/digital_twin"

_ASYNC_SCHEME = "postgresql+asyncpg://"
_REWRITE_PREFIXES = ("postgres://", "postgresql://")


def normalize_database_url(url: str) -> str:
    """Return ``url`` with an asyncpg-compatible scheme and query string.

    * ``postgres://`` / ``postgresql://`` -> ``postgresql+asyncpg://``
    * Any other scheme (already ``postgresql+asyncpg://``, sqlite, ...) is left
      untouched.
    * asyncpg does not understand libpq's ``sslmode=`` query parameter (it
      raises ``TypeError: connect() got an unexpected keyword argument
      'sslmode'``); it is rewritten to asyncpg's equivalent ``ssl=``.
    """
    url = url.strip()
    for prefix in _REWRITE_PREFIXES:
        if url.startswith(prefix):
            url = _ASYNC_SCHEME + url[len(prefix):]
            break
    else:
        return url

    parts = urlsplit(url)
    if "sslmode" in parts.query:
        query = [("ssl" if k == "sslmode" else k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
        url = urlunsplit(parts._replace(query=urlencode(query)))
    return url


_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}


def auto_create_tables_enabled() -> bool:
    """Should the app run ``Base.metadata.create_all`` at startup?

    Development convenience only. In production the schema is owned by Alembic
    (``alembic upgrade head`` is the release step); letting create_all also run
    would build tables outside Alembic's control and make the next
    ``alembic upgrade head`` fail with "relation already exists".

    ``AUTO_CREATE_TABLES`` (true/false) wins if set; otherwise the default is
    ON unless ``ENVIRONMENT=production``.
    """
    raw = os.getenv("AUTO_CREATE_TABLES")
    if raw is not None:
        value = raw.strip().lower()
        if value in _TRUTHY:
            return True
        if value in _FALSY:
            return False
        raise ValueError(f"AUTO_CREATE_TABLES must be true/false, got {raw!r}")
    return os.getenv("ENVIRONMENT", "development").strip().lower() != "production"
