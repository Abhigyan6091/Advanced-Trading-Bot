"""Closed vocabularies for the trading domain."""

from __future__ import annotations

from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY

    @property
    def sign(self) -> int:
        """+1 for BUY, -1 for SELL. Used for signed position arithmetic."""
        return 1 if self is Side.BUY else -1


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"

    @property
    def requires_price(self) -> bool:
        return self is OrderType.LIMIT

    @property
    def requires_stop_price(self) -> bool:
        return self is OrderType.STOP_MARKET


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES

    @property
    def is_open(self) -> bool:
        return not self.is_terminal


_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


class SignalAction(str, Enum):
    """What a strategy proposes. HOLD is a real answer, not an absence."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

    @property
    def is_actionable(self) -> bool:
        return self is not SignalAction.HOLD

    def to_side(self) -> Side:
        if self is SignalAction.HOLD:
            raise ValueError("HOLD does not map to an order side")
        return Side(self.value)


class RiskAction(str, Enum):
    """The risk engine's verdict on a proposed trade."""

    APPROVE = "APPROVE"
    REDUCE = "REDUCE"
    REJECT = "REJECT"

    @property
    def permits_order(self) -> bool:
        return self is not RiskAction.REJECT


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"
