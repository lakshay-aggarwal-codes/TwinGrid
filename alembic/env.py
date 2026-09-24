"""
Alembic env.py: async migrations using SQLAlchemy + asyncpg.

Uses DATABASE_URL from environment. Run: alembic upgrade head (from project root).
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from db_url import DEFAULT_DATABASE_URL, normalize_database_url
from models.db_models import Base

load_dotenv()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Same normalisation as database.py: postgres:// and postgresql:// become
# postgresql+asyncpg:// so `alembic upgrade head` works against the URL a
# managed-Postgres provider hands out.
database_url = normalize_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))
sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)  # offline mode only (no driver needed)

# configparser treats "%" as interpolation syntax, so a percent-encoded
# password (e.g. "p%40ss") must be escaped as "%%" before set_main_option().
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
