"""Shared database column types and time helpers.

All timestamps in TokenVault are timezone-aware and stored in UTC. SQLite does not
keep timezone information, so this type converts on the way in and attaches UTC on
the way out. Naive datetimes (no timezone) are rejected on purpose.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware_utc(value: datetime) -> datetime:
    """Return the value converted to UTC, or raise ValueError if it has no timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must be timezone-aware (for example, in UTC).")
    return value.astimezone(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[datetime]:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
      
