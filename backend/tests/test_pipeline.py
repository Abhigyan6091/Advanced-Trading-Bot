"""The end-to-end pipeline: signal -> risk -> order -> execution -> portfolio."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.brokers import PaperBroker
from app.domain import RiskAction, Signal, SignalAction
from app.portfolio import Portfolio
from app.risk import RiskEngine, RiskLimits
from app.trading import TradingPipeline
from tests.conftest import T0


def signal(action=SignalAction.BUY, price="60000", strength="1", symbol="BTCUSDT") -> Signal:
    return Signal(
        strategy="ema_crossover",
        symbol=symbol,
        action=action,
        strength=Decimal(strength),
        reference_price=Decimal(price),
        bar_close_time=T0,
    )


@pytest.fixture
def broker(btc) -> PaperBroker:
    b = PaperBroker(commission_rate="0.0004", slippage_bps="2", instruments={"BTCUSDT": btc})
    b.set_mark("BTCUSDT", "60000")
    return b


@pytest.fixture
def pipeline(broker, btc) -> TradingPipeline:
    return TradingPipeline(
        risk_engine=RiskEngine(),
        broker=broker,
        portfolio=Portfolio("100000"),
        instruments={"BTCUSDT": btc},
    )


class TestApprovedFlow:
    def test_a_clean_signal_reaches_the_portfolio(self, pipeline):
        outcome = pipeline.handle_signal(signal(), quantity=Decimal("0.05"))

        assert outcome.decision.action is RiskAction.APPROVE
        assert outcome.executed
        assert outcome.order.filled_quantity == Decimal("0.05")
        assert pipeline.portfolio.position("BTCUSDT").signed_quantity == Decimal("0.05")

    def test_the_order_records_its_provenance(self, pipeline):
        """Every order links back to the signal and decision behind it."""
        sig = signal()
        outcome = pipeline.handle_signal(sig, quantity=Decimal("0.05"))
        assert outcome.order.signal_id == sig.id
        assert outcome.order.risk_decision_id == outcome.decision.id

    def test_a_sell_signal_opens_a_short(self, pipeline):
        outcome = pipeline.handle_signal(
            signal(action=SignalAction.SELL), quantity=Decimal("0.05")
        )
        assert outcome.executed
        assert pipeline.portfolio.position("BTCUSDT").signed_quantity == Decimal("-0.05")

    def test_cash_and_commission_are_applied(self, pipeline):
        before = pipeline.portfolio.cash
        pipeline.handle_signal(signal(), quantity=Decimal("0.05"))
        assert pipeline.portfolio.cash < before
        assert pipeline.portfolio.total_commission > 0


class TestReducedFlow:
    def test_the_order_carries_the_approved_size_not_the_requested_one(self, pipeline):
        outcome = pipeline.handle_signal(signal(), quantity=Decimal("0.5"))

        assert outcome.decision.action is RiskAction.REDUCE
        assert outcome.order.quantity == outcome.decision.approved_quantity
        assert outcome.order.quantity < Decimal("0.5")
        assert outcome.executed


class TestRejectedFlow:
    def test_a_rejection_produces_no_order(self, pipeline):
        outcome = pipeline.handle_signal(signal(), quantity=Decimal("50"))

        assert outcome.rejected
        assert outcome.order is None
        assert outcome.fills == []
        assert pipeline.portfolio.position("BTCUSDT").is_flat

    def test_a_rejection_is_recorded_with_its_reasons(self, pipeline):
        """Rejections are results, not absences: the dashboard reads them."""
        outcome = pipeline.handle_signal(signal(), quantity=Decimal("50"))

        assert outcome in pipeline.history
        assert outcome in pipeline.rejections
        assert outcome.reasons
        assert "Position size exceeds" in outcome.describe()

    def test_a_halted_account_trades_nothing(self, broker, btc):
        """Past the daily loss budget, every signal is refused."""
        portfolio = Portfolio("100000")
        pipeline = TradingPipeline(
            RiskEngine(RiskLimits(max_daily_loss_pct=Decimal("0.001"))),
            broker,
            portfolio,
            instruments={"BTCUSDT": btc},
        )
        # Realise a loss to breach the budget.
        pipeline.handle_signal(signal(), quantity=Decimal("0.05"))
        broker.set_mark("BTCUSDT", "50000")
        pipeline.handle_signal(signal(action=SignalAction.SELL), quantity=Decimal("0.05"))

        broker.set_mark("BTCUSDT", "60000")
        outcome = pipeline.handle_signal(signal(), quantity=Decimal("0.01"))
        assert outcome.rejected
        assert any("Daily loss" in r for r in outcome.reasons)


class TestHoldSignals:
    def test_a_hold_signal_is_recorded_but_not_assessed(self, pipeline):
        outcome = pipeline.handle_signal(
            signal(action=SignalAction.HOLD, strength="0")
        )
        assert outcome.decision is None
        assert outcome.order is None
        assert outcome in pipeline.history
        assert not outcome.executed


class TestSizing:
    def test_quantity_is_proposed_from_equity_and_confidence(self, pipeline):
        """The proposal is only a starting point; risk still governs."""
        strong = pipeline._proposed_quantity(signal(strength="1"))
        weak = pipeline._proposed_quantity(signal(strength="0.25"))
        assert strong > weak
        assert weak > 0

    def test_proposed_size_is_rounded_to_the_venue_step(self, pipeline, btc):
        qty = pipeline._proposed_quantity(signal())
        assert qty == btc.round_quantity(qty)

    def test_an_automatic_proposal_still_passes_through_risk(self, pipeline):
        outcome = pipeline.handle_signal(signal())
        assert outcome.decision is not None


class TestExecutionFailure:
    def test_a_broker_error_is_captured_not_raised(self, btc):
        """A venue failure must not lose the signal or corrupt the portfolio."""
        broker = PaperBroker(instruments={"BTCUSDT": btc})  # no mark set
        pipeline = TradingPipeline(
            RiskEngine(), broker, Portfolio("100000"), instruments={"BTCUSDT": btc}
        )
        outcome = pipeline.handle_signal(signal(), quantity=Decimal("0.05"))

        assert outcome.error is not None
        assert outcome.order is None
        assert pipeline.portfolio.position("BTCUSDT").is_flat
        assert outcome in pipeline.history


class TestHistory:
    def test_every_signal_produces_an_outcome(self, pipeline):
        pipeline.handle_signal(signal(), quantity=Decimal("0.05"))          # approve
        pipeline.handle_signal(signal(), quantity=Decimal("50"))            # reject
        pipeline.handle_signal(signal(action=SignalAction.HOLD, strength="0"))  # hold

        assert len(pipeline.history) == 3
        assert len(pipeline.executions) == 1
        assert len(pipeline.rejections) == 1

    def test_idempotent_replay_does_not_double_the_position(self, pipeline):
        """The same signal handled twice must not open two positions."""
        sig = signal()
        first = pipeline.handle_signal(sig, quantity=Decimal("0.05"))
        # Re-submitting the very same order object is what a retry looks like.
        pipeline.broker.submit(first.order)
        assert len(pipeline.broker.all_fills) == 1


class TestZeroStrengthSizing:
    def test_a_zero_strength_signal_proposes_zero_not_full_size(self, pipeline):
        """Regression: `strength or D("1")` treated Decimal("0") as falsy,
        silently turning the weakest possible signal into the largest one.
        """
        weak = signal(strength="0")
        outcome = pipeline.handle_signal(weak)
        assert outcome.error == "proposed quantity is zero"
        assert outcome.order is None

    def test_proposed_size_scales_linearly_with_strength(self, pipeline):
        full = pipeline._proposed_quantity(signal(strength="1"))
        half = pipeline._proposed_quantity(signal(strength="0.5"))
        # Approximately half: exchange-step rounding prevents an exact ratio.
        assert abs(half - full / 2) <= Decimal("0.001")
