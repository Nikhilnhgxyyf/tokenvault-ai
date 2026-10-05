"""Shared request dependencies. `require_api_key` is how every protected route logs a caller in.

The tenant is taken ONLY from the API key's database record. Nothing the client sends
(headers or body) can choose or override it.
"""

import asyncio
import logging
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.services.api_keys import authenticate_api_key, is_well_formed_api_key

logger = logging.getLogger("tokenvault.auth")

_AUTH_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    api_key_id: str


def _invalid_key_error() -> AppError:
    return AppError(
        401,
        "invalid_api_key",
        "Invalid or missing API key.",
        error_type="authentication_error",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_bearer_token(header_value: str | None) -> str | None:
    if header_value is None:
        return None
    scheme, _, token = header_value.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not is_well_formed_api_key(token):
        return None
    return token


async def require_api_key(request: Request) -> AuthContext:
    presented = _extract_bearer_token(request.headers.get("authorization"))
    if presented is None:
        raise _invalid_key_error()

    factory = request.app.state.session_factory
    try:
        async with asyncio.timeout(_AUTH_TIMEOUT_SECONDS):
            async with factory() as session:
                principal = await authenticate_api_key(session, presented)
    except (SQLAlchemyError, TimeoutError, OSError) as exc:
        # We could not check the key. Say so; never claim the key is invalid.
        logger.error(
            "authentication_backend_error", extra={"fields": {"error_type": type(exc).__name__}}
        )
        raise AppError(
            503,
            "auth_unavailable",
            "Authentication is temporarily unavailable.",
            error_type="api_error",
        ) from exc

    if principal is None:
        raise _invalid_key_error()
    if not principal.tenant_active:
        raise AppError(403, "tenant_disabled", "This account is disabled.", "permission_error")
    return AuthContext(tenant_id=principal.tenant_id, api_key_id=principal.api_key_id)
  
