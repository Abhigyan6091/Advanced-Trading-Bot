"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    log.info(
        "application.startup",
        app=settings.app_name,
        env=settings.app_env,
        broker=settings.broker.value,
    )
    yield
    log.info("application.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Intelligent Trading & Risk Analysis Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    from app.api.routes import health

    app.include_router(health.router)
    return app


app = create_app()
