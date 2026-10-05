import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, NamedTuple

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import create_tables, session_scope
from app.models.tenant import Tenant
from app.models.usage import UsageEvent
from app.providers.base import Provider, ProviderCapabilities, ProviderRequest, ProviderResponse
from app.providers.mock import MockProvider
from app.services.api_keys import create_api_key, revoke_api_key
from app.services.pricing import PriceInput, create_price
from app.services.tenants import TenantInput, create_tenant
from app.services.usage import list_usage_events

URL = "/v1/chat/completions"
BODY: dict[str, Any] = {
    "model": "mock-model",
    "messages": [{"role": "user", "content": "hello there world"}],
}


class Seeded(NamedTuple):
    tenant_id: str
    key: str
    key_id: str


class SlowProvider(Provider):
    name = "slow"
    capabilities = ProviderCapabilities(streaming=False, tool_calls=False, structured_output=False)

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        await asyncio.sleep(5)
        return await MockProvider().complete(request)


@asynccontextmanager
async def running_gateway(
    build_app: Callable[..., FastAPI], *, with_tables: bool = True, **overrides: Any
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """The real app, an in-memory database, and an in-process HTTP client (same event loop)."""
    app = build_app(**overrides)
    if with_tables:
        await create_tables(app.state.engine)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield app, client
    finally:
        await app.state.engine.dispose()


async def seed_tenant(app: FastAPI, slug: str) -> Seeded:
    async with session_scope(app.state.session_factory) as session:
        tenant = await create_tenant(session, TenantInput(name=slug, slug=slug))
        created = await create_api_key(session, tenant_id=tenant.id, name="test key")
    return Seeded(tenant_id=tenant.id, key=created.plaintext, key_id=created.id)


async def events_for(app: FastAPI, tenant_id: str) -> list[UsageEvent]:
    async with app.state.session_factory() as session:
        return await list_usage_events(session, tenant_id=tenant_id)


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------- success and accounting


async def test_successful_request_is_answered_and_accounted(
    build_app: Callable[..., FastAPI],
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "acme")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "mock-model"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"].startswith("[mock-response")
    assert body["usage"]["prompt_tokens"] == 3

    info = body["tokenvault"]
    assert info["provider"] == "mock"
    assert info["usage_origin"] == "simulated"
    assert info["accounting"] == "recorded"
    assert info["cost_status"] == "unavailable"
    assert info["estimated_cost_nano_usd"] is None
    assert "simulated" in info["notice"]
    assert info["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-tokenvault-usage-origin"] == "simulated"
    assert response.headers["x-tokenvault-accounting"] == "recorded"

    assert len(events) == 1
    event = events[0]
    assert event.tenant_id == seeded.tenant_id
    assert event.request_id == info["request_id"]
    assert event.provider == "mock"
    assert event.model == "mock-model"
    assert event.usage_origin == "simulated"
    assert event.prompt_tokens == body["usage"]["prompt_tokens"]
    assert event.completion_tokens == body["usage"]["completion_tokens"]
    assert event.cost_status == "unavailable"
    assert event.estimated_cost_nano_usd is None


async def test_configured_price_gives_a_simulated_cost_never_a_real_one(
    build_app: Callable[..., FastAPI],
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "priced")
        async with session_scope(app.state.session_factory) as session:
            # FAKE test price, not any provider's real price.
            await create_price(
                session,
                PriceInput(
                    provider="mock",
                    model="mock-model",
                    input_micro_usd_per_million=150_000,
                    output_micro_usd_per_million=600_000,
                    price_version="test-v1",
                    price_source="Test fixture, not a real price list",
                    effective_from=datetime(2000, 1, 1, tzinfo=UTC),
                ),
            )
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))

    assert response.status_code == 200
    info = response.json()["tokenvault"]
    assert info["cost_status"] == "simulated"
    # 3 prompt tokens x 0.15 + 2 completion tokens x 0.60 (USD per million) = 1650 nano-USD
    assert info["estimated_cost_nano_usd"] == 1650


