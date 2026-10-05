"""FastAPI application factory.

Run locally from the backend folder with:  uvicorn app.main:app --port 8000
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.db.session import create_engine_from_settings, create_session_factory, create_tables
from app.middleware.body_limit import BodyLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.providers.base import ProviderNotConfiguredError
from app.providers.registry import get_provider

logger = logging.getLogger("tokenvault.app")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    if settings.should_auto_create_tables:
        await create_tables(application.state.engine)
    logger.info(
        "startup",
        extra={
            "fields": {
                "environment": settings.tokenvault_env,
                "provider_mode": settings.tokenvault_provider_mode,
            }
        },
    )
    yield
    await application.state.engine.dispose()
    logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="TokenVault AI",
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.engine = create_engine_from_settings(settings)
    application.state.session_factory = create_session_factory(application.state.engine)
    try:
        application.state.provider = get_provider(settings)
        application.state.provider_error = None
    except ProviderNotConfiguredError as exc:
        application.state.provider = None
        application.state.provider_error = str(exc)

    install_exception_handlers(application)

    # Added innermost first: body limit, then CORS, then request context (outermost).
    application.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    application.add_middleware(RequestContextMiddleware)

    application.include_router(health_router)
    application.include_router(chat_router)
    return application


app = create_app()
