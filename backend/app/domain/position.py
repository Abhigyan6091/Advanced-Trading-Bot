"""Positions, maintained by average-cost accounting.

A position is a fold over fills. ``apply_fill`` handles the four cases that
actually occur — opening, increasing, reducing, and reversing through flat —
and is the only place P&L is realised.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.money import ZERO, notional
from app.domain.enums import PositionSide, Side
from app.domain.fill import Fill


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Position(BaseModel):
    """Net exposure in one symbol.

    ``signed_quantity`` is positive when long and negative when short; a flat
    position is zero. Carrying the sign rather than a separate side field means
    the arithmetic has no branches for direction.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    signed_quantity: Decimal = ZERO
    average_entry_price: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    total_commission: Decimal = ZERO
    updated_at: datetime = Field(default_factory=_utcnow)

    # --- derived state -------------------------------------------------

    @property
    def side(self) -> PositionSide:
        if self.signed_quantity > 0:
            return PositionSide.LONG
        if self.signed_quantity < 0:
            return PositionSide.SHORT
        return PositionSide.FLAT

    @property
    def quantity(self) -> Decimal:
        """Absolute size, regardless of direction."""
        return abs(self.signed_quantity)

    @property
    def is_flat(self) -> bool:
        return self.signed_quantity == ZERO

    def notional_value(self, mark_price: Decimal) -> Decimal:
        """Absolute exposure at the current mark."""
        return notional(self.quantity, mark_price)

    def unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        """Open P&L. Zero when flat, and correctly signed for shorts."""
        if self.is_flat:
            return ZERO
        return self.signed_quantity * (mark_price - self.average_entry_price)

    def total_pnl(self, mark_price: Decimal) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl(mark_price)

    # --- state transition ----------------------------------------------

    def apply_fill(self, fill: Fill) -> Position:
        """Return the position after ``fill``, realising P&L where applicable.

        Four cases:

        * **Open / increase** — the fill has the same sign as the position.
          Average entry price is re-weighted; nothing is realised.
        * **Reduce** — opposite sign, smaller than the position. P&L is
          realised on the closed portion; average entry price is unchanged.
        * **Close** — opposite sign, exactly the position size. Everything is
          realised and the position goes flat.
        * **Reverse** — opposite sign, larger than the position. The existing
          position is fully realised and the remainder opens a new position at
          the fill price.
        """
        if fill.symbol != self.symbol:
            raise ValueError(
                f"fill for {fill.symbol} cannot be applied to a {self.symbol} position"
            )

        delta = fill.signed_quantity
        current = self.signed_quantity
        new_signed = current + delta

        commission = self.total_commission + fill.commission
        realized = self.realized_pnl
        avg_price = self.average_entry_price

        same_direction = current == ZERO or (current > ZERO) == (delta > ZERO)

        if same_direction:
            # Open or increase: re-weight the average entry price.
            total_cost = (abs(current) * avg_price) + (abs(delta) * fill.price)
            avg_price = total_cost / abs(new_signed)
        else:
            closed_quantity = min(abs(delta), abs(current))
            # Profit is (exit - entry) in the direction the position was held.
            direction = Decimal(1) if current > ZERO else Decimal(-1)
            realized += closed_quantity * (fill.price - avg_price) * direction

            if abs(delta) > abs(current):
                # Reversal: remainder opens fresh at the fill price.
                avg_price = fill.price
            elif new_signed == ZERO:
                avg_price = ZERO
            # A partial reduction leaves the average entry price untouched.

        return Position(
            symbol=self.symbol,
            signed_quantity=new_signed,
            average_entry_price=avg_price,
            realized_pnl=realized,
            total_commission=commission,
            updated_at=fill.executed_at,
        )

    @classmethod
    def flat(cls, symbol: str) -> Position:
        return cls(symbol=symbol)

    @classmethod
    def from_fills(cls, symbol: str, fills: list[Fill]) -> Position:
        """Rebuild a position by replaying its fills in order."""
        position = cls.flat(symbol)
        for fill in sorted(fills, key=lambda f: f.executed_at):
            position = position.apply_fill(fill)
        return position


__all__ = ["Position", "PositionSide", "Side"]
