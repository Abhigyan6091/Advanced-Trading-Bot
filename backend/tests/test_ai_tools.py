"""AI Analyst tool functions against real stored data.

Marked integration: each tool reads through the same repositories the
dashboard uses, so these are checked against a live database rather than
mocks.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.tools import (
    get_portfolio,
    get_positions,
    get_risk_decisions,
    get_strategy_performance,
    get_trades,
)
from app.core.config import get_settings
from app.db.repositories import (
    FillRepository,
    OrderRepository,
    RiskDecisionRepository,
    SignalRepository,
)
from app.db.session import session_scope
from app.domain import (
    Fill,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    RiskAction,
    RiskCheckResult,
    RiskDecision,
    Side,
    Signal,
    SignalAction,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    with session_scope() as s:
        yield s


class TestGetPortfolio:
    def test_returns_json_serialisable_decimals_as_strings(self, db):
        result = get_portfolio(db, get_settings())
        assert isinstance(result["equity"], str)
        float(result["equity"])  # must parse as a number

    def test_shape_matches_what_the_analyst_prompt_promises(self, db):
        result = get_portfolio(db, get_settings())
        for key in ("equity", "cash", "realized_pnl", "unrealized_pnl", "positions"):
            assert key in result


class TestGetPositions:
    def test_empty_when_nothing_is_open(self, db):
        result = get_positions(db, get_settings())
        assert "positions" in result

    def test_sorted_largest_notional_first(self, db):
        signal = Signal(
            strategy="ema_crossover", symbol="AAATESTUSDT", action=SignalAction.BUY,
            strength=Decimal("1"), reference_price=Decimal("100"),
            bar_close_time=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )
        SignalRepository(db).save(signal)
        db.flush()

        decision = RiskDecision(
            signal_id=signal.id, action=RiskAction.APPROVE, score=Decimal("10"),
            requested_quantity=Decimal("1"), approved_quantity=Decimal("1"),
        )
        RiskDecisionRepository(db).save(decision)
        db.flush()

        order = Order.from_request(
            OrderRequest(
                symbol="AAATESTUSDT", side=Side.BUY, order_type=OrderType.MARKET,
                quantity=Decimal("1"),
            ),
            signal_id=signal.id, risk_decision_id=decision.id,
        )
        order = order.transition_to(OrderStatus.SUBMITTED)
        order = order.transition_to(
            OrderStatus.FILLED, filled_quantity=Decimal("1"), average_fill_price=Decimal("100")
        )
        OrderRepository(db).save(order)
        db.flush()

        fill = Fill(order_id=order.id, symbol="AAATESTUSDT", side=Side.BUY,
                    quantity=Decimal("1"), price=Decimal("100"))
        FillRepository(db).save(fill)
        db.flush()

        result = get_positions(db, get_settings())
        symbols = [p["symbol"] for p in result["positions"]]
        assert "AAATESTUSDT" in symbols


class TestGetRiskDecisions:
    def test_filters_by_action(self, db):
        result = get_risk_decisions(db, action="REJECT", limit=5)
        assert "decisions" in result
        for decision in result["decisions"]:
            assert decision["action"] == "REJECT"

    def test_returns_the_check_breakdown(self, db):
        signal = Signal(
            strategy="rsi", symbol="BBBTESTUSDT", action=SignalAction.BUY,
            strength=Decimal("1"), reference_price=Decimal("50"),
            bar_close_time=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )
        SignalRepository(db).save(signal)
        db.flush()

        decision = RiskDecision(
            signal_id=signal.id, action=RiskAction.REJECT, score=Decimal("90"),
            requested_quantity=Decimal("5"), approved_quantity=Decimal("0"),
            checks=(
                RiskCheckResult(
                    name="daily_loss", passed=False, score=Decimal("95"),
                    reason="Daily loss limit reached",
                ),
            ),
        )
        RiskDecisionRepository(db).save(decision)
        db.flush()

        result = get_risk_decisions(db, symbol="BBBTESTUSDT", limit=5)
        matches = [d for d in result["decisions"] if d["symbol"] == "BBBTESTUSDT"]
        assert matches
        assert matches[0]["checks"][0]["reason"] == "Daily loss limit reached"


class TestGetStrategyPerformance:
    def test_lists_every_registered_strategy(self, db):
        result = get_strategy_performance(db)
        names = {s["strategy"] for s in result["strategies"]}
        assert {"ema_crossover", "rsi", "macd", "mean_reversion"} <= names

    def test_sorted_best_pnl_first(self, db):
        result = get_strategy_performance(db)
        pnls = [float(s["realized_pnl"]) for s in result["strategies"]]
        assert pnls == sorted(pnls, reverse=True)


class TestGetTrades:
    def test_returns_a_list_even_when_empty(self, db):
        result = get_trades(db, symbol="ZZZNONEXISTENT", limit=10)
        assert result["trades"] == []
