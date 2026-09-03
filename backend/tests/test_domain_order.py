"""Order construction rules and the lifecycle state machine."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import (
    IllegalTransition,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    new_client_order_id,
)


def market_request(qty: str = "1") -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, order_type=OrderType.MARKET, quantity=Decimal(qty)
    )


class TestOrderRequestValidation:
    def test_limit_order_requires_a_price(self):
        with pytest.raises(ValidationError, match="requires a price"):
            OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
            )

    def test_stop_market_requires_a_stop_price(self):
        with pytest.raises(ValidationError, match="requires a stop_price"):
            OrderRequest(
                symbol="BTCUSDT",
                side=Side.SELL,
                order_type=OrderType.STOP_MARKET,
                quantity=Decimal("1"),
            )

    def test_market_order_must_not_carry_a_price(self):
        with pytest.raises(ValidationError, match="must not carry a price"):
            OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
                price=Decimal("60000"),
            )

    def test_quantity_must_be_positive(self):
        with pytest.raises(ValidationError):
            market_request("0")

    def test_client_order_id_is_generated_and_unique(self):
        assert market_request().client_order_id != market_request().client_order_id
        assert new_client_order_id().startswith("sta-")


class TestRiskProvenance:
    def test_reduced_size_is_applied_from_the_decision(self):
        req = market_request("1")
        decision_id = uuid.uuid4()
        order = Order.from_request(
            req, risk_decision_id=decision_id, quantity=Decimal("0.4")
        )
        assert order.quantity == Decimal("0.4")
        assert order.risk_decision_id == decision_id
        # Idempotency key survives the resize.
        assert order.client_order_id == req.client_order_id


class TestLifecycle:
    def test_happy_path(self):
        order = Order.from_request(market_request())
        assert order.status is OrderStatus.PENDING

        order = order.transition_to(OrderStatus.SUBMITTED, exchange_order_id="X1")
        assert order.exchange_order_id == "X1"

        order = order.transition_to(
            OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
            average_fill_price=Decimal("60000"),
        )
        assert order.status.is_terminal
        assert order.remaining_quantity == Decimal("0")

    def test_partial_fills_accumulate(self):
        order = Order.from_request(market_request("2")).transition_to(OrderStatus.SUBMITTED)
        order = order.transition_to(OrderStatus.PARTIALLY_FILLED, filled_quantity=Decimal("0.5"))
        assert order.remaining_quantity == Decimal("1.5")
        order = order.transition_to(OrderStatus.PARTIALLY_FILLED, filled_quantity=Decimal("1.2"))
        assert order.remaining_quantity == Decimal("0.8")
        assert order.is_open

    @pytest.mark.parametrize(
        ("terminal", "target"),
        [
            (OrderStatus.FILLED, OrderStatus.SUBMITTED),
            (OrderStatus.CANCELLED, OrderStatus.FILLED),
            (OrderStatus.REJECTED, OrderStatus.SUBMITTED),
            (OrderStatus.EXPIRED, OrderStatus.PARTIALLY_FILLED),
        ],
    )
    def test_terminal_states_are_final(self, terminal, target):
        order = Order.from_request(market_request()).transition_to(OrderStatus.SUBMITTED)
        order = order.transition_to(
            terminal,
            **(
                {"filled_quantity": Decimal("1"), "average_fill_price": Decimal("60000")}
                if terminal is OrderStatus.FILLED
                else {}
            ),
        )
        with pytest.raises(IllegalTransition):
            order.transition_to(target)

    def test_cannot_skip_submission(self):
        order = Order.from_request(market_request())
        with pytest.raises(IllegalTransition, match="PENDING to FILLED"):
            order.transition_to(OrderStatus.FILLED)

    def test_orders_are_immutable(self):
        order = Order.from_request(market_request())
        with pytest.raises(ValidationError):
            order.status = OrderStatus.FILLED

    def test_fill_cannot_exceed_order_quantity(self):
        order = Order.from_request(market_request("1")).transition_to(OrderStatus.SUBMITTED)
        with pytest.raises(ValidationError, match="cannot exceed"):
            order.transition_to(OrderStatus.PARTIALLY_FILLED, filled_quantity=Decimal("1.5"))

    def test_filled_status_requires_complete_fill(self):
        order = Order.from_request(market_request("1")).transition_to(OrderStatus.SUBMITTED)
        with pytest.raises(ValidationError, match="must be fully filled"):
            order.transition_to(OrderStatus.FILLED, filled_quantity=Decimal("0.5"))
