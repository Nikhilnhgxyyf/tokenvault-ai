import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, NamedTuple

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import chat as chat_module
from app.db.session import create_tables, session_scope
from app.models.tenant import Tenant
from app.models.usage import UsageEvent
from app.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderRequest,
    ProviderResponse,
    TokenUsage,
)
from app.services.api_keys import (
    authenticate_api_key,
    create_api_key,
    hash_api_key,
    lookup_api_key,
    revoke_api_key,
)
from app.services.errors import InvalidInputError, UnknownTenantError
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


class InconsistentUsageProvider(Provider):
    """Reports more cached tokens than prompt tokens, which our accounting must refuse."""

    name = "inconsistent"
    capabilities = ProviderCapabilities(streaming=False, tool_calls=False, structured_output=False)

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            provider=self.name,
            model=request.model,
            content="ok",
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=5,
                completion_tokens=1,
                cached_prompt_tokens=9,
                total_tokens=6,
                origin="provider_reported",
            ),
        )


@asynccontextmanager
async def running_gateway(
    build_app: Callable[..., FastAPI], *, with_tables: bool = True, **overrides: Any
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
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


def all_logged_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.getMessage()} {getattr(r, 'fields', '')}" for r in caplog.records)


def auth_failures(caplog: pytest.LogCaptureFixture) -> list[dict[str, str]]:
    return [getattr(r, "fields", {}) for r in caplog.records if r.getMessage() == "auth_failed"]


# ------------------------------------------------ accounting: expected vs unexpected failures


@pytest.mark.parametrize(
    ("error_class", "message"),
    [
        (SQLAlchemyError, "db-detail-1"),
        (InvalidInputError, "rule-detail-2"),
        (UnknownTenantError, "tenant-detail-3"),
        (TimeoutError, "timeout-detail-4"),
        (OSError, "disk-detail-5"),
    ],
)
async def test_expected_accounting_failures_keep_the_response_but_say_failed(
    build_app: Callable[..., FastAPI],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_class: type[Exception],
    message: str,
) -> None:
    async def failing_record_usage(*args: Any, **kwargs: Any) -> None:
        raise error_class(message)

    monkeypatch.setattr("app.api.chat.record_usage", failing_record_usage)
    caplog.set_level(logging.DEBUG)

    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "expected-failure")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 200
    info = response.json()["tokenvault"]
    assert info["accounting"] == "failed"
    assert info["cost_status"] is None
    assert response.headers["x-tokenvault-accounting"] == "failed"
    assert events == []
    assert message not in response.text

    logged = all_logged_text(caplog)
    assert "usage_accounting_failed" in logged
    assert error_class.__name__ in logged
    assert message not in logged  # exception messages are never logged


@pytest.mark.parametrize(
    ("error_class", "message"),
    [
        (RuntimeError, "programming-defect-1"),
        (KeyError, "programming-defect-2"),
        (TypeError, "programming-defect-3"),
        (AttributeError, "programming-defect-4"),
    ],
)
async def test_unexpected_errors_are_not_hidden_as_accounting_failures(
    build_app: Callable[..., FastAPI],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_class: type[Exception],
    message: str,
) -> None:
    async def buggy_record_usage(*args: Any, **kwargs: Any) -> None:
        raise error_class(message)

    monkeypatch.setattr("app.api.chat.record_usage", buggy_record_usage)
    caplog.set_level(logging.DEBUG)

    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "unexpected-failure")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert message not in response.text
    assert events == []
    assert "unhandled_exception" in all_logged_text(caplog)


async def test_a_hung_accounting_step_times_out_instead_of_hanging(
    build_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hung_record_usage(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr("app.api.chat.record_usage", hung_record_usage)
    monkeypatch.setattr(chat_module, "_ACCOUNTING_TIMEOUT_SECONDS", 0.05)

    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "hung-accounting")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 200
    assert response.json()["tokenvault"]["accounting"] == "failed"
    assert events == []


async def test_provider_usage_that_breaks_the_rules_is_reported_as_failed_accounting(
    build_app: Callable[..., FastAPI],
) -> None:
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "bad-usage")
        app.state.provider = InconsistentUsageProvider()
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
        events = await events_for(app, seeded.tenant_id)

    assert response.status_code == 200
    assert response.json()["tokenvault"]["accounting"] == "failed"
    assert events == []


# ------------------------------------------------ authentication: security logging


