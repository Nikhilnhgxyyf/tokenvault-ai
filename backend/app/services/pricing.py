"""Price lookup and cost estimation.

Units:
- Prices: micro-USD per 1,000,000 tokens (integer). $0.15 per million = 150000.
- Costs: nano-USD (1e-9 USD, integer).

cost_nano_usd = tokens x price / 1000 (rounded half up), so no floating point is used.
Prices are entered by an operator with a stated source. This code never invents prices.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.types import ensure_aware_utc
from app.models.pricing import ModelPrice
from app.services.errors import InvalidInputError

_MAX_PRICE = 10**12


@dataclass(frozen=True)
class PriceSnapshot:
    price_id: int
    price_version: str
    price_source: str
    currency: str
    input_micro_usd_per_million: int
    output_micro_usd_per_million: int
    cached_input_micro_usd_per_million: int | None


class PriceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    input_micro_usd_per_million: int = Field(ge=0, le=_MAX_PRICE)
    output_micro_usd_per_million: int = Field(ge=0, le=_MAX_PRICE)
    cached_input_micro_usd_per_million: int | None = Field(default=None, ge=0, le=_MAX_PRICE)
    currency: Literal["USD"] = "USD"
    price_version: str = Field(min_length=1, max_length=64)
    price_source: str = Field(min_length=1, max_length=500)
    effective_from: datetime

    @field_validator("effective_from")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


def estimate_cost_nano_usd(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cached_prompt_tokens: int,
    price: PriceSnapshot,
) -> int:
    """Estimate cost in nano-USD from token counts and a configured price.

    prompt_tokens includes cached tokens. If no cached-input price is configured, cached
    tokens are charged at the normal input price (this never understates the estimate).
    """
    if prompt_tokens < 0 or completion_tokens < 0 or cached_prompt_tokens < 0:
        raise ValueError("Token counts must not be negative.")
    if cached_prompt_tokens > prompt_tokens:
        raise ValueError("Cached tokens cannot exceed prompt tokens.")

    cached_price = price.cached_input_micro_usd_per_million
    if cached_price is None:
        cached_price = price.input_micro_usd_per_million

    uncached_prompt_tokens = prompt_tokens - cached_prompt_tokens
    numerator = (
        uncached_prompt_tokens * price.input_micro_usd_per_million
        + cached_prompt_tokens * cached_price
        + completion_tokens * price.output_micro_usd_per_million
    )
    return (numerator + 500) // 1000


def nano_usd_to_usd(nano_usd: int) -> Decimal:
    """Convert nano-USD to a Decimal amount in USD for display."""
    return Decimal(nano_usd).scaleb(-9)


async def create_price(session: AsyncSession, data: PriceInput) -> ModelPrice:
    price = ModelPrice(
        provider=data.provider,
        model=data.model,
        input_micro_usd_per_million=data.input_micro_usd_per_million,
        output_micro_usd_per_million=data.output_micro_usd_per_million,
        cached_input_micro_usd_per_million=data.cached_input_micro_usd_per_million,
        currency=data.currency,
        price_version=data.price_version,
        price_source=data.price_source,
        effective_from=data.effective_from,
    )
    session.add(price)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise InvalidInputError(
            "This price conflicts with an existing price version or breaks a rule."
        ) from exc
    return price


async def find_price(
    session: AsyncSession, *, provider: str, model: str, at: datetime
) -> PriceSnapshot | None:
    """Return the newest price already in effect at `at`, or None if none is configured."""
    moment = ensure_aware_utc(at)
    statement = (
        select(ModelPrice)
        .where(
            ModelPrice.provider == provider,
            ModelPrice.model == model,
            ModelPrice.effective_from <= moment,
        )
        .order_by(ModelPrice.effective_from.desc(), ModelPrice.id.desc())
        .limit(1)
    )
    row = (await session.execute(statement)).scalar_one_or_none()
    if row is None:
        return None
    return PriceSnapshot(
        price_id=row.id,
        price_version=row.price_version,
        price_source=row.price_source,
        currency=row.currency,
        input_micro_usd_per_million=row.input_micro_usd_per_million,
        output_micro_usd_per_million=row.output_micro_usd_per_million,
        cached_input_micro_usd_per_million=row.cached_input_micro_usd_per_million,
    )
  
