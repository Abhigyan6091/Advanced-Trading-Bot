"""The broker contract.

One protocol, two implementations: a paper broker that simulates fills, and a
Binance Futures testnet broker. There is deliberately no live-money broker —
absent rather than disabled, so it cannot be switched on by configuration.

Every implementation must honour three rules, which a shared contract test
suite enforces against all of them:

1. **Idempotency.** Submitting the same ``client_order_id`` twice returns the
   original order. A retry after a network timeout must not open a second
   position.
2. **No silent partials.** An order is either accepted with its full requested
   quantity or rejected. Quantity is decided by the risk engine, not quietly
   trimmed at the venue boundary.
3. **Fills reference their order.** A ``Fill`` is only ever produced against an
   order the broker has accepted.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain import Fill, Order


class BrokerError(RuntimeError):
    """Base class for broker failures."""


class OrderRejected(BrokerError):
    """The venue refused the order. Terminal; retrying will not help."""


class BrokerUnavailable(BrokerError):
    """The venue could not be reached. Transient; a retry may succeed."""


class DuplicateOrder(BrokerError):
    """A different order already claims this client_order_id."""


@runtime_checkable
class Broker(Protocol):
    """Somewhere orders can be sent."""

    name: str

    def submit(self, order: Order) -> Order:
        """Submit an order and return it with venue state applied.

        Idempotent on ``client_order_id``: re-submitting a known id returns the
        existing order untouched rather than creating a second one.
        """
        ...

    def cancel(self, client_order_id: str) -> Order:
        """Cancel a working order. Cancelling a terminal order is an error."""
        ...

    def get_order(self, client_order_id: str) -> Order | None:
        """Look up a previously submitted order."""
        ...

    def fills_for(self, client_order_id: str) -> list[Fill]:
        """Executions recorded against an order."""
        ...
