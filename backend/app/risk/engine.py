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
    Position,
    RiskAction,
    RiskCheckResult,
    RiskDecision,
    Side,
    Signal,
    SignalAction,
)
from app.risk.checks import DEFAULT_CHECKS, MLAdverseOutcomeCheck, RiskCheck
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
        ml_model: object | None = None,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.hard_checks = hard_checks

        # The ML check is additive and opt-in: passing no model (the default)
        # leaves `checks` exactly as given, so every existing caller -- and
        # every test written before this feature existed -- is unaffected.
        # A model is only ever appended, never substituted for a deterministic
        # check, because it assists the engine rather than replacing any part
        # of it.
        if ml_model is not None:
            checks = (*checks, MLAdverseOutcomeCheck(ml_model))
        self.checks = checks

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

        # Round to the exchange grid before anything downstream sees the
        # quantity. This makes `requested_quantity` on the decision the
        # quantity the venue could actually accept, which is what keeps an
        # APPROVE (required to equal the requested quantity exactly) from
        # conflicting with grid rounding applied after the fact.
        if instrument is not None:
            quantity = instrument.round_quantity(quantity)
            if quantity <= ZERO:
                raise ValueError(
                    f"requested quantity rounds to zero at {symbol}'s step "
                    f"size ({instrument.step_size})"
                )

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
        approved = self._size(
            action, results, symbol, side, quantity, price, account, instrument
        )

        # Sizing can find no tradeable quantity — below the exchange minimum,
        # say. That is a rejection, not a zero-size approval or a zero-size
        # "approval" that would violate RiskDecision's own invariant (an
        # APPROVE must carry the full requested quantity).
        if action is not RiskAction.REJECT and approved <= ZERO:
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
        symbol: str,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        account: AccountSnapshot,
        instrument: Instrument | None,
    ) -> Decimal:
        if action is RiskAction.REJECT:
            return ZERO

        if action is RiskAction.APPROVE:
            # `quantity` is already grid-rounded (assess() does this up
            # front), so only the minimum-notional/minimum-quantity floor can
            # still be violated here. A quantity below that floor cannot be
            # approved as-is; the caller sees this as a REJECT via the
            # approved<=0 downgrade in assess().
            if instrument is not None and not instrument.is_tradeable(quantity, price):
                return ZERO
            return quantity

        allowed = self._largest_permitted_quantity(
            results, symbol, side, quantity, price, account
        )
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
        symbol: str,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        account: AccountSnapshot,
    ) -> Decimal:
        """Size down to the tightest binding limit.

        Each size-sensitive check implies a maximum order quantity; the
        smallest of those governs. Checks that do not depend on size
        (drawdown, daily loss, volatility) cannot be sized around and are
        excluded.

        Every cap below accounts for the position or exposure already on the
        book -- an order that is *reducing* the very thing a check flagged has
        more headroom than one that is adding to it, and a cap computed as if
        the account were flat would under-size a legitimate exit.
        """
        caps: list[Decimal] = [quantity]

        by_name = {r.name: r for r in results}
        existing = account.position(symbol)

        position = by_name.get("position_size")
        if position is not None and not position.passed:
            max_resulting = self.limits.max_position_pct * account.equity / price
            # abs(existing.signed_quantity + side.sign * q) <= max_resulting,
            # solved for the largest non-negative q. See PositionSizeCheck for
            # the same "resulting position" convention this mirrors.
            caps.append(
                max(ZERO, max_resulting - side.sign * existing.signed_quantity)
            )

        exposure = by_name.get("portfolio_exposure")
        if exposure is not None and not exposure.passed:
            caps.append(
                self._headroom_quantity(
                    account, existing, side, price, self.limits.max_portfolio_exposure_pct
                )
            )

        leverage = by_name.get("leverage")
        if leverage is not None and not leverage.passed:
            caps.append(
                self._headroom_quantity(account, existing, side, price, self.limits.max_leverage)
            )

        order_value = by_name.get("order_value")
        if order_value is not None and not order_value.passed:
            caps.append(self.limits.max_order_value / price)

        # A soft REDUCE with nothing actually breached: trim rather than refuse.
        if len(caps) == 1:
            caps.append(quantity * Decimal("0.5"))

        return max(ZERO, min(caps))

    @staticmethod
    def _headroom_quantity(
        account: AccountSnapshot,
        existing: Position,
        side: Side,
        price: Decimal,
        budget_factor: Decimal,
    ) -> Decimal:
        """Largest order quantity that keeps *portfolio-wide* exposure or
        leverage within budget, given this symbol's existing contribution.

        ``budget_factor`` scales equity into a currency budget either way: a
        fraction for exposure (0.6 -> 60% of equity) or a raw multiple for
        leverage (3 -> 3x equity) -- both are just "factor times equity".
        """
        budget = budget_factor * account.equity
        existing_mark = account.mark(existing.symbol) or price
        other_exposure = account.gross_exposure - existing.notional_value(existing_mark)

        # Budget left for this symbol once every other position's exposure is
        # accounted for.
        symbol_budget = budget - other_exposure
        if symbol_budget <= ZERO:
            return ZERO

        # Largest resulting quantity in this symbol the remaining budget
        # allows, then converted into an order quantity the same way the
        # position-size cap is: accounting for what already exists.
        max_resulting_qty = symbol_budget / price
        return max(ZERO, max_resulting_qty - side.sign * existing.signed_quantity)

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