@pytest.mark.parametrize(
    "extra",
    [{"stream": False}, {"n": 1}, {"user": "end-user-1"}, {"temperature": 0.2, "max_tokens": 50}],
)
async def test_supported_optional_fields_are_accepted(
    build_app: Callable[..., FastAPI], extra: dict[str, Any]
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "optional-ok")
        response = await client.post(URL, json={**BODY, **extra}, headers=bearer(seeded.key))
    assert response.status_code == 200


# ---------------------------------------------------------------- authentication


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not-a-real-key"},
        {"Authorization": "Bearer tv_" + "A" * 43},
    ],
)
async def test_missing_or_bad_keys_are_refused(
    build_app: Callable[..., FastAPI], headers: dict[str, str]
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "locked")
        response = await client.post(URL, json=BODY, headers=headers)
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert response.headers["www-authenticate"] == "Bearer"
    assert "A" * 43 not in response.text
    assert events == []


async def test_revoked_key_is_refused(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "revoked-co")
        async with session_scope(app.state.session_factory) as session:
            assert await revoke_api_key(
                session, tenant_id=seeded.tenant_id, api_key_id=seeded.key_id
            )
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert events == []


async def test_disabled_tenant_is_refused(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "disabled-co")
        async with session_scope(app.state.session_factory) as session:
            await session.execute(
                update(Tenant).where(Tenant.id == seeded.tenant_id).values(is_active=False)
            )
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_disabled"
    assert events == []


async def test_database_outage_during_login_is_503_not_401(
    build_app: Callable[..., FastAPI],
) -> None:
    async with running_gateway(
        build_app,
        with_tables=False,
        database_url="sqlite+aiosqlite:////nonexistent-dir-abc/x.db",
    ) as (_app, client):
        response = await client.post(URL, json=BODY, headers=bearer("tv_" + "B" * 43))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"
    assert "nonexistent" not in response.text


# ---------------------------------------------------------------- tenant isolation


async def test_tenant_comes_only_from_the_key(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app) as (app, client):
        tenant_a = await seed_tenant(app, "tenant-a")
        tenant_b = await seed_tenant(app, "tenant-b")

        # Tenant A's key, while claiming to be tenant B in a header.
        as_a = await client.post(
            URL,
            json=BODY,
            headers={**bearer(tenant_a.key), "X-Tenant-ID": tenant_b.tenant_id},
        )
        as_b = await client.post(URL, json=BODY, headers=bearer(tenant_b.key))
        events_a = await events_for(app, tenant_a.tenant_id)
        events_b = await events_for(app, tenant_b.tenant_id)

    assert as_a.status_code == 200
    assert as_b.status_code == 200
    assert len(events_a) == 1
    assert len(events_b) == 1
    assert events_a[0].request_id == as_a.json()["tokenvault"]["request_id"]
    assert events_b[0].request_id == as_b.json()["tokenvault"]["request_id"]


async def test_a_tenant_field_in_the_body_is_rejected(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app) as (app, client):
        tenant_a = await seed_tenant(app, "body-a")
        tenant_b = await seed_tenant(app, "body-b")
        response = await client.post(
            URL,
            json={**BODY, "tenant_id": tenant_b.tenant_id},
            headers=bearer(tenant_a.key),
        )
        events_a = await events_for(app, tenant_a.tenant_id)
        events_b = await events_for(app, tenant_b.tenant_id)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert events_a == []
    assert events_b == []


# ---------------------------------------------------------------- invalid requests


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"model": "mock-model", "messages": []},
        {"model": "mock-model", "messages": [{"role": "tool", "content": "x"}]},
        {"messages": [{"role": "user", "content": "hi"}]},
        {**BODY, "temperature": 5},
        {"model": "bad model!", "messages": [{"role": "user", "content": "hi"}]},
        {
            "model": "mock-model",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        },
        {**BODY, "foo": 1},
    ],
)
async def test_invalid_bodies_get_a_consistent_422(
    build_app: Callable[..., FastAPI], payload: dict[str, Any]
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "invalid-body")
        response = await client.post(URL, json=payload, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert events == []


async def test_validation_errors_never_echo_the_prompt(build_app: Callable[..., FastAPI]) -> None:
    payload = {"model": "mock-model", "messages": [{"role": "hacker", "content": "SECRET-PROMPT"}]}
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "no-echo")
        response = await client.post(URL, json=payload, headers=bearer(seeded.key))
    assert response.status_code == 422
    assert "SECRET-PROMPT" not in response.text


