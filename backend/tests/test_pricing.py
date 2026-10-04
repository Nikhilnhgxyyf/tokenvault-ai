from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.errors import InvalidInputError
from app.services.pricing import (
    PriceInput,
    PriceSnapshot,
    create_price,
    estimate_cost_nano_usd,
    find_price,
    nano_usd_to_usd,
)

# These prices are FAKE test data. They are not any provider's real prices.
INPUT_PRICE = 150_000  # 0.15 USD per million tokens
OUTPUT_PRICE = 600_000  # 0.60 USD per million tokens
CACHED_PRICE = 75_000  # 0.075 USD per million tokens


def snapshot(cached: int | None = CACHED_PRICE, input_price: int = INPUT_PRICE) -> PriceSnapshot:
    return PriceSnapshot(
        price_id=1,
        price_version="test-v1",
        price_source="Test fixture, not a real price list",
        currency="USD",
        input_micro_usd_per_million=input_price,
        output_micro_usd_per_million=OUTPUT_PRICE,
        cached_input_micro_usd_per_million=cached,
    )


def make_price(version: str, effective_from: datetime) -> PriceInput:
    return PriceInput(
        provider="test-provider",
        model="test-model",
        input_micro_usd_per_million=INPUT_PRICE,
        output_micro_usd_per_million=OUTPUT_PRICE,
        cached_input_micro_usd_per_million=CACHED_PRICE,
        price_version=version,
        price_source="Test fixture, not a real price list",
        effective_from=effective_from,
    )


def test_cost_for_plain_input_and_output() -> None:
    cost = estimate_cost_nano_usd(
        prompt_tokens=1000, completion_tokens=500, cached_prompt_tokens=0, price=snapshot()
    )
    # 1000 x 0.15/1e6 + 500 x 0.60/1e6 = 0.00045 USD = 450,000 nano-USD
    assert cost == 450_000
    assert nano_usd_to_usd(cost) == Decimal("0.00045")


def test_cached_tokens_use_the_cached_price() -> None:
    cost = estimate_cost_nano_usd(
        prompt_tokens=1000, completion_tokens=0, cached_prompt_tokens=400, price=snapshot()
    )
    # 600 x 0.15/1e6 + 400 x 0.075/1e6 = 0.00012 USD
    assert cost == 120_000


def test_missing_cached_price_charges_cached_tokens_at_the_input_price() -> None:
    cost = estimate_cost_nano_usd(
        prompt_tokens=1000,
        completion_tokens=0,
        cached_prompt_tokens=400,
        price=snapshot(cached=None),
    )
    assert cost == 150_000


def test_rounding_is_half_up() -> None:
    def cost_at(price: int) -> int:
        return estimate_cost_nano_usd(
            prompt_tokens=1,
            completion_tokens=0,
            cached_prompt_tokens=0,
            price=snapshot(cached=None, input_price=price),
        )

    assert cost_at(1500) == 2  # 1.5 nano-USD rounds up
    assert cost_at(1499) == 1
    assert cost_at(400) == 0


def test_zero_tokens_cost_zero() -> None:
    cost = estimate_cost_nano_usd(
        prompt_tokens=0, completion_tokens=0, cached_prompt_tokens=0, price=snapshot()
    )
    assert cost == 0


def test_invalid_token_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_cost_nano_usd(
            prompt_tokens=10, completion_tokens=0, cached_prompt_tokens=11, price=snapshot()
        )
    with pytest.raises(ValueError):
        estimate_cost_nano_usd(
            prompt_tokens=-1, completion_tokens=0, cached_prompt_tokens=0, price=snapshot()
        )


def test_price_input_requires_a_timezone() -> None:
    with pytest.raises(ValidationError):
        make_price("v1", datetime(2026, 1, 1))


def test_price_input_rejects_negative_prices() -> None:
    with pytest.raises(ValidationError):
        PriceInput(
            provider="p",
            model="m",
            input_micro_usd_per_million=-1,
            output_micro_usd_per_million=1,
            price_version="v1",
            price_source="test",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        )


async def test_find_price_picks_the_version_in_effect(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await create_price(session, make_price("v1", datetime(2026, 1, 1, tzinfo=UTC)))
        await create_price(session, make_price("v2", datetime(2026, 6, 1, tzinfo=UTC)))
        await session.commit()

    async with session_factory() as session:
        early = await find_price(
            session,
            provider="test-provider",
            model="test-model",
            at=datetime(2025, 12, 1, tzinfo=UTC),
        )
        middle = await find_price(
            session,
            provider="test-provider",
            model="test-model",
            at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        late = await find_price(
            session,
            provider="test-provider",
            model="test-model",
            at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        other_model = await find_price(
            session,
            provider="test-provider",
            model="unknown-model",
            at=datetime(2026, 7, 1, tzinfo=UTC),
        )

    assert early is None
    assert middle is not None and middle.price_version == "v1"
    assert late is not None and late.price_version == "v2"
    assert other_model is None


async def test_duplicate_price_version_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await create_price(session, make_price("v1", datetime(2026, 1, 1, tzinfo=UTC)))
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(InvalidInputError):
            await create_price(session, make_price("v1", datetime(2026, 2, 1, tzinfo=UTC)))


async def test_find_price_requires_a_timezone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await find_price(
                session, provider="p", model="m", at=datetime(2026, 1, 1)
  )
          
