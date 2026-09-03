"""Risk engine output.

The full check implementations arrive in Phase 3. What is fixed here is the
*shape* of a decision, and the invariant that ties the verdict to the approved
size. Encoding that invariant in the model means no later code path can emit a
REJECT that still carries tradeable quantity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import RiskAction
from app.domain.types import NonNegQuantity, Quantity, RiskScore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RiskCheckResult(BaseModel):
    """One independent check's contribution to the overall decision.

    Each check reports what it measured against what it allows, so the reason
    shown to a user is derived from numbers rather than written by hand.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    passed: bool

    #: This check's own risk contribution, 0-100 before weighting.
    score: RiskScore

    #: Weight applied when combining into the overall score.
    weight: Decimal = Field(default=Decimal("1"), gt=0)

    observed: Decimal | None = None
    limit: Decimal | None = None

    reason: str = ""

    @model_validator(mode="after")
    def _failed_checks_explain_themselves(self) -> RiskCheckResult:
        if not self.passed and not self.reason:
            raise ValueError(f"failed check {self.name!r} must supply a reason")
        return self


class RiskDecision(BaseModel):
    """The verdict on one proposed trade.

    Persisted whether or not it produced an order. Rejections are records, not
    silence — they are what the Risk dashboard and the AI Analyst read to
    answer "why was this trade rejected?".
    """

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    signal_id: uuid.UUID

    action: RiskAction
    score: RiskScore

    requested_quantity: Quantity
    approved_quantity: NonNegQuantity

    checks: tuple[RiskCheckResult, ...] = ()
    created_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _quantity_matches_verdict(self) -> RiskDecision:
        """The core invariant of the risk layer."""
        if self.action is RiskAction.REJECT:
            if self.approved_quantity != 0:
                raise ValueError("a REJECT decision must approve zero quantity")
        elif self.action is RiskAction.APPROVE:
            if self.approved_quantity != self.requested_quantity:
                raise ValueError("an APPROVE decision must approve the full requested quantity")
        else:  # REDUCE
            if not (0 < self.approved_quantity < self.requested_quantity):
                raise ValueError(
                    "a REDUCE decision must approve a positive quantity strictly "
                    "below the requested quantity"
                )
        return self

    @property
    def reasons(self) -> tuple[str, ...]:
        """Human-readable explanations, drawn only from checks that failed."""
        return tuple(c.reason for c in self.checks if not c.passed and c.reason)

    @property
    def failed_checks(self) -> tuple[RiskCheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)

    @property
    def permits_order(self) -> bool:
        return self.action.permits_order

    def summary(self) -> str:
        """The operator-facing rendering used in logs and the CLI."""
        lines = [f"Risk Score: {self.score}", f"Decision: {self.action.value}"]
        if self.reasons:
            lines.append("Reasons:")
            lines.extend(f"- {r}" for r in self.reasons)
        return "\n".join(lines)
