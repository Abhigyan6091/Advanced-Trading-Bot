"""Individual risk checks, exercised at their boundaries.

Boundary behaviour is the whole point of a limit, so each check is tested just
inside, exactly at, and just outside its threshold.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.domain import Fill, Position, Side
from app.risk import (
    AccountSnapshot,
    DailyLossCheck,
    DrawdownCheck,
    LeverageCheck,
    OrderValueCheck,
    PortfolioExposureCheck,
    PositionSizeCheck,
    RiskLimits,
    VolatilityCheck,
)

LIMITS = RiskLimits()
EQUITY = Decimal("100000")


def account(**kwargs) -> AccountSnapshot:
    base = {"equity": EQUITY, "cash": EQUITY}
    return AccountSnapshot(**{**base, **kwargs})


def position(symbol: str, side: Side, qty: str, price: str) -> Position:
    return Position.flat(symbol).apply_fill(
        Fill(
            order_id=uuid.uuid4(),
            symbol=symbol,
            side=side,
            quantity=Decimal(qty),
            price=Decimal(price),
        )
    )


def run(check, *, qty: str, price: str = "60000", acct=None, side=Side.BUY):
    return check.evaluate(
        symbol="BTCUSDT",
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        account=acct or account(),
        limits=LIMITS,
    )


class TestPositionSize:
    check = PositionSizeCheck()

    @pytest.mark.parametrize(
        ("qty", "expected_pass"),
        [
            ("0.16", True),   # 9,600 = 9.6% of equity, under the 10% cap
            ("0.1666", True), # 9,996 = 9.996%, just inside
            ("0.16667", False),  # 10,000.2, just over
            ("0.5", False),   # 30%, far over
        ],
    )
    def test_boundary(self, qty, expected_pass):
        assert run(self.check, qty=qty).passed is expected_pass

    def test_exactly_at_the_limit_passes(self):
        # 10% of 100,000 = 10,000 -> 10,000/60,000 BTC
        qty = LIMITS.max_position_pct * EQUITY / Decimal("60000")
        assert run(self.check, qty=str(qty)).passed

    def test_counts_the_resulting_position_not_just_the_order(self):
        """Adding to an existing position is what breaches a size cap."""
        held = position("BTCUSDT", Side.BUY, "0.15", "60000")
        acct = account(positions=(held,), mark_prices={"BTCUSDT": Decimal("60000")})
        # 0.05 alone is fine; on top of 0.15 it is not.
        assert run(self.check, qty="0.05").passed
        assert not run(self.check, qty="0.05", acct=acct).passed

    def test_reducing_an_existing_position_is_allowed(self):
        """Selling into a long shrinks it, so the cap must not block the exit."""
        held = position("BTCUSDT", Side.BUY, "0.2", "60000")
        acct = account(positions=(held,), mark_prices={"BTCUSDT": Decimal("60000")})
        assert run(self.check, qty="0.1", acct=acct, side=Side.SELL).passed

    def test_reason_is_derived_from_the_numbers(self):
        result = run(self.check, qty="0.5")
        assert "30.0% of equity" in result.reason
        assert "10.0% cap" in result.reason

    def test_passing_check_carries_no_reason(self):
        assert run(self.check, qty="0.1").reason == ""

    def test_reports_what_it_observed_and_compared_against(self):
        result = run(self.check, qty="0.5")
        assert result.observed == Decimal("0.3")
        assert result.limit == LIMITS.max_position_pct


class TestPortfolioExposure:
    check = PortfolioExposureCheck()

    def test_passes_within_budget(self):
        assert run(self.check, qty="0.1").passed

    def test_counts_existing_exposure(self):
        held = position("ETHUSDT", Side.BUY, "10", "5000")  # 50,000 = 50%
        acct = account(positions=(held,), mark_prices={"ETHUSDT": Decimal("5000")})
        # Adding 12% more exceeds the 60% cap.
        assert not run(self.check, qty="0.2", acct=acct).passed

    def test_shorts_add_to_gross_exposure(self):
        """A long and a short are two risks, not a flat book."""
        long_p = position("ETHUSDT", Side.BUY, "6", "5000")
        short_p = position("SOLUSDT", Side.SELL, "200", "150")
        acct = account(
            positions=(long_p, short_p),
            mark_prices={"ETHUSDT": Decimal("5000"), "SOLUSDT": Decimal("150")},
        )
        assert acct.gross_exposure == Decimal("60000")
        assert not run(self.check, qty="0.1", acct=acct).passed


class TestLeverage:
    check = LeverageCheck()

    def test_within_leverage_passes(self):
        assert run(self.check, qty="0.1").passed

    def test_beyond_leverage_fails_with_a_multiplier_in_the_reason(self):
        held = position("ETHUSDT", Side.BUY, "58", "5000")  # 290,000 = 2.9x
        acct = account(positions=(held,), mark_prices={"ETHUSDT": Decimal("5000")})
        result = run(self.check, qty="0.5", acct=acct)
        assert not result.passed
        assert "x cap" in result.reason


class TestDailyLoss:
    check = DailyLossCheck()

    @pytest.mark.parametrize(
        ("pnl", "expected_pass"),
        [
            ("1000", True),    # profitable
            ("0", True),
            ("-4999", True),   # just inside the 5% budget
            ("-5000", False),  # exactly at the limit stops trading
            ("-8000", False),
        ],
    )
    def test_boundary(self, pnl, expected_pass):
        acct = account(daily_pnl=Decimal(pnl))
        assert run(self.check, qty="0.01", acct=acct).passed is expected_pass

    def test_profit_reports_zero_loss(self):
        assert account(daily_pnl=Decimal("5000")).daily_loss_pct == 0

    def test_verdict_is_independent_of_trade_size(self):
        """Past the budget, the answer is stop for the day regardless."""
        acct = account(daily_pnl=Decimal("-8000"))
        assert not run(self.check, qty="0.00001", acct=acct).passed


class TestDrawdown:
    check = DrawdownCheck()

    @pytest.mark.parametrize(
        ("equity", "peak", "expected_pass"),
        [
            ("100000", "100000", True),   # at the high
            ("81000", "100000", True),    # 19% down, inside
            ("80000", "100000", False),   # exactly 20%
            ("60000", "100000", False),   # 40%
            ("120000", "100000", True),   # new high
        ],
    )
    def test_boundary(self, equity, peak, expected_pass):
        acct = account(equity=Decimal(equity), cash=Decimal(equity), peak_equity=Decimal(peak))
        assert run(self.check, qty="0.01", acct=acct).passed is expected_pass

    def test_absent_peak_means_no_drawdown(self):
        assert account().drawdown == 0


class TestVolatility:
    check = VolatilityCheck()

    def test_calm_market_passes(self):
        assert run(self.check, qty="0.1", acct=account(volatility=Decimal("0.5"))).passed

    def test_excessive_volatility_fails(self):
        result = run(self.check, qty="0.1", acct=account(volatility=Decimal("2.0")))
        assert not result.passed
        assert "Excessive volatility" in result.reason

    def test_unknown_volatility_passes_but_is_not_scored_as_safe(self):
        """Absence of a measurement is not evidence of calm."""
        result = run(self.check, qty="0.1", acct=account())
        assert result.passed
        assert result.score == Decimal("25")
        assert result.observed is None


class TestOrderValue:
    check = OrderValueCheck()

    @pytest.mark.parametrize(
        ("qty", "expected_pass"),
        [("0.8", True), ("0.833333", True), ("0.9", False), ("2", False)],
    )
    def test_boundary(self, qty, expected_pass):
        # 50,000 cap / 60,000 price -> 0.8333 BTC
        assert run(self.check, qty=qty).passed is expected_pass

    def test_backstops_a_fat_finger(self):
        result = run(self.check, qty="100")
        assert not result.passed
        assert result.score == Decimal("100")


class TestScoring:
    def test_scores_stay_within_0_100(self):
        for qty in ("0.000001", "0.1", "1", "1000", "100000"):
            result = run(PositionSizeCheck(), qty=qty)
            assert Decimal(0) <= result.score <= Decimal(100)

    def test_score_rises_with_utilisation(self):
        scores = [run(PositionSizeCheck(), qty=q).score for q in ("0.05", "0.1", "0.15", "0.5")]
        assert scores == sorted(scores)

    def test_exactly_at_the_limit_scores_at_the_rejection_threshold(self):
        """A boundary trade must not be admitted by a rounding accident."""
        qty = LIMITS.max_position_pct * EQUITY / Decimal("60000")
        assert run(PositionSizeCheck(), qty=str(qty)).score == Decimal("75")


class TestLimitsValidation:
    def test_reduce_threshold_must_sit_below_reject(self):
        with pytest.raises(ValueError, match="reduce_score must be below reject_score"):
            RiskLimits(reduce_score=Decimal("80"), reject_score=Decimal("75"))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_position_pct": Decimal("0")},
            {"max_position_pct": Decimal("1.5")},
            {"max_leverage": Decimal("0.5")},
            {"max_order_value": Decimal("-1")},
        ],
    )
    def test_nonsensical_limits_are_refused(self, kwargs):
        with pytest.raises(ValueError):
            RiskLimits(**kwargs)

    def test_defaults_are_conservative(self):
        limits = RiskLimits()
        assert limits.max_position_pct <= Decimal("0.10")
        assert limits.max_leverage <= Decimal("3")
        assert limits.max_daily_loss_pct <= Decimal("0.05")


class TestExposureAndLeverageIgnoreClosingTrades:
    """A closing or de-risking order must not be scored as adding exposure.

    Regression coverage for a defect where PortfolioExposureCheck and
    LeverageCheck added the order's notional to gross exposure with no regard
    for direction or the existing position, so an order that FLATTENED an
    over-exposed book was refused or cut down to almost nothing -- precisely
    the trade that should always be allowed through.
    """

    def test_flattening_an_over_exposed_position_passes_exposure(self):
        held = position("BTCUSDT", Side.BUY, "0.55", "100000")  # 55% of equity
        acct = account(positions=(held,), mark_prices={"BTCUSDT": Decimal("100000")})
        closing = run(PortfolioExposureCheck(), qty="0.55", acct=acct, side=Side.SELL)
        assert closing.passed
        assert closing.observed == Decimal("0")

    def test_flattening_passes_leverage_too(self):
        held = position("BTCUSDT", Side.BUY, "0.55", "100000")
        acct = account(positions=(held,), mark_prices={"BTCUSDT": Decimal("100000")})
        closing = run(LeverageCheck(), qty="0.55", acct=acct, side=Side.SELL)
        assert closing.passed

    def test_reducing_partially_still_reads_the_smaller_resulting_exposure(self):
        held = position("BTCUSDT", Side.BUY, "0.55", "100000")
        acct = account(positions=(held,), mark_prices={"BTCUSDT": Decimal("100000")})
        # Selling 0.45 of the 0.55 leaves 0.10 BTC @100,000 = 10% of equity,
        # not 55%+45%=100% as the naive addition would have scored it.
        result = run(
            PortfolioExposureCheck(), qty="0.45", price="100000", acct=acct, side=Side.SELL
        )
        assert result.observed == Decimal("0.10")

    def test_opening_a_new_position_is_still_measured_correctly(self):
        """The fix must not break the ordinary opening case."""
        result = run(PortfolioExposureCheck(), qty="0.1")
        assert result.observed == Decimal("0.1") * Decimal("60000") / EQUITY

    def test_other_symbols_exposure_is_unaffected_by_this_symbols_trade(self):
        eth = position("ETHUSDT", Side.BUY, "10", "5000")  # 50,000 = 50%
        acct = account(positions=(eth,), mark_prices={"ETHUSDT": Decimal("5000")})
        # Trading BTC must add on top of ETH's 50%, not replace or ignore it.
        result = run(PortfolioExposureCheck(), qty="0.1", acct=acct)
        assert result.observed == (Decimal("50000") + Decimal("6000")) / EQUITY
