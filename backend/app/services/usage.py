"""Usage accounting: record usage events and read tenant-scoped summaries.

Every read function requires a tenant_id and filters by it. Simulated and
provider-reported usage are never added together: summaries are grouped by origin
and cost status.
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.types import ensure_aware_utc, utc_now
from app.models.tenant import Tenant
from app.models.usage import UsageEvent
from app.providers.base import DataOrigin, ProviderResponse
from app.services.errors import InvalidInputError, UnknownTenantError
from app.services.pricing import estimate_cost_nano_usd, find_price

_MAX_TOKENS = 1_000_000_000
_MAX_LIST_LIMIT = 1000


class UsageRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=36)
    request_id: str = Field(pattern=r"^[A-Za-z0-9._-]{8,64}$")
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    prompt_tokens: int = Field(ge=0, le=_MAX_TOKENS)
    completion_tokens: int = Field(ge=0, le=_MAX_TOKENS)
    cached_prompt_tokens: int = Field(default=0, ge=0, le=_MAX_TOKENS)
    total_tokens: int | None = Field(default=None, ge=0, le=2 * _MAX_TOKENS)
    usage_origin: DataOrigin
    occurred_at: datetime | None = None

    @field_validator("occurred_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _cached_tokens_within_prompt(self) -> "UsageRecordInput":
        if self.cached_prompt_tokens > self.prompt_tokens:
            raise ValueError("cached_prompt_tokens cannot exceed prompt_tokens.")
        return self


def usage_input_from_provider_response(
    *, tenant_id: str, request_id: str, response: ProviderResponse
) -> UsageRecordInput:
    """Turn a provider response into a usage record, keeping its origin label."""
    usage = response.usage
    return UsageRecordInput(
        tenant_id=tenant_id,
        request_id=request_id,
        provider=response.provider,
        model=response.model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_prompt_tokens=usage.cached_prompt_tokens,
        total_tokens=usage.total_tokens,
        usage_origin=usage.origin,
    )


async def record_usage(session: AsyncSession, data: UsageRecordInput) -> UsageEvent:
    """Store one usage event for an existing tenant, with an estimated cost if a price exists.

    cost_status rules:
    - no configured price in effect          -> "unavailable" (no cost stored)
    - price found, provider-reported tokens  -> "estimated"
    - price found, simulated tokens          -> "simulated"
    """
    tenant_id = (
        await session.execute(select(Tenant.id).where(Tenant.id == data.tenant_id))
    ).scalar_one_or_none()
    if tenant_id is None:
        raise UnknownTenantError("Tenant does not exist.")

    occurred_at = data.occurred_at or utc_now()
    price = await find_price(
        session, provider=data.provider, model=data.model, at=occurred_at
    )

    if price is None:
        cost: int | None = None
        cost_status = "unavailable"
    else:
        cost = estimate_cost_nano_usd(
            prompt_tokens=data.prompt_tokens,
            completion_tokens=data.completion_tokens,
            cached_prompt_tokens=data.cached_prompt_tokens,
            price=price,
        )
        cost_status = "estimated" if data.usage_origin == "provider_reported" else "simulated"

    total_tokens = (
        data.total_tokens
        if data.total_tokens is not None
        else data.prompt_tokens + data.completion_tokens
    )
    event = UsageEvent(
        tenant_id=data.tenant_id,
        request_id=data.request_id,
        occurred_at=occurred_at,
        provider=data.provider,
        model=data.model,
        prompt_tokens=data.prompt_tokens,
        completion_tokens=data.completion_tokens,
        cached_prompt_tokens=data.cached_prompt_tokens,
        total_tokens=total_tokens,
        usage_origin=data.usage_origin,
        price_id=price.price_id if price else None,
        price_version=price.price_version if price else None,
        price_source=price.price_source if price else None,
        currency=price.currency if price else None,
        estimated_cost_nano_usd=cost,
        cost_status=cost_status,
    )
    session.add(event)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise InvalidInputError("The usage event breaks a database rule.") from exc
    return event


@dataclass(frozen=True)
class UsageSummaryRow:
    provider: str
    model: str
    usage_origin: str
    cost_status: str
    event_count: int
    prompt_tokens: int
    completion_tokens: int
    cached_prompt_tokens: int
    total_tokens: int
    estimated_cost_nano_usd: int | None


async def summarize_usage(
    session: AsyncSession, *, tenant_id: str, start: datetime, end: datetime
) -> list[UsageSummaryRow]:
    """Totals for one tenant in [start, end), grouped so labels are never mixed."""
    start_utc = ensure_aware_utc(start)
    end_utc = ensure_aware_utc(end)
    if start_utc >= end_utc:
        raise ValueError("start must be earlier than end.")

    statement = (
        select(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.usage_origin,
            UsageEvent.cost_status,
            func.count(UsageEvent.id),
            func.sum(UsageEvent.prompt_tokens),
            func.sum(UsageEvent.completion_tokens),
            func.sum(UsageEvent.cached_prompt_tokens),
            func.sum(UsageEvent.total_tokens),
            func.sum(UsageEvent.estimated_cost_nano_usd),
        )
        .where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.occurred_at >= start_utc,
            UsageEvent.occurred_at < end_utc,
        )
        .group_by(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.usage_origin,
            UsageEvent.cost_status,
        )
        .order_by(
            UsageEvent.provider,
            UsageEvent.model,
            UsageEvent.usage_origin,
            UsageEvent.cost_status,
        )
    )
    rows = (await session.execute(statement)).all()
    return [
        UsageSummaryRow(
            provider=row[0],
            model=row[1],
            usage_origin=row[2],
            cost_status=row[3],
            event_count=int(row[4]),
            prompt_tokens=int(row[5]),
            completion_tokens=int(row[6]),
            cached_prompt_tokens=int(row[7]),
            total_tokens=int(row[8]),
            estimated_cost_nano_usd=None if row[9] is None else int(row[9]),
        )
        for row in rows
    ]


async def list_usage_events(
    session: AsyncSession, *, tenant_id: str, limit: int = 100, offset: int = 0
) -> list[UsageEvent]:
    """Newest-first usage events for one tenant."""
    if not 1 <= limit <= _MAX_LIST_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}.")
    if offset < 0:
        raise ValueError("offset must not be negative.")
    statement = (
        select(UsageEvent)
        .where(UsageEvent.tenant_id == tenant_id)
        .order_by(UsageEvent.occurred_at.desc(), UsageEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(statement)).scalars().all())
  
