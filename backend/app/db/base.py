"""Base class for all database models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Every table model inherits from this class."""
  
