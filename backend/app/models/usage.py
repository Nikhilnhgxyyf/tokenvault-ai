"""Durable usage events: one row per model call.

Labels (never mixed together):
- usage_origin: "provider_reported" (numbers returned by a provider) or
  "simulated" (numbers from the offline mock provider).
- cost_status: "estimated" (provider-reported tokens x configured price),
  "simulated" (simulated tokens x configured price), or "unavailable" (no price
  was configured, so no cost is stored).
No measured billing data is stored here. Estimated cost is in nano-USD (1e-9 USD).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utc_now


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0 "
            "AND cached_prompt_tokens >= 0 AND total_tokens >= 0",
            name="ck_usage_events_tokens_nonnegative",
        ),
        CheckConstraint(
            "cached_prompt_tokens <= prompt_tokens",
            name="ck_usage_events_cached_within_prompt",
        ),
        CheckConstraint(
            "usage_origin IN ('provider_reported', 'simulated')",
            name="ck_usage_events_usage_origin",
        ),
        CheckConstraint(
            "cost_status IN ('estimated', 'simulated', 'unavailable')",
            name="ck_usage_events_cost_status",
        ),
        CheckConstraint(
            "(cost_status = 'unavailable' AND estimated_cost_nano_usd IS NULL) "
            "OR (cost_status <> 'unavailable' AND estimated_cost_nano_usd IS NOT NULL)",
            name="ck_usage_events_cost_consistency",
        ),
        Index("ix_usage_events_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_usage_events_tenant_request", "tenant_id", "request_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id", name="fk_usage_events_tenant_id_tenants"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_origin: Mapped[str] = mapped_column(String(32), nullable=False)

    price_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("model_prices.id", name="fk_usage_events_price_id_model_prices"),
        nullable=True,
    )
    price_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price_source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    estimated_cost_nano_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cost_status: Mapped[str] = mapped_column(String(32), nullable=False)
    
