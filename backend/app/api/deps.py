"""Shared API dependencies.

Declared with ``Annotated`` so the dependency is part of the type rather than a
mutable default argument.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services import TradingService


def settings_dep() -> Settings:
    return get_settings()


def db_session() -> Iterator[Session]:
    yield from get_db()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
SessionDep = Annotated[Session, Depends(db_session)]


def trading_service(session: SessionDep, settings: SettingsDep) -> TradingService:
    return TradingService(session=session, settings=settings)


ServiceDep = Annotated[TradingService, Depends(trading_service)]
