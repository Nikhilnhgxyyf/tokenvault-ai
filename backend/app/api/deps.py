"""Shared request dependencies. `require_api_key` is how every protected route logs a caller in.

The tenant is taken ONLY from the API key's database record. Nothing the client sends
(headers or body) can choose or override it.

Security logging: every rejected attempt writes one `auth_failed` entry with a short
reason. The API key, any part of it, and the Authorization header are never logged.
"""

import asyncio
import logging
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.services.api_keys import is_well_formed_api_key, lookup_api_key

logger = logging.getLogger("tokenvault.auth")

_AUTH_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    api_key_id: str


def _invalid_key_error() -> AppError:
    # The same answer for missing, malformed, unknown and revoked keys, on purpose.
    return AppError(
        401,
        "invalid_api_key",
        "Invalid or missing API key.",
        error_type="authentication_error",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _log_auth_failure(
    reason: str, *, tenant_id: str | None = None, api_key_id: str | None = None
) -> None:
    """Record a rejected login. Only a reason and internal IDs; never the key or header."""
    fields: dict[str, str] = {"reason": reason}
    if tenant_id is not None:
        fields["tenant_id"] = tenant_id
    if api_key_id is not None:
        fields["api_key_id"] = api_key_id
    logger.warning("auth_failed", extra={"fields": fields})


def _extract_bearer_token(header_value: str) -> str | None:
    scheme, _, token = header_value.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not is_well_formed_api_key(token):
        return None
    return token


async def require_api_key(request: Request) -> AuthContext:
    header_value = request.headers.get("authorization")
    if header_value is None:
        _log_auth_failure("missing_credentials")
        raise _invalid_key_error()

    presented = _extract_bearer_token(header_value)
    if presented is None:
        _log_auth_failure("malformed_credentials")
        raise _invalid_key_error()

    factory = request.app.state.session_factory
    try:
        async with asyncio.timeout(_AUTH_TIMEOUT_SECONDS):
            async with factory() as session:
                found = await lookup_api_key(session, presented)
    except (SQLAlchemyError, TimeoutError, OSError) as exc:
        # We could not check the key. Say so; never claim the key is invalid. Only the
        # error type is logged: database messages can contain the key's hash.
        logger.error(
            "authentication_backend_error", extra={"fields": {"error_type": type(exc).__name__}}
        )
        raise AppError(
            503,
            "auth_unavailable",
            "Authentication is temporarily unavailable.",
            error_type="api_error",
        ) from exc

    if found is None:
        _log_auth_failure("unknown_key")
        raise _invalid_key_error()
    if found.revoked:
        _log_auth_failure("revoked_key", tenant_id=found.tenant_id, api_key_id=found.api_key_id)
        raise _invalid_key_error()
    if not found.tenant_active:
        _log_auth_failure("tenant_disabled", tenant_id=found.tenant_id, api_key_id=found.api_key_id)
        raise AppError(403, "tenant_disabled", "This account is disabled.", "permission_error")
    return AuthContext(tenant_id=found.tenant_id, api_key_id=found.api_key_id)
    
