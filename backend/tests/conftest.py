"""Shared test setup. Tests use only the offline mock provider: no network, no keys, no cost."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "tokenvault_env": "test",
        "tokenvault_provider_mode": "mock",
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
      
