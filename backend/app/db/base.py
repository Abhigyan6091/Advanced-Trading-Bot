"""SQLAlchemy declarative base and shared column types."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase, mapped_column

#: Money and quantities. 24 significant digits with 10 decimal places covers
#: 8-decimal crypto quantities and large notionals without loss. NUMERIC is
#: exact — this is the database-side half of the no-floats rule.
Money = Annotated[Decimal, mapped_column(Numeric(24, 10))]
OptMoney = Annotated[Decimal, mapped_column(Numeric(24, 10), nullable=True)]

#: Every timestamp is stored timezone-aware in UTC.
Timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True))]

UUIDPk = Annotated[uuid.UUID, mapped_column(primary_key=True, default=uuid.uuid4)]
Symbol = Annotated[str, mapped_column(String(20), index=True)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
