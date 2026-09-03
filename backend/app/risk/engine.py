"""The risk engine.

Every proposed trade passes through here, and nothing else in the platform is
permitted to construct an order. The engine combines independent checks into a
single 0-100 score and one of three verdicts:

* **APPROVE** — trade at the requested size.
* **REDUCE**  — trade, but at a size that brings the binding limit back inside
  its budget.
* **REJECT**  — do not trade.

Two rules govern how the verdict is reached, and they are deliberately not
symmetrical:

1. Any **hard** check that fails rejects outright, whatever the blended score
   says. A daily loss limit is not something a good score should be able to
   average away.
2. Otherwise the weighted score decides, against configured thresholds.

Rule 1 exists because a weighted average is a poor instrument for a
constraint that is categorical rather than gradual.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from app.core.logging import get_logger
from app.core.money import ZERO, notional
from app.domain import (
    Instrument,
    RiskAction,
    RiskCheckResult,
    RiskDecision,
    Side,
    Signal,
    SignalAction,
)
from app.risk.checks import DEFAULT_CHECKS, RiskCheck
from app.risk.limits import AccountSnapshot, RiskLimits

log = get_logger(__name__)

#: Checks whose failure rejects regardless of the blended score. These describe
#: states in which the account should not be trading at all, rather than
#: qualities of the individual trade.
HARD_CHECKS: frozenset[str] = frozenset({"daily_loss", "drawdown"})


class RiskEngine:
    """Scores proposed trades and decides whether they may proceed."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        checks: tuple[RiskCheck, ...] = DEFAULT_CHECKS,
        hard_checks: frozenset[str] = HARD_CHECKS,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.checks = checks
        self.hard_checks = hard_checks

    # --- public API ----------------------------------------------------

    def assess(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        account: AccountSnapshot,
        signal_id: uuid.UUID | None = None,
        instrument: Instrument | None = None,
        now: datetime | None = None,
    ) -> RiskDecision:
        """Assess a proposed trade and return a persistable decision.

        ``now`` stamps the decision. A replay passes the bar's own time so the
        stored history spans the period it simulates rather than collapsing
        onto the moment the replay ran.
        """
        if quantity <= ZERO:
            raise ValueError("quantity must be positive")
        if price <= ZERO:
            raise ValueError("price must be positive")

        results = tuple(
            check.evaluate(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                account=account,
                limits=self.limits,
            )
            for check in self.checks
        )

        score = self._blend(results)
        action = self._verdict(score, results)
        approved = self._size(action, results, quantity, price, account, instrument)

        # Sizing can find no tradeable quantity — below the exchange minimum,
        # say. That is a rejection, not a zero-size approval.
        if action is RiskAction.REDUCE and approved <= ZERO:
            action = RiskAction.REJECT
            approved = ZERO
            results = (*results, self._unfundable_result())

        decision = RiskDecision(
            signal_id=signal_id or uuid.uuid4(),
            action=action,
            score=score,
            requested_quantity=quantity,
            approved_quantity=approved,
            checks=results,
            **({"created_at": now} if now is not None else {}),
        )

        log.info(
            "risk.decision",
            symbol=symbol,
            side=side.value,
            action=action.value,
            score=str(score),
            requested=str(quantity),
            approved=str(approved),
            failed=[c.name for c in decision.failed_checks],
        )
        return decision

    def assess_signal(
        self,
        signal: Signal,
        *,
        quantity: Decimal,
        account: AccountSnapshot,
        instrument: Instrument | None = None,
        now: datetime | None = None,
    ) -> RiskDecision:
        """Assess a strategy signal. HOLD signals are not tradeable."""
        if not signal.is_actionable:
            raise ValueError("a HOLD signal cannot be assessed for execution")
        return self.assess(
            symbol=signal.symbol,
            side=signal.action.to_side(),
            quantity=quantity,
            price=signal.reference_price,
            account=account,
            signal_id=signal.id,
            instrument=instrument,
            now=now,
        )

    # --- scoring -------------------------------------------------------

    def _blend(self, results: tuple[RiskCheckResult, ...]) -> Decimal:
        """Weighted mean of the individual check scores."""
        total_weight = sum((r.weight for r in results), ZERO)
        if total_weight == ZERO:
            return ZERO
        weighted = sum((r.score * r.weight for r in results), ZERO)
        return _clamp((weighted / total_weight).quantize(Decimal("1")))

    def _verdict(self, score: Decimal, results: tuple[RiskCheckResult, ...]) -> RiskAction:
        """Decide, applying two escalations the blended score cannot express.

        A weighted mean is the right instrument for combining comparable,
        gradual risks. It is the wrong one in two situations, so both are
        handled before the score is consulted:

        * a *categorical* limit failing (daily loss, drawdown) — the account
          should not be trading at all, and a good score elsewhere must not
          average that away;
        * a limit breached by a large *multiple* — a request 10x past its cap
          is more plausibly a mistake than an intention. Silently reinterpreting
          it as a 10%-sized order is the dangerous answer: the trader may not
          notice and may simply submit it again.
        """
        failed_hard = [r for r in results if not r.passed and r.name in self.hard_checks]
        if failed_hard:
            return RiskAction.REJECT

        if self._grossly_breached(results):
            return RiskAction.REJECT

        if score >= self.limits.reject_score:
            return RiskAction.REJECT
        if score >= self.limits.reduce_score or any(not r.passed for r in results):
            return RiskAction.REDUCE
        return RiskAction.APPROVE

    def _grossly_breached(self, results: tuple[RiskCheckResult, ...]) -> bool:
        limit = self.limits.gross_breach_multiple
        return any(
            not r.passed and r.utilisation is not None and r.utilisation > limit
            for r in results
        )

    # --- sizing --------------------------------------------------------

    def _size(
        self,
        action: RiskAction,
        results: tuple[RiskCheckResult, ...],
        quantity: Decimal,
        price: Decimal,
        account: AccountSnapshot,
        instrument: Instrument | None,
    ) -> Decimal:
        if action is RiskAction.REJECT:
            return ZERO
        if action is RiskAction.APPROVE:
            return quantity

        allowed = self._largest_permitted_quantity(results, quantity, price, account)
        allowed = min(allowed, quantity)

        if instrument is not None:
            # Round down to the exchange step, then confirm the result is still
            # a legal order. Rounding can push a size below the venue minimum.
            allowed = instrument.round_quantity(allowed)
            if not instrument.is_tradeable(allowed, price):
                return ZERO

        # A "reduction" to the full size is really an approval; the decision
        # model forbids REDUCE with an unchanged quantity, so step just below.
        if allowed >= quantity:
            allowed = quantity * Decimal("0.99")
            if instrument is not None:
                allowed = instrument.round_quantity(allowed)
                if not instrument.is_tradeable(allowed, price):
                    return ZERO
        return max(ZERO, allowed)

    def _largest_permitted_quantity(
        self,
        results: tuple[RiskCheckResult, ...],
        quantity: Decimal,
        price: Decimal,
        account: AccountSnapshot,
    ) -> Decimal:
        """Size down to the tightest binding limit.

        Each size-sensitive check implies a maximum quantity; the smallest of
        those governs. Checks that do not depend on size (drawdown, daily loss,
        volatility) cannot be sized around and are excluded.
        """
        caps: list[Decimal] = [quantity]

        by_name = {r.name: r for r in results}

        position = by_name.get("position_size")
        if position is not None and not position.passed:
            caps.append(self.limits.max_position_pct * account.equity / price)

        exposure = by_name.get("portfolio_exposure")
        if exposure is not None and not exposure.passed:
            headroom = (
                self.limits.max_portfolio_exposure_pct * account.equity
                - account.gross_exposure
            )
            caps.append(headroom / price)

        leverage = by_name.get("leverage")
        if leverage is not None and not leverage.passed:
            headroom = self.limits.max_leverage * account.equity - account.gross_exposure
            caps.append(headroom / price)

        order_value = by_name.get("order_value")
        if order_value is not None and not order_value.passed:
            caps.append(self.limits.max_order_value / price)

        # A soft REDUCE with nothing actually breached: trim rather than refuse.
        if len(caps) == 1:
            caps.append(quantity * Decimal("0.5"))

        return max(ZERO, min(caps))

    @staticmethod
    def _unfundable_result() -> RiskCheckResult:
        return RiskCheckResult(
            name="tradeable_size",
            passed=False,
            score=Decimal("100"),
            reason="No tradeable size remains after applying risk limits",
        )


def _clamp(value: Decimal) -> Decimal:
    return max(ZERO, min(Decimal("100"), value))


__all__ = [
    "HARD_CHECKS",
    "AccountSnapshot",
    "RiskAction",
    "RiskEngine",
    "RiskLimits",
    "SignalAction",
    "notional",
]
