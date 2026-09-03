"""Paper broker — the default execution venue.

Simulates fills against a supplied mark price, applying commission and
slippage, so the entire platform is usable with no exchange credentials.

The simulation is deliberately pessimistic: slippage always moves against the
trader. A backtest that flatters itself on fill prices is worse than no
backtest, because it produces confident numbers that are wrong.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.brokers.base import BrokerError, DuplicateOrder, OrderRejected
from app.core.logging import get_logger
from app.core.money import ZERO, D, apply_bps
from app.domain import (
    Fill,
    Instrument,
    Order,
    OrderStatus,
    OrderType,
    Side,
)

log = get_logger(__name__)


class PaperBroker:
    """In-process order book with simulated execution."""

    name = "paper"

    def __init__(
        self,
        commission_rate: Decimal | str = "0.0004",
        slippage_bps: Decimal | str = "2",
        instruments: dict[str, Instrument] | None = None,
    ) -> None:
        self.commission_rate = D(commission_rate)
        self.slippage_bps = D(slippage_bps)
        self.instruments = instruments or {}

        self._orders: dict[str, Order] = {}
        self._fills: dict[str, list[Fill]] = {}
        self._marks: dict[str, Decimal] = {}

        # Simulation clock. When unset, fills are stamped with wall-clock time.
        # A replay (backtest or seed) advances it per bar so the fill ledger
        # carries the times the trades would actually have happened, and any
        # curve derived from that ledger has a meaningful time axis.
        self._now: datetime | None = None

    # --- market state --------------------------------------------------

    def set_mark(self, symbol: str, price: Decimal | str) -> None:
        """Set the price used to fill subsequent orders in ``symbol``."""
        self._marks[symbol] = D(price)

    def set_time(self, when: datetime | None) -> None:
        """Set the simulation clock. ``None`` restores wall-clock time."""
        self._now = when

    def mark(self, symbol: str) -> Decimal | None:
        return self._marks.get(symbol)

    # --- Broker protocol -----------------------------------------------

    def submit(self, order: Order) -> Order:
        existing = self._orders.get(order.client_order_id)
        if existing is not None:
            if existing.id != order.id:
                raise DuplicateOrder(
                    f"client_order_id {order.client_order_id!r} already belongs "
                    f"to a different order"
                )
            # A replayed submission after a timeout: return what already exists.
            log.info("broker.submit.duplicate", client_order_id=order.client_order_id)
            return existing

        mark = self._marks.get(order.symbol)
        if mark is None:
            raise OrderRejected(f"no mark price available for {order.symbol}")

        accepted = order.transition_to(
            OrderStatus.SUBMITTED,
            exchange_order_id=f"paper-{order.client_order_id[-12:]}",
        )
        self._orders[order.client_order_id] = accepted
        self._fills.setdefault(order.client_order_id, [])

        if self._fills_immediately(accepted, mark):
            accepted = self._fill(accepted, mark)

        return accepted

    def cancel(self, client_order_id: str) -> Order:
        order = self._orders.get(client_order_id)
        if order is None:
            raise BrokerError(f"unknown order {client_order_id!r}")
        if order.status.is_terminal:
            raise BrokerError(
                f"cannot cancel order {client_order_id!r} in terminal state "
                f"{order.status.value}"
            )
        cancelled = order.transition_to(OrderStatus.CANCELLED)
        self._orders[client_order_id] = cancelled
        return cancelled

    def get_order(self, client_order_id: str) -> Order | None:
        return self._orders.get(client_order_id)

    def fills_for(self, client_order_id: str) -> list[Fill]:
        return list(self._fills.get(client_order_id, []))

    # --- simulation ----------------------------------------------------

    @staticmethod
    def _fills_immediately(order: Order, mark: Decimal) -> bool:
        """Would this order execute against the current mark?"""
        if order.order_type is OrderType.MARKET:
            return True
        if order.order_type is OrderType.LIMIT:
            assert order.price is not None
            return mark <= order.price if order.side is Side.BUY else mark >= order.price
        if order.order_type is OrderType.STOP_MARKET:
            assert order.stop_price is not None
            return (
                mark >= order.stop_price
                if order.side is Side.BUY
                else mark <= order.stop_price
            )
        return False

    def _fill(self, order: Order, mark: Decimal) -> Order:
        price = self._execution_price(order, mark)
        commission = order.quantity * price * self.commission_rate

        fill = Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            commission=commission,
            exchange_trade_id=f"paper-trade-{order.client_order_id[-12:]}",
            **({"executed_at": self._now} if self._now is not None else {}),
        )
        self._fills[order.client_order_id].append(fill)

        filled = order.transition_to(
            OrderStatus.FILLED,
            filled_quantity=order.quantity,
            average_fill_price=price,
        )
        self._orders[order.client_order_id] = filled

        log.info(
            "broker.filled",
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side.value,
            quantity=str(order.quantity),
            price=str(price),
            commission=str(commission),
        )
        return filled

    def _execution_price(self, order: Order, mark: Decimal) -> Decimal:
        """Apply slippage against the trader, then snap to the venue tick.

        A buy fills slightly above the mark and a sell slightly below. Assuming
        a mid-price fill is the most common way a backtest overstates itself.
        """
        direction = self.slippage_bps if order.side is Side.BUY else -self.slippage_bps
        price = apply_bps(mark, direction)

        instrument = self.instruments.get(order.symbol)
        if instrument is not None:
            price = instrument.round_price(price)
        return max(price, ZERO)

    # --- introspection --------------------------------------------------

    @property
    def orders(self) -> list[Order]:
        return list(self._orders.values())

    @property
    def all_fills(self) -> list[Fill]:
        return [f for fills in self._fills.values() for f in fills]
