"""Versioned model prices, entered by an operator (never invented by the code).

Unit: micro-USD per 1,000,000 tokens. Example: $0.15 per million tokens is stored as
150000. Integers avoid floating-point rounding errors.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utc_now


class ModelPrice(Base):
    __tablename__ = "model_prices"
    __table_args__ = (
        UniqueConstraint(
            "provider", "model", "price_version", name="uq_model_prices_provider_model_version"
        ),
        CheckConstraint(
            "input_micro_usd_per_million >= 0 AND output_micro_usd_per_million >= 0 "
            "AND (cached_input_micro_usd_per_million IS NULL "
            "OR cached_input_micro_usd_per_million >= 0)",
            name="ck_model_prices_nonnegative",
        ),
        Index("ix_model_prices_lookup", "provider", "model", "effective_from"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_micro_usd_per_million: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_micro_usd_per_million: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cached_input_micro_usd_per_million: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    price_version: Mapped[str] = mapped_column(String(64), nullable=False)
    price_source: Mapped[str] = mapped_column(String(500), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    