async def test_non_json_body_is_a_422(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "not-json")
        response = await client.post(
            URL,
            content=b"this is not json",
            headers={**bearer(seeded.key), "Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


async def test_wrong_content_type_is_a_415(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "wrong-type")
        response = await client.post(
            URL,
            content=json.dumps(BODY),
            headers={**bearer(seeded.key), "Content-Type": "text/plain"},
        )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.parametrize(
    "extra",
    [
        {"stream": True},
        {"tools": []},
        {"response_format": {"type": "json_object"}},
        {"n": 2},
        {"top_p": 0.5},
    ],
)
async def test_unsupported_features_are_refused_not_ignored(
    build_app: Callable[..., FastAPI], extra: dict[str, Any]
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "unsupported")
        response = await client.post(URL, json={**BODY, **extra}, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_feature"
    assert events == []


async def test_oversized_body_is_a_413(build_app: Callable[..., FastAPI]) -> None:
    big = {"model": "mock-model", "messages": [{"role": "user", "content": "x" * 5000}]}
    async with running_gateway(build_app, max_request_body_bytes=2048) as (app, client):
        seeded = await seed_tenant(app, "too-big")
        response = await client.post(URL, json=big, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert events == []


# ---------------------------------------------------------------- provider and accounting failures


async def test_slow_provider_times_out_with_a_504(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app, upstream_timeout_seconds=0.05) as (app, client):
        seeded = await seed_tenant(app, "slow-co")
        app.state.provider = SlowProvider()
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
    assert events == []


async def test_provider_failure_is_a_502_without_details(
    build_app: Callable[..., FastAPI],
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "failing-co")
        app.state.provider = MockProvider(fail_mode="error")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"
    assert "Simulated upstream failure" not in response.text
    assert events == []


async def test_missing_provider_is_a_503(build_app: Callable[..., FastAPI]) -> None:
    async with running_gateway(build_app, tokenvault_provider_mode="live") as (app, client):
        seeded = await seed_tenant(app, "no-provider")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"


async def test_accounting_failure_is_reported_never_hidden(
    build_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_record_usage(*args: Any, **kwargs: Any) -> None:
        raise SQLAlchemyError("secret-db-detail")

    monkeypatch.setattr("app.api.chat.record_usage", failing_record_usage)

    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "accounting-down")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 200
    info = response.json()["tokenvault"]
    assert info["accounting"] == "failed"
    assert info["cost_status"] is None
    assert info["estimated_cost_nano_usd"] is None
    assert "not in usage reports" in info["notice"]
    assert response.headers["x-tokenvault-accounting"] == "failed"
    assert "secret-db-detail" not in response.text
    assert events == []


# ---------------------------------------------------------------- logging and settings


async def test_logs_never_contain_api_keys_or_prompts(
    build_app: Callable[..., FastAPI], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret_prompt = "TOP-SECRET-PROMPT-XYZ"
    bad_key = "tv_" + "C" * 43
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "log-check")
        await client.post(
            URL,
            json={"model": "mock-model", "messages": [{"role": "user", "content": secret_prompt}]},
            headers=bearer(seeded.key),
        )
        await client.post(URL, json=BODY, headers=bearer(bad_key))

    logged = "\n".join(f"{r.getMessage()} {getattr(r, 'fields', '')}" for r in caplog.records)
    assert "request_completed" in logged  # proves the logs were really captured
    assert seeded.key not in logged
    assert bad_key not in logged
    assert secret_prompt not in logged


def test_timeout_setting_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, upstream_timeout_seconds=0)
      
