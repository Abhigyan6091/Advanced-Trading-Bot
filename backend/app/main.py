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

    from fastapi.middleware.cors import CORSMiddleware

    from app.api.routes import (
        backtest,
        health,
        markets,
        orders,
        performance,
        portfolio,
        risk,
        strategies,
    )

    # The dashboard is served from a different origin. An explicit allowlist
    # rather than a wildcard, so credentialed requests stay safe.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (
        health,
        performance,
        portfolio,
        risk,
        orders,
        markets,
        strategies,
        backtest,
    ):
        app.include_router(module.router)
    return app


app = create_app()
