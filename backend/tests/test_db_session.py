from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import check_database, create_engine_from_settings, session_scope
from app.db.types import UTCDateTime
from app.models.tenant import Tenant


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "tokenvault_env": "test",
        "database_url": "sqlite+aiosqlite:///:memory:",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def test_engine_can_run_a_query() -> None:
    engine = create_engine_from_settings(make_settings())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()


async def test_foreign_keys_are_switched_on() -> None:
    engine = create_engine_from_settings(make_settings())
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("PRAGMA foreign_keys"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()


async def test_check_database_is_true_for_a_working_database() -> None:
    engine = create_engine_from_settings(make_settings())
    try:
        assert await check_database(engine) is True
    finally:
        await engine.dispose()


async def test_check_database_is_false_for_an_unreachable_database() -> None:
    settings = make_settings(database_url="sqlite+aiosqlite:////nonexistent-dir-abc/x.db")
    engine = create_engine_from_settings(settings)
    try:
        assert await check_database(engine) is False
    finally:
        await engine.dispose()


async def test_session_scope_commits_on_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        session.add(Tenant(name="Commit Co", slug="scope-commit"))

    async with session_factory() as session:
        found = (
            await session.execute(select(Tenant).where(Tenant.slug == "scope-commit"))
        ).scalar_one_or_none()
    assert found is not None


async def test_session_scope_rolls_back_on_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError):
        async with session_scope(session_factory) as session:
            session.add(Tenant(name="Rollback Co", slug="scope-rollback"))
            await session.flush()
            raise RuntimeError("boom")

    async with session_factory() as session:
        found = (
            await session.execute(select(Tenant).where(Tenant.slug == "scope-rollback"))
        ).scalar_one_or_none()
    assert found is None


async def test_timestamps_come_back_timezone_aware(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        session.add(Tenant(name="Clock Co", slug="clock-co"))

    async with session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "clock-co"))
        ).scalar_one()
    assert tenant.created_at.tzinfo is not None
    assert tenant.created_at.utcoffset() == UTC.utcoffset(None)


def test_naive_datetimes_are_rejected() -> None:
    column_type = UTCDateTime()
    with pytest.raises(ValueError):
        column_type.process_bind_param(datetime(2026, 1, 1), None)


def test_naive_datetimes_from_the_database_are_treated_as_utc() -> None:
    column_type = UTCDateTime()
    result = column_type.process_result_value(datetime(2026, 1, 1, 12, 0), None)
    assert result == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_postgres_urls_are_rejected_for_now() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql://user:pw@host/db")


def test_tables_are_only_auto_created_in_local_development() -> None:
    assert Settings(_env_file=None).should_auto_create_tables is True
    assert Settings(_env_file=None, tokenvault_env="test").should_auto_create_tables is False
    assert Settings(_env_file=None, database_auto_create=False).should_auto_create_tables is False


def test_ready_reports_database_ok(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_ready_is_503_when_the_database_is_unreachable(
    build_app: Callable[..., FastAPI],
) -> None:
    app = build_app(database_url="sqlite+aiosqlite:////nonexistent-dir-abc/x.db")
    with TestClient(app, raise_server_exceptions=False) as broken_client:
        response = broken_client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "unavailable"
    assert body["provider"] == "mock"
    assert "nonexistent" not in response.text
  
