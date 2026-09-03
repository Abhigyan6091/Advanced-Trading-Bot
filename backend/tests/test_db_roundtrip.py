"""Domain models survive a round trip through PostgreSQL.

Marked ``integration``: requires a live database. Run with
``pytest -m integration`` once ``docker compose up db`` is running.

The point of these tests is precision. A Decimal that comes back as a float, or
a quantity truncated by an undersized NUMERIC scale, corrupts P&L silently —
so the assertions compare exact values and types, not approximations.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import FillRow, OrderRow, RiskDecisionRow, SignalRow
from app.db.session import session_scope
from app.domain import (
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    RiskAction,
    RiskCheckResult,
    RiskDecision,
    Side,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    with session_scope() as s:
        yield s


class TestPrecision:
    def test_eight_decimal_quantity_survives_the_round_trip(self, db):
        """Crypto quantities go to 8 decimal places. None of them may be lost."""
        qty = Decimal("0.00000001")
        price = Decimal("67123.45678901")

        order = OrderRow(
            client_order_id=f"sta-{uuid.uuid4().hex[:24]}",
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=qty,
            status="PENDING",
            filled_quantity=Decimal("0"),
        )
        db.add(order)
        db.flush()

        db.add(
            FillRow(
                order_id=order.id,
                symbol="BTCUSDT",
                side="BUY",
                quantity=qty,
                price=price,
                commission=Decimal("0.0000004"),
            )
        )
        db.flush()
        db.expire_all()

        stored = db.execute(select(FillRow).where(FillRow.order_id == order.id)).scalar_one()
        assert isinstance(stored.quantity, Decimal)
        assert stored.quantity == qty
        assert stored.price == price
        assert stored.commission == Decimal("0.0000004")

    def test_large_notional_does_not_overflow(self, db):
        """NUMERIC(24,10) leaves 14 integer digits — ample for any notional."""
        big = Decimal("99999999999999.1234567890")
        row = OrderRow(
            client_order_id=f"sta-{uuid.uuid4().hex[:24]}",
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=big,
            status="PENDING",
            filled_quantity=Decimal("0"),
        )
        db.add(row)
        db.flush()
        db.expire_all()
        assert db.get(OrderRow, row.id).quantity == big


class TestIdempotency:
    def test_duplicate_client_order_id_is_refused_by_the_database(self, db):
        """The idempotency guarantee is a constraint, not application logic."""
        from sqlalchemy.exc import IntegrityError

        coid = f"sta-{uuid.uuid4().hex[:24]}"
        common = dict(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("1"),
            status="PENDING",
            filled_quantity=Decimal("0"),
        )
        db.add(OrderRow(client_order_id=coid, **common))
        db.flush()

        db.add(OrderRow(client_order_id=coid, **common))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestRiskDecisionPersistence:
    def test_a_rejection_is_stored_with_its_reasons(self, db):
        """Rejections are records. This is what the Risk dashboard reads."""
        signal = SignalRow(
            strategy="ema_crossover",
            symbol="BTCUSDT",
            action="BUY",
            strength=Decimal("0.8"),
            reference_price=Decimal("60200"),
            bar_close_time=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            features={"ema_fast": "60210", "ema_slow": "60050"},
        )
        db.add(signal)
        db.flush()

        decision = RiskDecision(
            signal_id=signal.id,
            action=RiskAction.REJECT,
            score=Decimal("72"),
            requested_quantity=Decimal("1"),
            approved_quantity=Decimal("0"),
            checks=(
                RiskCheckResult(
                    name="exposure",
                    passed=False,
                    score=Decimal("85"),
                    observed=Decimal("0.82"),
                    limit=Decimal("0.60"),
                    reason="High portfolio exposure",
                ),
                RiskCheckResult(
                    name="volatility",
                    passed=False,
                    score=Decimal("78"),
                    reason="Excessive volatility",
                ),
            ),
        )

        db.add(
            RiskDecisionRow(
                id=decision.id,
                signal_id=decision.signal_id,
                action=decision.action.value,
                score=decision.score,
                requested_quantity=decision.requested_quantity,
                approved_quantity=decision.approved_quantity,
                checks=[c.model_dump(mode="json") for c in decision.checks],
            )
        )
        db.flush()
        db.expire_all()

        stored = db.get(RiskDecisionRow, decision.id)
        assert stored.action == "REJECT"
        assert stored.approved_quantity == Decimal("0")
        assert [c["reason"] for c in stored.checks] == [
            "High portfolio exposure",
            "Excessive volatility",
        ]
        # The JSONB breakdown reconstitutes into domain objects unchanged.
        rebuilt = [RiskCheckResult.model_validate(c) for c in stored.checks]
        assert rebuilt[0].observed == Decimal("0.82")
        assert rebuilt[0].limit == Decimal("0.60")


class TestOrderProvenance:
    def test_order_links_back_to_the_decision_that_authorised_it(self, db):
        decision_row = RiskDecisionRow(
            action="APPROVE",
            score=Decimal("22"),
            requested_quantity=Decimal("1"),
            approved_quantity=Decimal("1"),
            checks=[],
        )
        db.add(decision_row)
        db.flush()

        domain_order = Order.from_request(
            OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
            ),
            risk_decision_id=decision_row.id,
        )
        db.add(
            OrderRow(
                id=domain_order.id,
                client_order_id=domain_order.client_order_id,
                risk_decision_id=domain_order.risk_decision_id,
                symbol=domain_order.symbol,
                side=domain_order.side.value,
                order_type=domain_order.order_type.value,
                quantity=domain_order.quantity,
                status=OrderStatus.PENDING.value,
                filled_quantity=Decimal("0"),
            )
        )
        db.flush()
        db.expire_all()

        stored = db.get(OrderRow, domain_order.id)
        assert stored.risk_decision.action == "APPROVE"
        assert stored.risk_decision.id == decision_row.id
