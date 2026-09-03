"""The individual risk checks.

Each check is independent, pure, and answers one question about a proposed
trade. A check reports:

* whether the trade passes it,
* a 0-100 risk contribution (not a boolean, so the engine can grade severity),
* the number it observed and the limit it compared against,
* a reason, generated from those two numbers rather than written by hand.

Because reasons are derived, the explanation shown to a user cannot drift out
of sync with the arithmetic that produced the verdict.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from app.core.money import ZERO, notional
from app.domain import RiskCheckResult, Side
from app.risk.limits import AccountSnapshot, RiskLimits


class RiskCheck(ABC):
    """One dimension of risk."""

    name: str = "check"
    weight: Decimal = Decimal("1")

    @abstractmethod
    def evaluate(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        account: AccountSnapshot,
        limits: RiskLimits,
    ) -> RiskCheckResult:
        """Assess the proposed trade on this dimension."""

    # --- helpers -------------------------------------------------------

    def _result(
        self,
        *,
        passed: bool,
        score: Decimal,
        observed: Decimal | None = None,
        limit: Decimal | None = None,
        reason: str = "",
    ) -> RiskCheckResult:
        return RiskCheckResult(
            name=self.name,
            passed=passed,
            score=_clamp_score(score),
            weight=self.weight,
            observed=observed,
            limit=limit,
            reason=reason,
        )

    @staticmethod
    def _ratio_score(observed: Decimal, limit: Decimal) -> Decimal:
        """Grade utilisation of a limit onto 0-100.

        At the limit exactly the score is 75 — the default rejection
        threshold — so a trade that lands precisely on a boundary is refused
        rather than admitted by a rounding accident. Beyond the limit the score
        climbs to 100.
        """
        if limit <= ZERO:
            return Decimal("100")
        utilisation = observed / limit
        if utilisation <= 1:
            return utilisation * Decimal("75")
        return min(Decimal("100"), Decimal("75") + (utilisation - 1) * Decimal("50"))


def _clamp_score(value: Decimal) -> Decimal:
    return max(ZERO, min(Decimal("100"), value))


def _pct(value: Decimal) -> str:
    """Render a fraction as a percentage for human-readable reasons."""
    return f"{value * 100:.1f}%"


class PositionSizeCheck(RiskCheck):
    """Caps a single position as a fraction of equity."""

    name = "position_size"
    weight = Decimal("1.5")

    def evaluate(self, *, symbol, side, quantity, price, account, limits):
        # The resulting position, not just the incremental order: adding to an
        # existing position is what actually breaches a size cap.
        existing = account.position(symbol)
        delta = side.sign * quantity
        resulting = abs(existing.signed_quantity + delta)

        value = notional(resulting, price)
        pct = value / account.equity
        limit = limits.max_position_pct

        passed = pct <= limit
        return self._result(
            passed=passed,
            score=self._ratio_score(pct, limit),
            observed=pct,
            limit=limit,
            reason=(
                f"Position size exceeds limit: {_pct(pct)} of equity "
                f"against a {_pct(limit)} cap"
                if not passed
                else ""
            ),
        )


class PortfolioExposureCheck(RiskCheck):
    """Caps total gross exposure across all positions."""

    name = "portfolio_exposure"
    weight = Decimal("1.2")

    def evaluate(self, *, symbol, side, quantity, price, account, limits):
        projected = account.gross_exposure + notional(quantity, price)
        pct = projected / account.equity
        limit = limits.max_portfolio_exposure_pct

        passed = pct <= limit
        return self._result(
            passed=passed,
            score=self._ratio_score(pct, limit),
            observed=pct,
            limit=limit,
            reason=(
                f"High portfolio exposure: {_pct(pct)} of equity "
                f"against a {_pct(limit)} cap"
                if not passed
                else ""
            ),
        )


class LeverageCheck(RiskCheck):
    """Caps gross exposure divided by equity."""

    name = "leverage"
    weight = Decimal("1.2")

    def evaluate(self, *, symbol, side, quantity, price, account, limits):
        projected = (account.gross_exposure + notional(quantity, price)) / account.equity
        limit = limits.max_leverage

        passed = projected <= limit
        return self._result(
            passed=passed,
            score=self._ratio_score(projected, limit),
            observed=projected,
            limit=limit,
            reason=(
                f"Leverage would reach {projected:.2f}x against a {limit:.2f}x cap"
                if not passed
                else ""
            ),
        )


class DailyLossCheck(RiskCheck):
    """Stops trading once the day's loss budget is spent.

    Independent of the trade being proposed: past a daily loss limit the
    correct answer is to stop for the day, whatever the next idea looks like.
    """

    name = "daily_loss"
    weight = Decimal("2.0")

    def evaluate(self, *, symbol, side, quantity, price, account, limits):
        loss = account.daily_loss_pct
        limit = limits.max_daily_loss_pct

        passed = loss < limit
        return self._result(
            passed=passed,
            score=self._ratio_score(loss, limit),
            observed=loss,
            limit=limit,
            reason=(
                f"Daily loss limit reached: down {_pct(loss)} today "
                f"against a {_pct(limit)} budget"
                if not passed
                else ""
            ),
        )


class DrawdownCheck(RiskCheck):
    """Stops trading after a deep peak-to-trough decline."""

    name = "drawdown"
    weight = Decimal("2.0")

    def evaluate(self, *, symbol, side, quantity, price, account, limits):
        drawdown = account.drawdown
        limit = limits.max_drawdown_pct

        passed = drawdown < limit
        return self._result(
            passed=passed,
            score=self._ratio_score(drawdown, limit),
            observed=drawdown,
            limit=limit,
            reason=(
                f"Drawdown of {_pct(drawdown)} exceeds the {_pct(limit)} limit"
                if not passed
                else ""
            ),
        )


class VolatilityCheck(RiskCheck):
    """Penalises trading an unusually volatile instrument.

    Missing volatility is treated as mildly risky rather than safe: absence of
    a measurement is not evidence of calm.
    """

    name = "volatility"
    weight = Decimal("1.0")

    def evaluate(self, *, symbol, side, quantity, price, account, limits):
        volatility = account.volatility
        limit = limits.max_volatility

        if volatility is None:
            return self._result(
                passed=True,
                score=Decimal("25"),
                limit=limit,
                reason="",
            )

        passed = volatility <= limit
        return self._result(
            passed=passed,
            score=self._ratio_score(volatility, limit),
            observed=volatility,
            limit=limit,
            reason=(
                f"Excessive volatility: {_pct(volatility)} annualised "
                f"against a {_pct(limit)} ceiling"
                if not passed
                else ""
            ),
        )


class OrderValueCheck(RiskCheck):
    """Hard ceiling on a single order's notional.

    A backstop against a fat-fingered or miscomputed quantity, independent of
    percentage-based limits.
    """

    name = "order_value"
    weight = Decimal("1.0")

    def evaluate(self, *, symbol, side, quantity, price, account, limits):
        value = notional(quantity, price)
        limit = limits.max_order_value

        passed = value <= limit
        return self._result(
            passed=passed,
            score=self._ratio_score(value, limit),
            observed=value,
            limit=limit,
            reason=(
                f"Order value {value:,.2f} exceeds the {limit:,.2f} maximum"
                if not passed
                else ""
            ),
        )


#: Evaluated in this order; the order affects only how reasons are listed.
DEFAULT_CHECKS: tuple[RiskCheck, ...] = (
    PositionSizeCheck(),
    PortfolioExposureCheck(),
    LeverageCheck(),
    DailyLossCheck(),
    DrawdownCheck(),
    VolatilityCheck(),
    OrderValueCheck(),
)
