"""Shared test setup. Tests use only the offline mock provider and an in-memory
database: no network, no keys, no cost, and no files left behind."""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_engine_from_settings, create_session_factory, create_tables
from app.main import create_app


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "tokenvault_env": "test",
        "tokenvault_provider_mode": "mock",
        "database_url": "sqlite+aiosqlite:///:memory:",
    }
    values.update(overrides)
    # _env_file=None makes sure a developer's real .env file can never affect tests.
    return Settings(_env_file=None, **values)


@pytest.fixture
def build_app() -> Callable[..., FastAPI]:
    def _build(**overrides: Any) -> FastAPI:
        return create_app(make_settings(**overrides))

    return _build


@pytest.fixture
def client(build_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    with TestClient(build_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh, empty in-memory database with all tables created, for each test."""
    engine = create_engine_from_settings(make_settings())
    await create_tables(engine)
    yield create_session_factory(engine)
    await engine.dispose()
    
