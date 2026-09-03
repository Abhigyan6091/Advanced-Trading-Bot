"""Orders and their lifecycle.

An Order is immutable; a state change produces a new instance through
``transition_to``, which refuses illegal moves. Modelling the lifecycle as an
explicit graph rather than a mutable status string means an order cannot go
from FILLED back to PENDING because some retry path set a field twice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import OrderStatus, OrderType, Side, TimeInForce
from app.domain.types import NonNegQuantity, Price, Quantity


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_client_order_id() -> str:
    """Client-generated idempotency key.

    Generated before submission and stored with the order, so replaying a
    submission after a timeout resolves to the same order instead of creating a
    duplicate.
    """
    return f"sta-{uuid.uuid4().hex[:24]}"


#: Legal state transitions. Anything absent is rejected.
_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset(
        {OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.CANCELLED}
    ),
    OrderStatus.SUBMITTED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


class IllegalTransition(ValueError):
    """Raised when an order is moved between incompatible states."""


class OrderRequest(BaseModel):
    """A validated intent to trade, before it has any exchange identity.

    This is the shape the CLI and dashboard both submit, and it is the only
    thing a risk decision can be attached to.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    side: Side
    order_type: OrderType
    quantity: Quantity

    price: Price | None = None
    stop_price: Price | None = None
    time_in_force: TimeInForce = TimeInForce.GTC

    client_order_id: str = Field(default_factory=new_client_order_id)
    reduce_only: bool = False

    @model_validator(mode="after")
    def _price_fields_match_type(self) -> OrderRequest:
        if self.order_type.requires_price and self.price is None:
            raise ValueError(f"{self.order_type.value} order requires a price")
        if self.order_type.requires_stop_price and self.stop_price is None:
            raise ValueError(f"{self.order_type.value} order requires a stop_price")
        if self.order_type is OrderType.MARKET and self.price is not None:
            raise ValueError("MARKET order must not carry a price")
        return self


class Order(BaseModel):
    """An order request that has been accepted into the system."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    client_order_id: str

    #: Provenance. Both are absent only for a manually entered order.
    signal_id: uuid.UUID | None = None
    risk_decision_id: uuid.UUID | None = None

    symbol: str
    side: Side
    order_type: OrderType
    quantity: Quantity
    price: Price | None = None
    stop_price: Price | None = None
    time_in_force: TimeInForce = TimeInForce.GTC

    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: NonNegQuantity = Decimal("0")
    average_fill_price: Price | None = None

    #: Venue-assigned identifier, present once submitted.
    exchange_order_id: str | None = None

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _fill_within_quantity(self) -> Order:
        if self.filled_quantity > self.quantity:
            raise ValueError("filled_quantity cannot exceed order quantity")
        if self.status is OrderStatus.FILLED and self.filled_quantity != self.quantity:
            raise ValueError("a FILLED order must be fully filled")
        return self

    @classmethod
    def from_request(
        cls,
        request: OrderRequest,
        *,
        signal_id: uuid.UUID | None = None,
        risk_decision_id: uuid.UUID | None = None,
        quantity: Decimal | None = None,
    ) -> Order:
        """Build an order from a request.

        ``quantity`` overrides the requested size, which is how a risk REDUCE
        verdict is applied: the order carries the approved size, and the
        decision that produced it.
        """
        return cls(
            client_order_id=request.client_order_id,
            signal_id=signal_id,
            risk_decision_id=risk_decision_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=quantity if quantity is not None else request.quantity,
            price=request.price,
            stop_price=request.stop_price,
            time_in_force=request.time_in_force,
        )

    def transition_to(self, status: OrderStatus, **changes: object) -> Order:
        """Return a new Order in ``status``, refusing illegal moves.

        Rebuilt through the constructor rather than ``model_copy``: copying
        does not re-run validators, so the fill-quantity invariants would be
        silently skipped on every state change.
        """
        if status not in _TRANSITIONS[self.status]:
            raise IllegalTransition(
                f"cannot move order {self.client_order_id} from "
                f"{self.status.value} to {status.value}"
            )
        data = self.model_dump()
        data.update(status=status, updated_at=_utcnow(), **changes)
        return type(self)(**data)

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def is_open(self) -> bool:
        return self.status.is_open
