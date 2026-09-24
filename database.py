"""
Async PostgreSQL connection and session management using SQLAlchemy + asyncpg.

Usage:
    from database import get_session, init_db
    async with get_session() as session:
        ...
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db_url import DEFAULT_DATABASE_URL, auto_create_tables_enabled, normalize_database_url
from models.db_models import Base

load_dotenv()

# Accepts postgres:// , postgresql:// or postgresql+asyncpg://user:password@host:port/dbname
# (see db_url.py) -- managed-Postgres providers hand out the first two.
DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))

# Async engine with pool settings
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "0").lower() in ("1", "true", "yes"),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async session for the request lifecycle."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables -- DEVELOPMENT ONLY (see db_url.auto_create_tables_enabled).

    In production the schema comes from `alembic upgrade head` (Procfile release
    step / container start), so this is a no-op there.
    """
    if not auto_create_tables_enabled():
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield an async session."""
    async with get_session() as session:
        yield session
