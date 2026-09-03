"""Executions against an order.

Fills are the ledger. Positions, realised P&L and every performance metric are
derived from them rather than stored independently, so there is one source of
truth and no reconciliation step.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.money import notional
from app.domain.enums import Side
from app.domain.types import Price, Quantity


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    order_id: uuid.UUID
    symbol: str
    side: Side

    quantity: Quantity
    price: Price
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    commission_asset: str = "USDT"

    #: Venue trade id, used to discard duplicate execution reports.
    exchange_trade_id: str | None = None

    executed_at: datetime = Field(default_factory=_utcnow)

    @property
    def gross_value(self) -> Decimal:
        return notional(self.quantity, self.price)

    @property
    def net_value(self) -> Decimal:
        """Signed cash impact: negative when buying, positive when selling."""
        return -self.side.sign * self.gross_value - self.commission

    @property
    def signed_quantity(self) -> Decimal:
        return self.side.sign * self.quantity
