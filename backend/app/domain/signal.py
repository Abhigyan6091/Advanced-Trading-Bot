"""Strategy output.

A Signal is a *proposal*. It carries no authority to trade: only the risk
engine can turn one into an order. Strategies therefore have no dependency on
brokers, orders or portfolios, which is what keeps them unit-testable as pure
functions over a bar window.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import SignalAction
from app.domain.types import Price, Strength


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    strategy: str = Field(min_length=1)
    symbol: str

    action: SignalAction
    strength: Strength = Decimal("1")

    #: Price of the bar the signal was derived from.
    reference_price: Price

    #: Close time of the last bar used. Execution must occur strictly after
    #: this instant; the backtester asserts it.
    bar_close_time: datetime

    created_at: datetime = Field(default_factory=_utcnow)

    #: Indicator values behind the decision. Kept for explainability in the UI
    #: and reused as model features in Phase 6.
    features: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _hold_has_no_strength(self) -> Signal:
        if self.action is SignalAction.HOLD and self.strength != 0:
            raise ValueError("a HOLD signal must have strength 0")
        return self

    @property
    def is_actionable(self) -> bool:
        return self.action.is_actionable
