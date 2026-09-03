"""The risk engine: scoring, verdicts and position sizing."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.domain import (
    Fill,
    Position,
    RiskAction,
    Side,
    Signal,
    SignalAction,
)
from app.risk import AccountSnapshot, RiskEngine, RiskLimits

EQUITY = Decimal("100000")
PRICE = Decimal("60000")


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine()


def account(**kwargs) -> AccountSnapshot:
    base = {"equity": EQUITY, "cash": EQUITY, "volatility": Decimal("0.4")}
    return AccountSnapshot(**{**base, **kwargs})


def assess(engine, qty: str, acct=None, side=Side.BUY, instrument=None):
    return engine.assess(
        symbol="BTCUSDT",
        side=side,
        quantity=Decimal(qty),
        price=PRICE,
        account=acct or account(),
        instrument=instrument,
    )


class TestVerdicts:
    def test_a_modest_trade_on_a_clean_account_is_approved(self, engine):
        decision = assess(engine, "0.05")
        assert decision.action is RiskAction.APPROVE
        assert decision.approved_quantity == Decimal("0.05")
        assert decision.reasons == ()

    def test_an_oversized_trade_is_reduced(self, engine):
        decision = assess(engine, "1")
        assert decision.action is RiskAction.REDUCE
        assert 0 < decision.approved_quantity < Decimal("1")
        assert any("Position size exceeds" in r for r in decision.reasons)

    def test_a_grossly_oversized_trade_is_rejected(self, engine):
        decision = assess(engine, "50")
        assert decision.action is RiskAction.REJECT
        assert decision.approved_quantity == 0

    def test_score_is_bounded_and_integral(self, engine):
        for qty in ("0.001", "0.1", "1", "10", "100"):
            score = assess(engine, qty).score
            assert Decimal(0) <= score <= Decimal(100)
            assert score == score.to_integral_value()


class TestHardChecks:
    """Some limits are categorical and must not be averaged away."""

    def test_daily_loss_rejects_despite_a_low_blended_score(self, engine):
        acct = account(daily_pnl=Decimal("-8000"))
        decision = assess(engine, "0.001", acct)
        assert decision.action is RiskAction.REJECT
        assert decision.score < engine.limits.reject_score
        assert any("Daily loss limit" in r for r in decision.reasons)

    def test_drawdown_rejects_despite_a_low_blended_score(self, engine):
        acct = account(equity=Decimal("70000"), cash=Decimal("70000"), peak_equity=EQUITY)
        decision = assess(engine, "0.001", acct)
        assert decision.action is RiskAction.REJECT
        assert decision.score < engine.limits.reject_score

    def test_a_soft_failure_alone_does_not_reject(self, engine):
        """Volatility is gradual, so it reduces rather than refuses."""
        acct = account(volatility=Decimal("2.0"))
        decision = assess(engine, "0.05", acct)
        assert decision.action is RiskAction.REDUCE

    def test_hard_check_set_is_configurable(self):
        permissive = RiskEngine(hard_checks=frozenset())
        acct = account(daily_pnl=Decimal("-8000"))
        decision = permissive.assess(
            symbol="BTCUSDT",
            side=Side.BUY,
            quantity=Decimal("0.001"),
            price=PRICE,
            account=acct,
        )
        assert decision.action is not RiskAction.REJECT


class TestSizing:
    """A REDUCE must produce a size that actually satisfies the binding limit."""

    def test_reduced_size_clears_the_check_that_failed(self, engine):
        first = assess(engine, "1")
        assert first.action is RiskAction.REDUCE

        # Re-assessing at the approved size must no longer breach position size.
        second = assess(engine, str(first.approved_quantity))
        breached = {c.name for c in second.failed_checks}
        assert "position_size" not in breached

    def test_reduced_size_respects_the_tightest_binding_limit(self, engine):
        """Order value binds before position size at this equity."""
        decision = assess(engine, "1")
        value = decision.approved_quantity * PRICE
        assert value <= engine.limits.max_order_value
        assert value <= engine.limits.max_position_pct * EQUITY

    def test_exposure_headroom_governs_when_it_is_tightest(self, engine):
        held = Position.flat("ETHUSDT").apply_fill(
            Fill(
                order_id=uuid.uuid4(),
                symbol="ETHUSDT",
                side=Side.BUY,
                quantity=Decimal("11"),
                price=Decimal("5000"),
            )
        )
        acct = account(positions=(held,), mark_prices={"ETHUSDT": Decimal("5000")})
        decision = assess(engine, "0.5", acct)
        if decision.action is RiskAction.REDUCE:
            projected = acct.gross_exposure + decision.approved_quantity * PRICE
            assert projected <= engine.limits.max_portfolio_exposure_pct * EQUITY

    def test_reduce_is_strictly_smaller_than_requested(self, engine):
        for qty in ("0.2", "0.5", "1", "2", "5"):
            decision = assess(engine, qty)
            if decision.action is RiskAction.REDUCE:
                assert decision.approved_quantity < Decimal(qty)
                assert decision.approved_quantity > 0

    def test_size_is_rounded_to_the_exchange_step(self, engine, btc):
        decision = assess(engine, "1", instrument=btc)
        if decision.action is RiskAction.REDUCE:
            assert decision.approved_quantity == btc.round_quantity(
                decision.approved_quantity
            )

    def test_a_size_below_the_venue_minimum_becomes_a_rejection(self, engine, btc):
        """Sizing down to something untradeable is a refusal, not a zero fill.

        A 100 cap at a 60,000 price allows 0.00167 BTC, which rounds down to
        the 0.001 step and is then worth 60 -- under the venue's 100 minimum
        notional. There is no legal order here, so the answer is REJECT.
        """
        tight = RiskEngine(limits=RiskLimits(max_order_value=Decimal("100")))
        decision = tight.assess(
            symbol="BTCUSDT",
            side=Side.BUY,
            quantity=Decimal("0.005"),  # 3x the cap: a breach, not a fat finger
            price=PRICE,
            account=account(),
            instrument=btc,
        )
        assert decision.action is RiskAction.REJECT
        assert decision.approved_quantity == 0
        assert any("No tradeable size" in r for r in decision.reasons)


class TestGrossBreach:
    """A request far past a limit is treated as an error, not an intention."""

    def test_a_mild_breach_is_sized_down(self, engine):
        # 0.5 BTC = 30,000 = 3x the 10% position cap. Plausibly intended.
        decision = assess(engine, "0.5")
        assert decision.action is RiskAction.REDUCE

    def test_an_extreme_breach_is_refused(self, engine):
        """Silently filling 0.3% of what was asked is the dangerous answer.

        The trader may not notice the difference and simply resubmit.
        """
        decision = assess(engine, "50")  # 300x the position cap
        assert decision.action is RiskAction.REJECT
        assert decision.approved_quantity == 0

    def test_it_rejects_even_when_the_blended_score_is_moderate(self, engine):
        """The failure a weighted mean cannot express.

        Three limits maxed out and four passing averages to a middling score,
        which would otherwise read as merely "reduce".
        """
        decision = assess(engine, "50")
        assert decision.score < engine.limits.reject_score
        assert decision.action is RiskAction.REJECT

    def test_the_threshold_is_configurable(self):
        lenient = RiskEngine(limits=RiskLimits(gross_breach_multiple=Decimal("1000")))
        decision = lenient.assess(
            symbol="BTCUSDT",
            side=Side.BUY,
            quantity=Decimal("50"),
            price=PRICE,
            account=account(),
        )
        assert decision.action is RiskAction.REDUCE

    def test_utilisation_is_reported_per_check(self, engine):
        decision = assess(engine, "50")
        size_check = next(c for c in decision.checks if c.name == "position_size")
        # 3,000,000 notional against a 10,000 cap.
        assert size_check.utilisation == Decimal("300")

    def test_a_check_without_a_ratio_has_no_utilisation(self, engine):
        decision = assess(engine, "0.05", account(volatility=None))
        volatility = next(c for c in decision.checks if c.name == "volatility")
        assert volatility.observed is None
        assert volatility.utilisation is None


class TestDecisionRecord:
    def test_every_check_is_recorded_even_when_it_passes(self, engine):
        decision = assess(engine, "0.05")
        assert len(decision.checks) == len(engine.checks)
        assert {c.name for c in decision.checks} == {c.name for c in engine.checks}

    def test_reasons_come_only_from_failures(self, engine):
        decision = assess(engine, "5")
        assert len(decision.reasons) == len(decision.failed_checks)
        assert all(r for r in decision.reasons)

    def test_observations_are_retained_for_audit(self, engine):
        decision = assess(engine, "5")
        size_check = next(c for c in decision.checks if c.name == "position_size")
        assert size_check.observed is not None
        assert size_check.limit == engine.limits.max_position_pct

    def test_summary_matches_the_operator_format(self, engine):
        decision = assess(engine, "50")
        text = decision.summary()
        assert text.startswith("Risk Score: ")
        assert "Decision: REJECT" in text
        assert "Reasons:" in text


class TestSignalIntegration:
    def test_assesses_a_strategy_signal(self, engine, buy_signal):
        decision = engine.assess_signal(
            buy_signal, quantity=Decimal("0.05"), account=account()
        )
        assert decision.signal_id == buy_signal.id
        assert decision.action is RiskAction.APPROVE

    def test_a_hold_signal_cannot_be_traded(self, engine, bar):
        hold = Signal(
            strategy="rsi",
            symbol="BTCUSDT",
            action=SignalAction.HOLD,
            strength=Decimal("0"),
            reference_price=bar.close,
            bar_close_time=bar.close_time,
        )
        with pytest.raises(ValueError, match="HOLD signal cannot be assessed"):
            engine.assess_signal(hold, quantity=Decimal("0.05"), account=account())

    def test_signal_price_is_used_for_the_assessment(self, engine, buy_signal):
        decision = engine.assess_signal(
            buy_signal, quantity=Decimal("0.05"), account=account()
        )
        size_check = next(c for c in decision.checks if c.name == "position_size")
        expected = Decimal("0.05") * buy_signal.reference_price / EQUITY
        assert size_check.observed == expected


class TestInputValidation:
    @pytest.mark.parametrize("qty", ["0", "-1"])
    def test_non_positive_quantity_is_refused(self, engine, qty):
        with pytest.raises(ValueError, match="quantity must be positive"):
            assess(engine, qty)

    def test_non_positive_price_is_refused(self, engine):
        with pytest.raises(ValueError, match="price must be positive"):
            engine.assess(
                symbol="BTCUSDT",
                side=Side.BUY,
                quantity=Decimal("1"),
                price=Decimal("0"),
                account=account(),
            )


class TestInvariantHolds:
    """The decision invariant must survive every scenario the engine produces."""

    @pytest.mark.parametrize("qty", ["0.001", "0.05", "0.2", "1", "5", "50", "500"])
    @pytest.mark.parametrize(
        "state",
        [
            {},
            {"daily_pnl": Decimal("-8000")},
            {"equity": Decimal("70000"), "cash": Decimal("70000"), "peak_equity": EQUITY},
            {"volatility": Decimal("3.0")},
        ],
        ids=["clean", "daily_loss", "drawdown", "volatile"],
    )
    def test_verdict_and_size_always_agree(self, engine, qty, state):
        decision = assess(engine, qty, account(**state))

        if decision.action is RiskAction.REJECT:
            assert decision.approved_quantity == 0
        elif decision.action is RiskAction.APPROVE:
            assert decision.approved_quantity == Decimal(qty)
        else:
            assert 0 < decision.approved_quantity < Decimal(qty)