async def test_every_kind_of_login_failure_gets_the_same_401_and_its_own_log_reason(
    build_app: Callable[..., FastAPI], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    unknown_key = "tv_" + "D" * 43

    async with running_gateway(build_app) as (app, client):
        revoked = await seed_tenant(app, "revoked-log")
        async with session_scope(app.state.session_factory) as session:
            await revoke_api_key(session, tenant_id=revoked.tenant_id, api_key_id=revoked.key_id)

        attempts: list[tuple[str, dict[str, str]]] = [
            ("missing_credentials", {}),
            ("malformed_credentials", {"Authorization": "Basic dXNlcjpwYXNz"}),
            ("malformed_credentials", {"Authorization": "Bearer not-a-key"}),
            ("unknown_key", bearer(unknown_key)),
            ("revoked_key", bearer(revoked.key)),
        ]
        responses = [await client.post(URL, json=BODY, headers=h) for _, h in attempts]

    # The caller cannot tell the failures apart.
    shapes = {
        (
            r.status_code,
            r.json()["error"]["code"],
            r.json()["error"]["message"],
            r.json()["error"]["type"],
            r.headers["www-authenticate"],
        )
        for r in responses
    }
    assert shapes == {
        (401, "invalid_api_key", "Invalid or missing API key.", "authentication_error", "Bearer")
    }

    # The operator can: one structured log entry per attempt, in order.
    failures = auth_failures(caplog)
    assert [f["reason"] for f in failures] == [reason for reason, _ in attempts]
    assert failures[-1]["tenant_id"] == revoked.tenant_id
    assert failures[-1]["api_key_id"] == revoked.key_id

    # And no secret is ever in the logs.
    logged = all_logged_text(caplog)
    assert unknown_key not in logged
    assert revoked.key not in logged
    assert "D" * 43 not in logged
    assert "Authorization" not in logged
    assert "Basic" not in logged


async def test_disabled_tenant_is_logged_with_ids_but_never_the_key(
    build_app: Callable[..., FastAPI], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "disabled-log")
        async with session_scope(app.state.session_factory) as session:
            await session.execute(
                update(Tenant).where(Tenant.id == seeded.tenant_id).values(is_active=False)
            )
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))

    assert response.status_code == 403
    failures = auth_failures(caplog)
    assert len(failures) == 1
    assert failures[0]["reason"] == "tenant_disabled"
    assert failures[0]["tenant_id"] == seeded.tenant_id
    assert seeded.key not in all_logged_text(caplog)


async def test_successful_login_writes_no_auth_failure(
    build_app: Callable[..., FastAPI], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with running_gateway(build_app) as (app, client):
        seeded = await seed_tenant(app, "login-ok")
        response = await client.post(URL, json=BODY, headers=bearer(seeded.key))
    assert response.status_code == 200
    assert auth_failures(caplog) == []


async def test_database_trouble_during_login_logs_only_the_error_type(
    build_app: Callable[..., FastAPI], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    key = "tv_" + "E" * 43
    async with running_gateway(
        build_app,
        with_tables=False,
        database_url="sqlite+aiosqlite:////nonexistent-dir-abc/x.db",
    ) as (_app, client):
        response = await client.post(URL, json=BODY, headers=bearer(key))

    assert response.status_code == 503
    logged = all_logged_text(caplog)
    assert "authentication_backend_error" in logged
    assert "OperationalError" in logged
    assert key not in logged
    assert hash_api_key(key) not in logged  # database messages could contain the hash
    assert "nonexistent" not in logged
    assert auth_failures(caplog) == []  # not a rejected login, so not logged as one


# ------------------------------------------------ the tenant always comes from the key


async def test_a_tenant_id_smuggled_into_user_or_headers_never_changes_the_tenant(
    build_app: Callable[..., FastAPI],
) -> None:
    async with running_gateway(build_app) as (app, client):
        tenant_a = await seed_tenant(app, "smuggle-a")
        tenant_b = await seed_tenant(app, "smuggle-b")
        response = await client.post(
            URL,
            json={**BODY, "user": tenant_b.tenant_id},
            headers={
                **bearer(tenant_a.key),
                "X-Tenant-ID": tenant_b.tenant_id,
                "X-Tenant": tenant_b.tenant_id,
            },
        )
        events_a = await events_for(app, tenant_a.tenant_id)
        events_b = await events_for(app, tenant_b.tenant_id)

    assert response.status_code == 200
    assert len(events_a) == 1
    assert events_b == []


# ------------------------------------------------ key lookup service


async def test_lookup_reports_why_a_key_fails_but_authentication_stays_strict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant = await create_tenant(session, TenantInput(name="lookup", slug="lookup-co"))
        created = await create_api_key(session, tenant_id=tenant.id, name="k")
        await session.commit()

    async with session_factory() as session:
        found = await lookup_api_key(session, created.plaintext)
        assert found is not None
        assert found.tenant_id == tenant.id
        assert found.api_key_id == created.id
        assert found.revoked is False
        assert found.tenant_active is True
        assert await lookup_api_key(session, "tv_" + "F" * 43) is None
        assert await lookup_api_key(session, "garbage") is None

    async with session_factory() as session:
        assert await revoke_api_key(session, tenant_id=tenant.id, api_key_id=created.id)
        await session.commit()

    async with session_factory() as session:
        found = await lookup_api_key(session, created.plaintext)
        assert found is not None
        assert found.revoked is True
        # Authentication itself still refuses a revoked key.
        assert await authenticate_api_key(session, created.plaintext) is None
