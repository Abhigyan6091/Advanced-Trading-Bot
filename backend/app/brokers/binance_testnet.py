"""Binance USDT-M Futures **testnet** broker.

Constructed with ``testnet=True``. Credentials are required here, unlike market
data, and their absence is an error at construction rather than a confusing
authentication failure on the first order.

There is no live-money counterpart to this class anywhere in the codebase.
"""

from __future__ import annotations

from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.brokers.base import BrokerUnavailable, DuplicateOrder, OrderRejected
from app.core.logging import get_logger
from app.core.money import D
from app.domain import Fill, Order, OrderStatus, OrderType, Side

log = get_logger(__name__)

#: Venue status -> our lifecycle. Anything unmapped is treated as an error
#: rather than guessed at.
_STATUS_MAP: dict[str, OrderStatus] = {
    "NEW": OrderStatus.SUBMITTED,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}


class BinanceTestnetBroker:
    """Routes orders to the Binance Futures testnet."""

    name = "testnet"

    def __init__(self, api_key: str, api_secret: str) -> None:
        if not api_key or not api_secret:
            raise ValueError(
                "Binance testnet credentials are required. Set BINANCE_API_KEY and "
                "BINANCE_API_SECRET, or use BROKER=paper which needs none."
            )
        from binance.client import Client

        # testnet=True is the supported switch; never rewrite URL attributes.
        self._client = Client(api_key, api_secret, testnet=True)

    # --- Broker protocol -----------------------------------------------

    def submit(self, order: Order) -> Order:
        """Submit, treating the venue's duplicate-id error as success.

        The venue enforces client-order-id uniqueness. If a submission times
        out after the exchange accepted it, the retry comes back as a duplicate
        error — which means the order exists, so we fetch and return it rather
        than surfacing a failure.
        """
        existing = self.get_order(order.client_order_id)
        if existing is not None:
            log.info("broker.submit.duplicate", client_order_id=order.client_order_id)
            return existing

        params: dict[str, Any] = {
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.order_type.value,
            "quantity": str(order.quantity),
            "newClientOrderId": order.client_order_id,
        }
        if order.order_type is OrderType.LIMIT:
            params["price"] = str(order.price)
            params["timeInForce"] = order.time_in_force.value
        elif order.order_type is OrderType.STOP_MARKET:
            params["stopPrice"] = str(order.stop_price)

        try:
            response = self._client.futures_create_order(**params)
        except Exception as exc:  # noqa: BLE001 - classified below
            return self._handle_submit_error(exc, order)

        return self._apply(order, response)

    def cancel(self, client_order_id: str) -> Order:
        order = self.get_order(client_order_id)
        if order is None:
            raise OrderRejected(f"unknown order {client_order_id!r}")
        try:
            response = self._client.futures_cancel_order(
                symbol=order.symbol, origClientOrderId=client_order_id
            )
        except Exception as exc:  # noqa: BLE001
            raise BrokerUnavailable(f"could not cancel {client_order_id!r}") from exc
        return self._apply(order, response)

    @retry(
        retry=retry_if_exception_type(BrokerUnavailable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    def get_order(self, client_order_id: str, symbol: str | None = None) -> Order | None:
        if symbol is None:
            # Binance requires a symbol to look an order up; without one there
            # is nothing to query.
            return None
        try:
            response = self._client.futures_get_order(
                symbol=symbol, origClientOrderId=client_order_id
            )
        except Exception as exc:  # noqa: BLE001
            if _is_unknown_order(exc):
                return None
            raise BrokerUnavailable(f"could not fetch {client_order_id!r}") from exc
        return self._from_response(response)

    def fills_for(self, client_order_id: str, symbol: str | None = None) -> list[Fill]:
        if symbol is None:
            return []
        try:
            trades = self._client.futures_account_trades(symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            raise BrokerUnavailable(f"could not fetch trades for {symbol}") from exc

        order = self.get_order(client_order_id, symbol=symbol)
        if order is None or order.exchange_order_id is None:
            return []
        return [
            self._to_fill(order, t)
            for t in trades
            if str(t.get("orderId")) == order.exchange_order_id
        ]

    # --- translation ---------------------------------------------------

    def _handle_submit_error(self, exc: Exception, order: Order) -> Order:
        if _is_duplicate_order(exc):
            # The venue already has it: the previous attempt landed.
            existing = self.get_order(order.client_order_id, symbol=order.symbol)
            if existing is not None:
                return existing
            raise DuplicateOrder(
                f"client_order_id {order.client_order_id!r} is already in use"
            ) from exc
        if _is_rejection(exc):
            log.warning("broker.rejected", client_order_id=order.client_order_id, error=str(exc))
            raise OrderRejected(str(exc)) from exc
        raise BrokerUnavailable(str(exc)) from exc

    def _apply(self, order: Order, response: dict[str, Any]) -> Order:
        status = self._map_status(response.get("status", ""))
        filled = D(response.get("executedQty", "0"))
        avg = response.get("avgPrice")

        changes: dict[str, Any] = {
            "exchange_order_id": str(response.get("orderId", "")) or None,
            "filled_quantity": filled,
        }
        if avg is not None and D(avg) > 0:
            changes["average_fill_price"] = D(avg)

        return order.transition_to(status, **changes)

    def _from_response(self, response: dict[str, Any]) -> Order:
        avg = response.get("avgPrice")
        return Order(
            client_order_id=response["clientOrderId"],
            exchange_order_id=str(response.get("orderId", "")) or None,
            symbol=response["symbol"],
            side=Side(response["side"]),
            order_type=OrderType(response["type"]),
            quantity=D(response["origQty"]),
            price=D(response["price"]) if D(response.get("price", "0")) > 0 else None,
            stop_price=(
                D(response["stopPrice"]) if D(response.get("stopPrice", "0")) > 0 else None
            ),
            status=self._map_status(response.get("status", "")),
            filled_quantity=D(response.get("executedQty", "0")),
            average_fill_price=D(avg) if avg is not None and D(avg) > 0 else None,
        )

    @staticmethod
    def _to_fill(order: Order, trade: dict[str, Any]) -> Fill:
        return Fill(
            order_id=order.id,
            symbol=trade["symbol"],
            side=Side(trade["side"]),
            quantity=D(trade["qty"]),
            price=D(trade["price"]),
            commission=D(trade.get("commission", "0")),
            commission_asset=trade.get("commissionAsset", "USDT"),
            exchange_trade_id=str(trade["id"]),
        )

    @staticmethod
    def _map_status(venue_status: str) -> OrderStatus:
        try:
            return _STATUS_MAP[venue_status]
        except KeyError:
            raise OrderRejected(
                f"unrecognised venue order status {venue_status!r}"
            ) from None


def _is_duplicate_order(exc: Exception) -> bool:
    return "-4015" in str(exc) or "duplicate" in str(exc).lower()


def _is_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("insufficient", "reject", "invalid", "notional", "precision")
    )


def _is_unknown_order(exc: Exception) -> bool:
    return "-2013" in str(exc) or "does not exist" in str(exc).lower()
