from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.types import utc_now
from app.models.usage import UsageEvent
from app.providers.base import ChatMessage, ProviderRequest
from app.providers.mock import MockProvider
from app.services.errors import DuplicateTenantError, UnknownTenantError
from app.services.pricing import PriceInput, create_price
from app.services.tenants import TenantInput, create_tenant
from app.services.usage import (
    UsageRecordInput,
    list_usage_events,
    record_usage,
    summarize_usage,
    usage_input_from_provider_response,
)

WINDOW_START = datetime(2026, 5, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 1, tzinfo=UTC)
EVENT_TIME = datetime(2026, 6, 1, tzinfo=UTC)

# Deliberately WITHOUT a timezone, to prove such values are rejected.
NAIVE_TIME = datetime.fromisoformat("2026-01-01T00:00:00")

# FAKE test price. Not any provider's real price list.
TEST_PRICE = PriceInput(
    provider="test-provider",
    model="test-model",
    input_micro_usd_per_million=150_000,
    output_micro_usd_per_million=600_000,
    cached_input_micro_usd_per_million=75_000,
    price_version="test-v1",
    price_source="Test fixture, not a real price list",
    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
)


@pytest_asyncio.fixture
async def tenant_ids(session_factory: async_sessionmaker[AsyncSession]) -> tuple[str, str]:
    async with session_factory() as session:
        tenant_a = await create_tenant(session, TenantInput(name="Tenant A", slug="tenant-a"))
        tenant_b = await create_tenant(session, TenantInput(name="Tenant B", slug="tenant-b"))
        await create_price(session, TEST_PRICE)
        ids = (tenant_a.id, tenant_b.id)
        await session.commit()
    return ids


def usage_input(tenant_id: str, **overrides: Any) -> UsageRecordInput:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "request_id": "req-00000001",
        "provider": "test-provider",
        "model": "test-model",
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "usage_origin": "provider_reported",
        "occurred_at": EVENT_TIME,
    }
    values.update(overrides)
    return UsageRecordInput(**values)


def raw_event(tenant_id: str, **overrides: Any) -> UsageEvent:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "request_id": "req-00000001",
        "occurred_at": utc_now(),
        "provider": "mock",
        "model": "mock-model",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cached_prompt_tokens": 0,
        "total_tokens": 15,
        "usage_origin": "simulated",
        "cost_status": "unavailable",
    }
    values.update(overrides)
    return UsageEvent(**values)


