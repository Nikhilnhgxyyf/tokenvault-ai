"""Safe, consistent error responses.

Every error uses the same JSON envelope and never echoes request content,
exception text from unexpected failures, secrets, or stack traces.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.providers.base import (
    ProviderNotConfiguredError,
    ProviderUpstreamError,
    UnsupportedFeatureError,
)

logger = logging.getLogger("tokenvault.errors")


class AppError(Exception):
    """An error we raise on purpose. The message must be safe to show to callers."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        error_type: str = "invalid_request_error",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.error_type = error_type


def error_payload(
    *,
    message: str,
    error_type: str,
    code: str,
    request_id: str | None,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "message": message,
        "type": error_type,
        "code": code,
        "request_id": request_id,
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def _request_id(request: Request) -> str | None:
    state = request.scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str):
            return value
    return None


def _json_error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    error_type: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = dict(headers or {})
    if request_id is not None:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=error_payload(
            message=message,
            error_type=error_type,
            code=code,
            request_id=request_id,
            details=details,
        ),
        headers=response_headers,
    )


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return _json_error(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        error_type=exc.error_type,
    )


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Report only where the problem is and what kind it is. Never echo submitted values.
    details = [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": str(error.get("msg", "Invalid value.")),
            "type": str(error.get("type", "invalid")),
        }
        for error in exc.errors()
    ]
    return _json_error(
        request,
        status_code=422,
        code="invalid_request",
        message="The request is not valid.",
        error_type="invalid_request_error",
        details=details,
    )


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    try:
        phrase = HTTPStatus(exc.status_code).phrase
    except ValueError:
        phrase = "Error"
    return _json_error(
        request,
        status_code=exc.status_code,
        code=phrase.lower().replace(" ", "_"),
        message=phrase,
        error_type="invalid_request_error" if exc.status_code < 500 else "api_error",
        headers=dict(exc.headers) if exc.headers else None,
    )


async def _handle_unsupported_feature(
    request: Request, exc: UnsupportedFeatureError
) -> JSONResponse:
    return _json_error(
        request,
        status_code=400,
        code="unsupported_feature",
        message=str(exc),
        error_type="invalid_request_error",
    )


async def _handle_upstream_error(request: Request, exc: ProviderUpstreamError) -> JSONResponse:
    logger.error("provider_upstream_error", exc_info=exc)
    return _json_error(
        request,
        status_code=502,
        code="upstream_error",
        message="The upstream provider returned an error.",
        error_type="api_error",
    )


async def _handle_not_configured(request: Request, exc: ProviderNotConfiguredError) -> JSONResponse:
    logger.error("provider_not_configured", exc_info=exc)
    return _json_error(
        request,
        status_code=503,
        code="provider_not_configured",
        message="No provider is available. Check the server configuration.",
        error_type="api_error",
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", exc_info=exc)
    return _json_error(
        request,
        status_code=500,
        code="internal_error",
        message="Internal server error.",
        error_type="api_error",
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(UnsupportedFeatureError, _handle_unsupported_feature)
    app.add_exception_handler(ProviderUpstreamError, _handle_upstream_error)
    app.add_exception_handler(ProviderNotConfiguredError, _handle_not_configured)
    app.add_exception_handler(Exception, _handle_unexpected)
  
