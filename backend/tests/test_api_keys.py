import re

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.services.api_keys import (
    authenticate_api_key,
    create_api_key,
    generate_api_key,
    hash_api_key,
    is_well_formed_api_key,
    revoke_api_key,
)
from app.services.errors import InvalidInputError, UnknownTenantError
from app.services.tenants import TenantInput, create_tenant


async def make_tenant(session: AsyncSession, slug: str) -> str:
    tenant = await create_tenant(session, TenantInput(name=slug, slug=slug))
    return tenant.id


def test_generated_keys_have_the_expected_shape_and_are_unique() -> None:
    first = generate_api_key()
    second = generate_api_key()
    assert re.fullmatch(r"tv_[A-Za-z0-9_-]{43}", first)
    assert first != second
    assert is_well_formed_api_key(first)


def test_malformed_keys_are_not_well_formed() -> None:
    assert not is_well_formed_api_key("")
    assert not is_well_formed_api_key("tv_short")
    assert not is_well_formed_api_key("xx_" + "A" * 43)
    assert not is_well_formed_api_key("tv_" + "A" * 44)
    assert not is_well_formed_api_key("tv_" + "A" * 42 + "!")


def test_hash_is_stable_and_not_the_key() -> None:
    key = generate_api_key()
    assert hash_api_key(key) == hash_api_key(key)
    assert re.fullmatch(r"[0-9a-f]{64}", hash_api_key(key))
    assert key not in hash_api_key(key)


async def test_only_the_hash_is_stored_never_the_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant_id = await make_tenant(session, "key-store")
        created = await create_api_key(session, tenant_id=tenant_id, name="  Production key  ")
        await session.commit()

    async with session_factory() as session:
        row = (await session.execute(select(ApiKey))).scalar_one()

    assert row.name == "Production key"
    assert row.key_hash == hash_api_key(created.plaintext)
    assert row.key_prefix == created.plaintext[:9]
    stored_text = f"{row.id} {row.tenant_id} {row.name} {row.key_prefix} {row.key_hash}"
    assert created.plaintext not in stored_text
    assert created.plaintext not in repr(created)


async def test_valid_key_identifies_its_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant_id = await make_tenant(session, "auth-ok")
        created = await create_api_key(session, tenant_id=tenant_id, name="k")
        await session.commit()

    async with session_factory() as session:
        principal = await authenticate_api_key(session, created.plaintext)

    assert principal is not None
    assert principal.tenant_id == tenant_id
    assert principal.api_key_id == created.id
    assert principal.tenant_active is True


async def test_unknown_and_malformed_keys_authenticate_as_nobody(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await authenticate_api_key(session, "tv_" + "A" * 43) is None
        assert await authenticate_api_key(session, "garbage") is None
        assert await authenticate_api_key(session, "") is None


async def test_revoked_key_stops_working_and_revocation_is_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant_a = await make_tenant(session, "revoke-a")
        tenant_b = await make_tenant(session, "revoke-b")
        created = await create_api_key(session, tenant_id=tenant_a, name="k")
        await session.commit()

    async with session_factory() as session:
        # Another tenant cannot revoke this key.
        assert await revoke_api_key(session, tenant_id=tenant_b, api_key_id=created.id) is False
        await session.commit()
    async with session_factory() as session:
        assert await authenticate_api_key(session, created.plaintext) is not None

    async with session_factory() as session:
        assert await revoke_api_key(session, tenant_id=tenant_a, api_key_id=created.id) is True
        await session.commit()
    async with session_factory() as session:
        assert await authenticate_api_key(session, created.plaintext) is None
        # Revoking twice changes nothing.
        assert await revoke_api_key(session, tenant_id=tenant_a, api_key_id=created.id) is False


async def test_inactive_tenant_is_flagged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant_id = await make_tenant(session, "inactive-co")
        created = await create_api_key(session, tenant_id=tenant_id, name="k")
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        tenant.is_active = False
        await session.commit()

    async with session_factory() as session:
        principal = await authenticate_api_key(session, created.plaintext)
    assert principal is not None
    assert principal.tenant_active is False


async def test_creating_a_key_validates_its_inputs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant_id = await make_tenant(session, "validate-keys")
        with pytest.raises(UnknownTenantError):
            await create_api_key(session, tenant_id="no-such-tenant", name="k")
        with pytest.raises(InvalidInputError):
            await create_api_key(session, tenant_id=tenant_id, name="   ")
        with pytest.raises(InvalidInputError):
            await create_api_key(session, tenant_id=tenant_id, name="x" * 101)
            
