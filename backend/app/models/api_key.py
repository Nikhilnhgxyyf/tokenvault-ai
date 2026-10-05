"""API keys for gateway clients.

Only a one-way hash of each key is stored, never the key itself. The short prefix is
kept so a person can tell keys apart in a list. A key is revoked when revoked_at is set.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utc_now


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        Index("ix_api_keys_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id", name="fk_api_keys_tenant_id_tenants"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
  
