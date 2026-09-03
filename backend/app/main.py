"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address, default_limits=["600/hour"])


def _bootstrap_admin() -> None:
    """Create the configured admin account if it does not already exist.

    Runs once at startup, not per request. A platform an operator cannot log
    into is not securable, so this exists purely to avoid a chicken-and-egg
    problem on first deploy -- it does nothing once that first admin exists,
    and nothing at all if the two env vars are left unset.
    """
    settings = get_settings()
    if not settings.bootstrap_admin_username or not settings.bootstrap_admin_password:
        return

    from app.auth.roles import Role
    from app.auth.security import hash_password
    from app.db.repositories import UserRepository
    from app.db.session import session_scope

    with session_scope() as session:
        users = UserRepository(session)
        if users.get_by_username(settings.bootstrap_admin_username) is not None:
            return
        users.create(
            settings.bootstrap_admin_username,
            hash_password(settings.bootstrap_admin_password),
            Role.ADMIN.value,
        )
        log.info("auth.bootstrap_admin_created", username=settings.bootstrap_admin_username)


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
    try:
        _bootstrap_admin()
    except Exception as exc:  # noqa: BLE001 - must not block startup
        log.warning("auth.bootstrap_admin_failed", error=str(exc))
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

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "invalid request", "errors": exc.errors()},
        )

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):
        # Domain validation (Pydantic model_validators, engine input checks)
        # raises plain ValueError. Surfacing it as 400 rather than a bare 500
        # tells the caller their request was rejected, not that the server
        # broke -- without leaking a stack trace either way.
        log.info("request.value_error", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception):
        log.error(
            "request.unhandled_error",
            path=request.url.path,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "an internal error occurred"},
        )

    from fastapi.middleware.cors import CORSMiddleware
    from slowapi.middleware import SlowAPIMiddleware

    from app.api.routes import (
        ai_analyst,
        audit,
        auth,
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
    app.add_middleware(SlowAPIMiddleware)

    for module in (
        health,
        auth,
        performance,
        portfolio,
        risk,
        orders,
        markets,
        strategies,
        backtest,
        ai_analyst,
        audit,
    ):
        app.include_router(module.router)
    return app


app = create_app()
