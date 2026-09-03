"""Binance testnet broker, exercised against a mock client.

No network calls: the real testnet is out of reach in CI, so a fake
``binance.client.Client`` stands in, letting us verify the response-mapping
and order-cache logic that the review found broken -- a market order that
fills immediately, and lookups/cancellation keyed on an id alone.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.brokers.base import BrokerUnavailable, OrderRejected
from app.brokers.binance_testnet import BinanceTestnetBroker
from app.domain import Order, OrderRequest, OrderStatus, OrderType, Side


def market_request(qty: str = "1", symbol: str = "BTCUSDT") -> OrderRequest:
    return OrderRequest(
        symbol=symbol, side=Side.BUY, order_type=OrderType.MARKET, quantity=Decimal(qty)
    )


def filled_response(order: Order, exchange_id: str = "555") -> dict:
    return {
        "orderId": exchange_id,
        "clientOrderId": order.client_order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "type": order.order_type.value,
        "status": "FILLED",
        "origQty": str(order.quantity),
        "executedQty": str(order.quantity),
        "avgPrice": "60000.00",
        "price": "0",
        "stopPrice": "0",
    }


@pytest.fixture
def broker() -> BinanceTestnetBroker:
    with patch("binance.client.Client") as mock_client_cls:
        instance = MagicMock()
        mock_client_cls.return_value = instance
        b = BinanceTestnetBroker("key", "secret")
        b._client = instance  # ensure the mock is the one actually used
        yield b


class TestImmediateFill:
    """A market order that fills synchronously must not crash the pipeline.

    Regression: PENDING -> FILLED directly is not a legal transition (see
    app.domain.order._TRANSITIONS), and treating the venue's immediate-fill
    response as a single transition raised IllegalTransition -- a ValueError
    the pipeline's `except BrokerError` could not catch, so the request 500s
    even though the trade executed.
    """

    def test_immediate_fill_does_not_raise(self, broker):
        order = Order.from_request(market_request())
        broker._client.futures_create_order.return_value = filled_response(order)

        result = broker.submit(order)

        assert result.status is OrderStatus.FILLED
        assert result.filled_quantity == order.quantity
        assert result.average_fill_price == Decimal("60000.00")

    def test_the_order_passes_through_submitted_first(self, broker):
        """Confirms the two-step transition, not just that it doesn't crash."""
        order = Order.from_request(market_request())
        broker._client.futures_create_order.return_value = filled_response(order)

        result = broker.submit(order)

        # A direct PENDING -> FILLED would be illegal; reaching FILLED at all
        # proves the intermediate SUBMITTED step happened.
        assert result.exchange_order_id == "555"
        assert result.status is OrderStatus.FILLED


class TestOrderCacheResolvesSymbol:
    """get_order / cancel / fills_for are keyed on id alone; Binance needs a
    symbol. Regression: these silently returned None/[] or raised "unknown
    order" for any id whose symbol was not explicitly re-supplied by the
    caller -- which the Broker protocol's own signature never does.
    """

    def test_get_order_resolves_symbol_from_a_prior_submit(self, broker):
        order = Order.from_request(market_request(symbol="ETHUSDT"))
        broker._client.futures_create_order.return_value = filled_response(order)
        broker.submit(order)

        broker._client.futures_get_order.return_value = filled_response(order)
        found = broker.get_order(order.client_order_id)

        assert found is not None
        assert found.symbol == "ETHUSDT"
        broker._client.futures_get_order.assert_called_with(
            symbol="ETHUSDT", origClientOrderId=order.client_order_id
        )

    def test_cancel_resolves_symbol_from_a_prior_submit(self, broker):
        order = Order.from_request(
            OrderRequest(
                symbol="SOLUSDT",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=Decimal("10"),
            )
        )
        resting = {**filled_response(order), "status": "NEW", "executedQty": "0"}
        broker._client.futures_create_order.return_value = resting
        broker.submit(order)

        cancelled = {**resting, "status": "CANCELED"}
        broker._client.futures_cancel_order.return_value = cancelled
        result = broker.cancel(order.client_order_id)

        assert result.status is OrderStatus.CANCELLED
        broker._client.futures_cancel_order.assert_called_with(
            symbol="SOLUSDT", origClientOrderId=order.client_order_id
        )

    def test_an_id_never_seen_by_this_broker_cannot_be_cancelled(self, broker):
        with pytest.raises(OrderRejected, match="unknown order"):
            broker.cancel("sta-never-submitted")

    def test_fills_for_resolves_symbol_and_matches_by_exchange_order_id(self, broker):
        order = Order.from_request(market_request(symbol="BTCUSDT"))
        broker._client.futures_create_order.return_value = filled_response(order, "777")
        broker.submit(order)

        broker._client.futures_get_order.return_value = filled_response(order, "777")
        broker._client.futures_account_trades.return_value = [
            {
                "orderId": "777",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "qty": "1",
                "price": "60000",
                "commission": "0.24",
                "commissionAsset": "USDT",
                "id": "9001",
            },
            {  # a trade from a different order on the same symbol -- excluded
                "orderId": "other",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "qty": "5",
                "price": "1",
                "commission": "0",
                "commissionAsset": "USDT",
                "id": "9002",
            },
        ]

        fills = broker.fills_for(order.client_order_id)

        assert len(fills) == 1
        assert fills[0].exchange_trade_id == "9001"


class TestSubmissionIdempotency:
    def test_a_cached_order_short_circuits_without_calling_the_venue(self, broker):
        order = Order.from_request(market_request())
        broker._client.futures_create_order.return_value = filled_response(order)
        first = broker.submit(order)

        second = broker.submit(order)

        assert second.id == first.id
        broker._client.futures_create_order.assert_called_once()


class TestTransientVsTerminalErrors:
    def test_a_network_timeout_is_unavailable_not_rejected(self, broker):
        broker._client.futures_create_order.side_effect = TimeoutError("connection timed out")
        order = Order.from_request(market_request())

        with pytest.raises(BrokerUnavailable):
            broker.submit(order)


class TestErrorClassificationUsesStructuredCodes:
    """Regression: a transport/format failure was misclassified as a
    terminal rejection because its message happened to contain the substring
    "invalid" -- exactly the text python-binance produces when a response
    body cannot even be parsed as JSON, which is not the venue rejecting an
    order at all.
    """

    def test_an_unparseable_response_is_unavailable_not_rejected(self, broker):
        from binance.exceptions import BinanceAPIException

        response = MagicMock(text="not json")
        exc = BinanceAPIException(response, 502, "not json")
        assert exc.code == 0  # python-binance's own "could not parse" marker

        broker._client.futures_create_order.side_effect = exc
        order = Order.from_request(market_request())

        with pytest.raises(BrokerUnavailable):
            broker.submit(order)

    def test_a_real_structured_rejection_is_still_terminal(self, broker):
        from binance.exceptions import BinanceAPIException

        response = MagicMock(text='{"code": -2010, "msg": "Account has insufficient balance"}')
        exc = BinanceAPIException(response, 400, response.text)
        assert exc.code == -2010

        broker._client.futures_create_order.side_effect = exc
        order = Order.from_request(market_request())

        with pytest.raises(OrderRejected):
            broker.submit(order)
