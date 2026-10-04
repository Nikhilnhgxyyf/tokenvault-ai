"""Liveness and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.db.session import check_database

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    provider_mode: str
    provider: str | None = None
    database: Literal["ok", "unavailable"]
    detail: str | None = None


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is running. Does not check dependencies."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    """Readiness: a provider is available and the database answers a trivial query."""
    settings = request.app.state.settings
    provider = request.app.state.provider
    database_ok = await check_database(request.app.state.engine)

    problems: list[str] = []
    if provider is None and request.app.state.provider_error:
        problems.append(request.app.state.provider_error)
    if not database_ok:
        problems.append("Database is not reachable.")

    is_ready = provider is not None and database_ok
    body = ReadyResponse(
        status="ready" if is_ready else "not_ready",
        provider_mode=settings.tokenvault_provider_mode,
        provider=provider.name if provider is not None else None,
        database="ok" if database_ok else "unavailable",
        detail="; ".join(problems) if problems else None,
    )
    return JSONResponse(status_code=200 if is_ready else 503, content=body.model_dump())
    
