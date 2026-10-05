"""POST /v1/chat/completions: the first gateway endpoint.

Steps: authenticate the API key -> check the content type -> validate the body ->
call the provider under a timeout -> record usage -> answer.

No database connection is held open while the provider is running. If usage cannot be
recorded because of an EXPECTED operational problem (database trouble, a timeout, or
usage data that breaks our rules), the reply still goes out (the provider call already
happened) but it says `accounting: failed` and is never labeled as recorded.
Unexpected errors (programming defects) are NOT caught here: they become a 500 and are
logged, so they cannot hide.
"""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import AuthContext, require_api_key
from app.core.errors import AppError
from app.db.session import session_scope
from app.db.types import utc_now
from app.providers.base import ProviderNotConfiguredError
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    TokenVaultInfo,
)
from app.services.errors import AccountingError
from app.services.usage import record_usage, usage_input_from_provider_response

logger = logging.getLogger("tokenvault.gateway")

router = APIRouter(tags=["gateway"])

_ACCOUNTING_TIMEOUT_SECONDS = 5.0

# Failures we expect in normal operation. ValidationError here means the provider reported
# usage that breaks our rules (for example cached tokens above prompt tokens).
_EXPECTED_ACCOUNTING_ERRORS = (
    AccountingError,
    SQLAlchemyError,
    ValidationError,
    TimeoutError,
    OSError,
)


def _request_id(request: Request) -> str:
    state = request.scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str):
            return value
    return uuid.uuid4().hex


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: Request,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_api_key)],
) -> ChatCompletionResponse:
    settings = request.app.state.settings
    provider = request.app.state.provider
    if provider is None:
        raise ProviderNotConfiguredError("No provider is configured.")

    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/json":
        raise AppError(415, "unsupported_media_type", "Content-Type must be application/json.")

    body = await request.body()
    try:
        gateway_request = ChatCompletionRequest.model_validate_json(body)
    except ValidationError as exc:
        # Report where the problem is, never the submitted values (they may be sensitive).
        raise RequestValidationError(
            exc.errors(include_url=False, include_context=False, include_input=False)
        ) from None
    gateway_request.ensure_supported()
    provider_request = gateway_request.to_provider_request()

    try:
        async with asyncio.timeout(settings.upstream_timeout_seconds):
            provider_response = await provider.complete(provider_request)
    except TimeoutError as exc:
        logger.warning(
            "provider_timeout",
            extra={"fields": {"tenant_id": auth.tenant_id, "provider": provider.name}},
        )
        raise AppError(
            504, "upstream_timeout", "The upstream provider timed out.", error_type="api_error"
        ) from exc

    request_id = _request_id(request)
    usage = provider_response.usage

    accounting = "recorded"
    cost_status = None
    estimated_cost = None
    try:
        usage_input = usage_input_from_provider_response(
            tenant_id=auth.tenant_id, request_id=request_id, response=provider_response
        )
        async with asyncio.timeout(_ACCOUNTING_TIMEOUT_SECONDS):
            async with session_scope(request.app.state.session_factory) as session:
                event = await record_usage(session, usage_input)
        cost_status = event.cost_status
        estimated_cost = event.estimated_cost_nano_usd
    except _EXPECTED_ACCOUNTING_ERRORS as exc:
        accounting = "failed"
        # Metadata only, so the call can be reconciled by hand: no prompt or reply text,
        # and no exception message (database errors can contain SQL parameters).
        logger.error(
            "usage_accounting_failed",
            extra={
                "fields": {
                    "tenant_id": auth.tenant_id,
                    "request_id": request_id,
                    "provider": provider_response.provider,
                    "model": provider_response.model,
                    "usage_origin": usage.origin,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "error_type": type(exc).__name__,
                }
            },
        )

    notices: list[str] = []
    if usage.origin == "simulated":
        notices.append(
            "Token counts and any cost are simulated by the offline mock provider. "
            "They are not real usage."
        )
    if accounting == "failed":
        notices.append("Usage could not be recorded; this request is not in usage reports.")

    response.headers["X-TokenVault-Usage-Origin"] = usage.origin
    response.headers["X-TokenVault-Accounting"] = accounting

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        object="chat.completion",
        created=int(utc_now().timestamp()),
        model=provider_response.model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=provider_response.content),
                finish_reason=provider_response.finish_reason,
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        ),
        tokenvault=TokenVaultInfo(
            request_id=request_id,
            provider=provider_response.provider,
            usage_origin=usage.origin,
            cached_prompt_tokens=usage.cached_prompt_tokens,
            accounting=accounting,
            cost_status=cost_status,
            estimated_cost_nano_usd=estimated_cost,
            notice=" ".join(notices) if notices else None,
        ),
    )
    
