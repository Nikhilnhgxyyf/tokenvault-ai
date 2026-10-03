"""Liveness and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    provider_mode: str
    provider: str | None = None
    detail: str | None = None


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is running. Does not check dependencies."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    """Readiness: the service can do useful work (a provider is available)."""
    settings = request.app.state.settings
    provider = request.app.state.provider
    if provider is None:
        body = ReadyResponse(
            status="not_ready",
            provider_mode=settings.tokenvault_provider_mode,
            detail=request.app.state.provider_error,
        )
        return JSONResponse(status_code=503, content=body.model_dump())
    body = ReadyResponse(
        status="ready",
        provider_mode=settings.tokenvault_provider_mode,
        provider=provider.name,
    )
    return JSONResponse(status_code=200, content=body.model_dump())
  
