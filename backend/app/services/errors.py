"""Errors raised by services. Messages are safe to show to callers."""


class AccountingError(Exception):
    """Base class for accounting and tenant errors."""


class InvalidInputError(AccountingError):
    """The data breaks a validation or database rule."""


class UnknownTenantError(AccountingError):
    """The tenant does not exist."""


class DuplicateTenantError(AccountingError):
    """A tenant with this slug already exists."""
  
