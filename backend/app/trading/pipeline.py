"""The trading pipeline.

    Signal -> Risk Decision -> Order -> Execution -> Portfolio

This module is the single place where a signal becomes an order, and it cannot
do so without a risk decision that permits it. Everything else in the platform
either produces signals or consumes results; nothing else submits.

The pipeline records an outcome for *every* signal, including the ones that
never became orders. A rejection is a result, not an absence — it is what the
Risk dashboard displays and what the AI Analyst reads to explain a refusal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.brokers.base import Broker, BrokerError
from app.core.logging import get_logger
from app.core.money import ZERO, D
from app.domain import (
    Fill,
    Instrument,
    Order,
    OrderRequest,
    OrderType,
    RiskAction,
    RiskDecision,
    Signal,
)
from app.portfolio import Portfolio
from app.risk import RiskEngine

log = get_logger(__name__)


@dataclass(frozen=True)
class TradeOutcome:
    """What happened to one signal, end to end.

    Always produced, whatever the verdict, so the pipeline's history is a
    complete record rather than a log of successes.
    """

    signal: Signal
    decision: RiskDecision | None = None
    order: Order | None = None
    fills: list[Fill] = field(default_factory=list)
    error: str | None = None

    @property
    def executed(self) -> bool:
        return self.order is not None and bool(self.fills)

    @property
    def rejected(self) -> bool:
        return self.decision is not None and self.decision.action is RiskAction.REJECT

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.decision.reasons if self.decision else ()

    def describe(self) -> str:
        if self.error:
            return f"{self.signal.symbol}: failed — {self.error}"
        if self.decision is None:
            return f"{self.signal.symbol}: no decision (signal not actionable)"
        head = f"{self.signal.symbol} {self.signal.action.value}: {self.decision.action.value}"
        if self.reasons:
            return head + "\n" + "\n".join(f"  - {r}" for r in self.reasons)
        return head


class TradingPipeline:
    """Runs signals through risk, execution and portfolio accounting."""

    def __init__(
        self,
        risk_engine: RiskEngine,
        broker: Broker,
        portfolio: Portfolio,
        instruments: dict[str, Instrument] | None = None,
        default_risk_fraction: Decimal | str = "0.02",
    ) -> None:
        self.risk_engine = risk_engine
        self.broker = broker
        self.portfolio = portfolio
        self.instruments = instruments or {}
        self.default_risk_fraction = D(default_risk_fraction)
        self.history: list[TradeOutcome] = []

    # --- main entry point ----------------------------------------------

    def handle_signal(
        self,
        signal: Signal,
        *,
        quantity: Decimal | None = None,
        volatility: Decimal | None = None,
    ) -> TradeOutcome:
        """Take one signal all the way through the pipeline."""
        if not signal.is_actionable:
            outcome = TradeOutcome(signal=signal)
            self.history.append(outcome)
            return outcome

        requested = quantity if quantity is not None else self._proposed_quantity(signal)
        instrument = self.instruments.get(signal.symbol)

        if requested <= ZERO:
            outcome = TradeOutcome(signal=signal, error="proposed quantity is zero")
            self.history.append(outcome)
            return outcome

        decision = self.risk_engine.assess_signal(
            signal,
            quantity=requested,
            account=self.portfolio.snapshot().to_account(volatility=volatility),
            instrument=instrument,
        )

        if not decision.permits_order:
            outcome = TradeOutcome(signal=signal, decision=decision)
            self.history.append(outcome)
            log.info(
                "pipeline.rejected",
                symbol=signal.symbol,
                strategy=signal.strategy,
                score=str(decision.score),
                reasons=list(decision.reasons),
            )
            return outcome

        return self._execute(signal, decision)

    # --- internals -----------------------------------------------------

    def _execute(self, signal: Signal, decision: RiskDecision) -> TradeOutcome:
        request = OrderRequest(
            symbol=signal.symbol,
            side=signal.action.to_side(),
            order_type=OrderType.MARKET,
            quantity=decision.approved_quantity,
        )
        # The order carries the size risk approved, and a link back to the
        # decision that authorised it.
        order = Order.from_request(
            request,
            signal_id=signal.id,
            risk_decision_id=decision.id,
            quantity=decision.approved_quantity,
        )

        try:
            submitted = self.broker.submit(order)
        except BrokerError as exc:
            outcome = TradeOutcome(signal=signal, decision=decision, error=str(exc))
            self.history.append(outcome)
            log.warning("pipeline.execution_failed", symbol=signal.symbol, error=str(exc))
            return outcome

        fills = self.broker.fills_for(submitted.client_order_id)
        for fill in fills:
            self.portfolio.apply_fill(fill)

        outcome = TradeOutcome(
            signal=signal, decision=decision, order=submitted, fills=fills
        )
        self.history.append(outcome)
        return outcome

    def _proposed_quantity(self, signal: Signal) -> Decimal:
        """Size a proposal before risk sees it.

        A fraction of equity scaled by the strategy's own confidence. This is a
        *proposal* only — the risk engine remains free to cut or refuse it, and
        every limit is applied downstream of this number.
        """
        equity = self.portfolio.equity
        budget = equity * self.default_risk_fraction * (signal.strength or D("1"))
        quantity = budget / signal.reference_price

        instrument = self.instruments.get(signal.symbol)
        if instrument is not None:
            quantity = instrument.round_quantity(quantity)
        return max(quantity, ZERO)

    # --- reporting ------------------------------------------------------

    @property
    def rejections(self) -> list[TradeOutcome]:
        return [o for o in self.history if o.rejected]

    @property
    def executions(self) -> list[TradeOutcome]:
        return [o for o in self.history if o.executed]
