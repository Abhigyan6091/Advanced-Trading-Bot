"""Broker behaviour, including the contract every implementation must meet."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.brokers import BrokerError, DuplicateOrder, OrderRejected, PaperBroker
from app.brokers.base import Broker
from app.domain import Order, OrderRequest, OrderStatus, OrderType, Side


def request(qty: str = "1", **kwargs) -> OrderRequest:
    base = dict(
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
    )
    return OrderRequest(**{**base, **kwargs})


@pytest.fixture
def broker(btc) -> PaperBroker:
    b = PaperBroker(commission_rate="0.0004", slippage_bps="2", instruments={"BTCUSDT": btc})
    b.set_mark("BTCUSDT", "60000")
    return b


class TestBrokerContract:
    """Rules every broker implementation must honour."""

    def test_satisfies_the_protocol(self, broker):
        assert isinstance(broker, Broker)

    def test_submission_is_idempotent(self, broker):
        """A retry after a timeout must not open a second position."""
        order = Order.from_request(request())
        first = broker.submit(order)
        second = broker.submit(order)

        assert first.id == second.id
        assert len(broker.orders) == 1
        assert len(broker.all_fills) == 1

    def test_a_different_order_reusing_an_id_is_refused(self, broker):
        first = Order.from_request(request())
        broker.submit(first)

        clash = Order.from_request(request("2")).model_copy(
            update={"client_order_id": first.client_order_id}
        )
        with pytest.raises(DuplicateOrder):
            broker.submit(clash)

    def test_accepted_orders_fill_their_full_quantity(self, broker):
        """No silent partials: size is the risk engine's decision, not the venue's."""
        order = broker.submit(Order.from_request(request("0.5")))
        assert order.status is OrderStatus.FILLED
        assert order.filled_quantity == Decimal("0.5")
        assert order.remaining_quantity == 0

    def test_fills_reference_their_order(self, broker):
        order = broker.submit(Order.from_request(request()))
        fills = broker.fills_for(order.client_order_id)
        assert fills
        assert all(f.order_id == order.id for f in fills)
        assert all(f.symbol == order.symbol for f in fills)

    def test_unknown_order_lookup_returns_none(self, broker):
        assert broker.get_order("sta-does-not-exist") is None


class TestExecutionSimulation:
    def test_slippage_always_moves_against_the_trader(self, broker):
        """A backtest that flatters its fills is worse than none at all."""
        buy = broker.submit(Order.from_request(request()))
        assert buy.average_fill_price > Decimal("60000")

        broker.set_mark("BTCUSDT", "60000")
        sell = broker.submit(Order.from_request(request(side=Side.SELL)))
        assert sell.average_fill_price < Decimal("60000")

    def test_fill_price_is_snapped_to_the_venue_tick(self, broker, btc):
        order = broker.submit(Order.from_request(request()))
        assert order.average_fill_price == btc.round_price(order.average_fill_price)

    def test_commission_is_charged_on_notional(self, broker):
        order = broker.submit(Order.from_request(request("0.5")))
        fill = broker.fills_for(order.client_order_id)[0]
        assert fill.commission == fill.quantity * fill.price * broker.commission_rate
        assert fill.commission > 0

    def test_submission_without_a_mark_price_is_rejected(self, btc):
        broker = PaperBroker(instruments={"BTCUSDT": btc})
        with pytest.raises(OrderRejected, match="no mark price"):
            broker.submit(Order.from_request(request()))


class TestOrderTypes:
    def test_marketable_limit_fills(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("61000"))
            )
        )
        assert order.status is OrderStatus.FILLED

    def test_away_from_market_limit_rests(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("59000"))
            )
        )
        assert order.status is OrderStatus.SUBMITTED
        assert broker.fills_for(order.client_order_id) == []

    def test_stop_market_triggers_once_the_mark_passes_it(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.STOP_MARKET, stop_price=Decimal("59000"))
            )
        )
        # Buy stop at 59,000 with the mark at 60,000 is already through.
        assert order.status is OrderStatus.FILLED

    def test_sell_limit_below_market_does_not_fill(self, broker):
        order = broker.submit(
            Order.from_request(
                request(side=Side.SELL, order_type=OrderType.LIMIT, price=Decimal("61000"))
            )
        )
        assert order.status is OrderStatus.SUBMITTED


class TestCancellation:
    def test_a_resting_order_can_be_cancelled(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("59000"))
            )
        )
        cancelled = broker.cancel(order.client_order_id)
        assert cancelled.status is OrderStatus.CANCELLED

    def test_a_filled_order_cannot_be_cancelled(self, broker):
        order = broker.submit(Order.from_request(request()))
        with pytest.raises(BrokerError, match="terminal state"):
            broker.cancel(order.client_order_id)

    def test_cancelling_an_unknown_order_is_an_error(self, broker):
        with pytest.raises(BrokerError, match="unknown order"):
            broker.cancel("sta-nope")


class TestNoLiveBroker:
    def test_there_is_no_live_broker_class(self):
        import app.brokers as brokers

        names = [n.lower() for n in brokers.__all__]
        assert not any("live" in n or "mainnet" in n or "production" in n for n in names)

    def test_testnet_broker_demands_credentials(self):
        from app.brokers import BinanceTestnetBroker

        with pytest.raises(ValueError, match="credentials are required"):
            BinanceTestnetBroker("", "")


class TestSimulatedClockAppliesToTransitions:
    """Regression: transition_to always stamped updated_at with wall-clock
    time, so a replayed order's history mixed a simulated created_at with a
    real-time updated_at -- persisted order rows for historical replays were
    dated today no matter which period they simulated.
    """

    def test_a_filled_orders_updated_at_uses_the_simulated_clock(self, broker):
        simulated = datetime(2020, 1, 1, tzinfo=timezone.utc)
        broker.set_time(simulated)

        order = broker.submit(Order.from_request(request(), now=simulated))

        assert order.status is OrderStatus.FILLED
        assert order.updated_at == simulated

    def test_cancellation_also_uses_the_simulated_clock(self, broker):
        simulated = datetime(2020, 1, 1, tzinfo=timezone.utc)
        broker.set_time(simulated)

        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("59000")), now=simulated
            )
        )
        cancelled = broker.cancel(order.client_order_id)

        assert cancelled.updated_at == simulated


class TestRestingOrdersFillWhenTheMarketMoves:
    """Regression: fills were only ever evaluated at submission time, so a
    LIMIT or STOP order that was not marketable when placed stayed SUBMITTED
    forever, even after the price later moved to meet it -- unlike a real
    venue, which fills a resting order the moment it becomes marketable.
    """

    def test_a_resting_limit_fills_once_the_mark_reaches_it(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("59000"))
            )
        )
        assert order.status is OrderStatus.SUBMITTED

        broker.set_mark("BTCUSDT", "59000")

        filled = broker.get_order(order.client_order_id)
        assert filled.status is OrderStatus.FILLED

    def test_a_resting_limit_stays_open_while_still_unreachable(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("50000"))
            )
        )
        broker.set_mark("BTCUSDT", "58000")  # still above the 50,000 buy limit

        still_resting = broker.get_order(order.client_order_id)
        assert still_resting.status is OrderStatus.SUBMITTED

    def test_a_resting_stop_triggers_once_the_mark_passes_it(self, broker):
        order = broker.submit(
            Order.from_request(
                request(
                    side=Side.SELL, order_type=OrderType.STOP_MARKET, stop_price=Decimal("58000")
                )
            )
        )
        assert order.status is OrderStatus.SUBMITTED

        broker.set_mark("BTCUSDT", "57500")

        filled = broker.get_order(order.client_order_id)
        assert filled.status is OrderStatus.FILLED

    def test_a_cancelled_order_does_not_come_back_to_life(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("50000"))
            )
        )
        broker.cancel(order.client_order_id)

        broker.set_mark("BTCUSDT", "50000")  # would have been marketable

        still_cancelled = broker.get_order(order.client_order_id)
        assert still_cancelled.status is OrderStatus.CANCELLED

    def test_a_mark_update_in_an_unrelated_symbol_does_not_touch_it(self, broker):
        order = broker.submit(
            Order.from_request(
                request(order_type=OrderType.LIMIT, price=Decimal("59000"))
            )
        )
        broker.set_mark("ETHUSDT", "3000")

        assert broker.get_order(order.client_order_id).status is OrderStatus.SUBMITTED