async def test_provider_reported_usage_gets_an_estimated_cost(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    async with session_factory() as session:
        event = await record_usage(session, usage_input(tenant_ids[0]))
        await session.commit()
    assert event.cost_status == "estimated"
    assert event.estimated_cost_nano_usd == 450_000
    assert event.usage_origin == "provider_reported"
    assert event.price_version == "test-v1"
    assert event.price_source == "Test fixture, not a real price list"
    assert event.currency == "USD"
    assert event.total_tokens == 1500
    assert event.request_id == "req-00000001"
    assert event.tenant_id == tenant_ids[0]


async def test_simulated_usage_is_labeled_simulated(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    async with session_factory() as session:
        event = await record_usage(session, usage_input(tenant_ids[0], usage_origin="simulated"))
    assert event.cost_status == "simulated"
    assert event.estimated_cost_nano_usd == 450_000


async def test_missing_price_means_cost_is_unavailable_not_zero(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    async with session_factory() as session:
        event = await record_usage(session, usage_input(tenant_ids[0], model="model-without-price"))
    assert event.cost_status == "unavailable"
    assert event.estimated_cost_nano_usd is None
    assert event.price_id is None
    assert event.price_version is None


async def test_unknown_tenant_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    async with session_factory() as session:
        with pytest.raises(UnknownTenantError):
            await record_usage(session, usage_input("no-such-tenant"))


def test_invalid_usage_input_is_rejected() -> None:
    with pytest.raises(ValidationError):
        usage_input("t1", cached_prompt_tokens=2000)  # more cached than prompt tokens
    with pytest.raises(ValidationError):
        usage_input("t1", request_id="short")
    with pytest.raises(ValidationError):
        usage_input("t1", prompt_tokens=-1)
    with pytest.raises(ValidationError):
        usage_input("t1", usage_origin="guess")
    with pytest.raises(ValidationError):
        usage_input("t1", occurred_at=NAIVE_TIME)  # no timezone


async def test_duplicate_tenant_slug_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    async with session_factory() as session:
        with pytest.raises(DuplicateTenantError):
            await create_tenant(session, TenantInput(name="Another", slug="tenant-a"))


def test_invalid_tenant_input_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TenantInput(name="Okay", slug="Bad Slug!")
    with pytest.raises(ValidationError):
        TenantInput(name="   ", slug="valid-slug")


async def test_tenants_only_see_their_own_usage(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    tenant_a, tenant_b = tenant_ids
    async with session_factory() as session:
        await record_usage(session, usage_input(tenant_a, request_id="req-a-000001"))
        await record_usage(session, usage_input(tenant_b, request_id="req-b-000001"))
        await record_usage(session, usage_input(tenant_b, request_id="req-b-000002"))
        await session.commit()

    async with session_factory() as session:
        events_a = await list_usage_events(session, tenant_id=tenant_a)
        events_b = await list_usage_events(session, tenant_id=tenant_b)
        nobody = await list_usage_events(session, tenant_id="no-such-tenant")
        summary_a = await summarize_usage(
            session, tenant_id=tenant_a, start=WINDOW_START, end=WINDOW_END
        )
        summary_b = await summarize_usage(
            session, tenant_id=tenant_b, start=WINDOW_START, end=WINDOW_END
        )

    assert {event.request_id for event in events_a} == {"req-a-000001"}
    assert {event.request_id for event in events_b} == {"req-b-000001", "req-b-000002"}
    assert all(event.tenant_id == tenant_a for event in events_a)
    assert nobody == []
    assert sum(row.event_count for row in summary_a) == 1
    assert sum(row.event_count for row in summary_b) == 2


async def test_summary_never_mixes_simulated_and_provider_reported(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    tenant_a = tenant_ids[0]
    async with session_factory() as session:
        await record_usage(session, usage_input(tenant_a, request_id="req-real-0001"))
        await record_usage(
            session, usage_input(tenant_a, request_id="req-fake-0001", usage_origin="simulated")
        )
        await record_usage(
            session,
            usage_input(tenant_a, request_id="req-none-0001", model="model-without-price"),
        )
        await session.commit()

    async with session_factory() as session:
        rows = await summarize_usage(
            session, tenant_id=tenant_a, start=WINDOW_START, end=WINDOW_END
        )

    labels = {(row.model, row.usage_origin, row.cost_status) for row in rows}
    assert labels == {
        ("test-model", "provider_reported", "estimated"),
        ("test-model", "simulated", "simulated"),
        ("model-without-price", "provider_reported", "unavailable"),
    }
    unavailable = next(row for row in rows if row.cost_status == "unavailable")
    assert unavailable.estimated_cost_nano_usd is None
    estimated = next(row for row in rows if row.cost_status == "estimated")
    assert estimated.estimated_cost_nano_usd == 450_000
    assert estimated.prompt_tokens == 1000
    assert estimated.completion_tokens == 500


async def test_summary_respects_the_date_window(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    tenant_a = tenant_ids[0]
    async with session_factory() as session:
        await record_usage(session, usage_input(tenant_a, occurred_at=EVENT_TIME))
        await session.commit()

    async with session_factory() as session:
        inside = await summarize_usage(
            session, tenant_id=tenant_a, start=WINDOW_START, end=WINDOW_END
        )
        before = await summarize_usage(
            session,
            tenant_id=tenant_a,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 2, 1, tzinfo=UTC),
        )
    assert len(inside) == 1
    assert before == []


async def test_summary_and_list_validate_their_arguments(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    tenant_a = tenant_ids[0]
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await summarize_usage(
                session, tenant_id=tenant_a, start=NAIVE_TIME, end=WINDOW_END
            )
        with pytest.raises(ValueError):
            await summarize_usage(
                session, tenant_id=tenant_a, start=WINDOW_END, end=WINDOW_START
            )
        with pytest.raises(ValueError):
            await list_usage_events(session, tenant_id=tenant_a, limit=0)
        with pytest.raises(ValueError):
            await list_usage_events(session, tenant_id=tenant_a, limit=100_000)
        with pytest.raises(ValueError):
            await list_usage_events(session, tenant_id=tenant_a, offset=-1)


async def test_offline_mock_provider_usage_can_be_recorded(
    session_factory: async_sessionmaker[AsyncSession], tenant_ids: tuple[str, str]
) -> None:
    response = await MockProvider().complete(
        ProviderRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="hello there world")],
        )
    )
    data = usage_input_from_provider_response(
        tenant_id=tenant_ids[0], request_id="req-mock-0001", response=response
    )
    async with session_factory() as session:
        event = await record_usage(session, data)
    assert event.provider == "mock"
    assert event.model == "mock-model"
    assert event.usage_origin == "simulated"
    assert event.prompt_tokens == 3
    assert event.total_tokens == response.usage.total_tokens
    # No price was configured for the mock provider, so no cost is invented.
    assert event.cost_status == "unavailable"
    assert event.estimated_cost_nano_usd is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"cached_prompt_tokens": 20},
        {"prompt_tokens": -1},
        {"usage_origin": "guess"},
        {"cost_status": "guess"},
        {"cost_status": "estimated"},  # "estimated" but no cost stored
        {"estimated_cost_nano_usd": 5},  # a cost stored but status "unavailable"
        {"tenant_id": "no-such-tenant"},  # foreign key must be enforced
    ],
)
async def test_database_itself_enforces_the_rules(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_ids: tuple[str, str],
    overrides: dict[str, Any],
) -> None:
    values = {"tenant_id": tenant_ids[0], **overrides}
    tenant_id = values.pop("tenant_id")
    async with session_factory() as session:
        session.add(raw_event(tenant_id, **values))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
        
