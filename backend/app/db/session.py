"""Database engine and session management.

- One engine per application, created from settings.
- Sessions are short-lived and managed with `session_scope`, which commits on
  success and rolls back on any error.
- Database error details are logged by type only, never returned to callers.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base

logger = logging.getLogger("tokenvault.db")


def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    # SQLite ignores foreign keys unless this is switched on for every connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    """Create the async engine. No connection is opened until it is first used."""
    url = make_url(settings.database_url)
    options: dict[str, Any] = {}
    if url.database in (None, "", ":memory:"):
        # An in-memory SQLite database only exists on one connection, so share it.
        options["poolclass"] = StaticPool
    engine = create_async_engine(settings.database_url, **options)
    # Only SQLite is supported in this version (enforced by Settings validation).
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Run a unit of work: commit if it succeeds, roll back if anything raises."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables(engine: AsyncEngine) -> None:
    """Create any missing tables directly from the models.

    Used for local development and tests only. Real deployments use Alembic migrations.
    """
    from app import models  # noqa: F401  (importing registers the tables)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def check_database(engine: AsyncEngine, timeout_seconds: float = 3.0) -> bool:
    """Return True if the database answers a trivial query. Never raises."""
    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, TimeoutError, OSError) as exc:
        logger.warning(
            "database_check_failed", extra={"fields": {"error_type": type(exc).__name__}}
        )
        return False
      
