"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, Any]:
    """Liveness: the process is up. Does not touch dependencies."""
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "broker": settings.broker.value,
        "live_trading": False,
    }


@router.get("/ready")
def ready(response: Response) -> dict[str, Any]:
    """Readiness: dependencies are reachable.

    Returns 503 when the database is down so an orchestrator stops routing
    traffic here rather than serving errors.
    """
    checks: dict[str, str] = {}
    healthy = True

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        checks["database"] = f"unavailable: {type(exc).__name__}"
        healthy = False

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if healthy else "degraded", "checks": checks}
