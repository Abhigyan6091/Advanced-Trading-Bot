"""The risk layer's core invariant: the verdict must match the approved size."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import RiskAction, RiskCheckResult, RiskDecision


def check(name: str, passed: bool, score: str, reason: str = "") -> RiskCheckResult:
    return RiskCheckResult(name=name, passed=passed, score=Decimal(score), reason=reason)


class TestDecisionInvariant:
    def test_approve_must_grant_full_size(self):
        d = RiskDecision(
            signal_id=uuid.uuid4(),
            action=RiskAction.APPROVE,
            score=Decimal("18"),
            requested_quantity=Decimal("1"),
            approved_quantity=Decimal("1"),
        )
        assert d.permits_order

    def test_approve_cannot_silently_trim_size(self):
        with pytest.raises(ValidationError, match="full requested quantity"):
            RiskDecision(
                signal_id=uuid.uuid4(),
                action=RiskAction.APPROVE,
                score=Decimal("18"),
                requested_quantity=Decimal("1"),
                approved_quantity=Decimal("0.5"),
            )

    def test_reject_must_grant_zero(self):
        with pytest.raises(ValidationError, match="approve zero quantity"):
            RiskDecision(
                signal_id=uuid.uuid4(),
                action=RiskAction.REJECT,
                score=Decimal("91"),
                requested_quantity=Decimal("1"),
                approved_quantity=Decimal("0.2"),
            )

    @pytest.mark.parametrize("approved", ["0", "1", "1.5"])
    def test_reduce_must_be_strictly_between_zero_and_requested(self, approved):
        with pytest.raises(ValidationError, match="strictly below"):
            RiskDecision(
                signal_id=uuid.uuid4(),
                action=RiskAction.REDUCE,
                score=Decimal("64"),
                requested_quantity=Decimal("1"),
                approved_quantity=Decimal(approved),
            )

    def test_reduce_accepts_a_partial_size(self):
        d = RiskDecision(
            signal_id=uuid.uuid4(),
            action=RiskAction.REDUCE,
            score=Decimal("64"),
            requested_quantity=Decimal("1"),
            approved_quantity=Decimal("0.4"),
        )
        assert d.permits_order
        assert d.approved_quantity == Decimal("0.4")

    @pytest.mark.parametrize("score", ["-1", "101"])
    def test_score_is_bounded_to_0_100(self, score):
        with pytest.raises(ValidationError):
            RiskDecision(
                signal_id=uuid.uuid4(),
                action=RiskAction.APPROVE,
                score=Decimal(score),
                requested_quantity=Decimal("1"),
                approved_quantity=Decimal("1"),
            )


class TestReasons:
    def test_reasons_come_only_from_failed_checks(self):
        d = RiskDecision(
            signal_id=uuid.uuid4(),
            action=RiskAction.REJECT,
            score=Decimal("88"),
            requested_quantity=Decimal("1"),
            approved_quantity=Decimal("0"),
            checks=(
                check("position_size", False, "90", "Position size exceeds limit"),
                check("leverage", True, "10"),
                check("volatility", False, "80", "Excessive volatility"),
            ),
        )
        assert d.reasons == ("Position size exceeds limit", "Excessive volatility")
        assert len(d.failed_checks) == 2

    def test_a_failed_check_must_explain_itself(self):
        with pytest.raises(ValidationError, match="must supply a reason"):
            check("exposure", False, "95")

    def test_summary_renders_the_operator_view(self):
        d = RiskDecision(
            signal_id=uuid.uuid4(),
            action=RiskAction.REJECT,
            score=Decimal("72"),
            requested_quantity=Decimal("1"),
            approved_quantity=Decimal("0"),
            checks=(check("exposure", False, "85", "High portfolio exposure"),),
        )
        assert d.summary() == (
            "Risk Score: 72\n"
            "Decision: REJECT\n"
            "Reasons:\n"
            "- High portfolio exposure"
        )
