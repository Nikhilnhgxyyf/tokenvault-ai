"""Tenant creation. (API-key authentication and admin routes come in a later batch.)"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.services.errors import DuplicateTenantError


class TenantInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


async def create_tenant(session: AsyncSession, data: TenantInput) -> Tenant:
    tenant = Tenant(name=data.name, slug=data.slug)
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateTenantError("A tenant with this slug already exists.") from exc
    return tenant
  
