"""Performance metrics for the live portfolio."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends

from app.analytics import TradeRecord, build_report
from app.api.deps import ServiceDep, SessionDep
from app.api.presenters import performance_out, portfolio_out, safe_ratio
from app.api.schemas import OverviewOut, PerformanceOut
from app.auth.dependencies import require_authenticated
from app.core.money import ZERO
from app.db.repositories import (
    FillRepository,
    OrderRepository,
    RiskDecisionRepository,
    SignalRepository,
    utc_day_start,
)
from app.domain import Position
from app.portfolio import Portfolio

router = APIRouter(
    prefix="/api", tags=["performance"], dependencies=[Depends(require_authenticated)]
)


@router.get("/performance", response_model=PerformanceOut)
def performance(session: SessionDep, service: ServiceDep) -> PerformanceOut:
    """Live metrics, computed from the same code the backtester uses."""
    fills = FillRepository(session).all_fills()
    starting = service.settings.paper_starting_balance

    if not fills:
        return performance_out(build_report([starting, starting], []))

    portfolio = Portfolio(starting)
    curve: list[Decimal] = [starting]
    trades: list[TradeRecord] = []
    positions: dict[str, Position] = {}

    for fill in fills:
        before = positions.get(fill.symbol) or Position.flat(fill.symbol)
        after = before.apply_fill(fill)
        positions[fill.symbol] = after

        realized = after.realized_pnl - before.realized_pnl
        if realized != ZERO:
            trades.append(TradeRecord(fill.symbol, realized - fill.commission))

        portfolio.apply_fill(fill)
        portfolio.set_mark(fill.symbol, fill.price)
        curve.append(portfolio.equity)

    return performance_out(build_report(curve, trades))


@router.get("/overview", response_model=OverviewOut)
def overview(session: SessionDep, service: ServiceDep) -> OverviewOut:
    """Everything the landing page needs, in one request."""
    decisions = RiskDecisionRepository(session)
    orders = OrderRepository(session)
    signals = SignalRepository(session)

    today = utc_day_start()
    recent_signals = signals.recent(limit=500)
    signals_today = sum(1 for s in recent_signals if s.created_at >= today)

    recent_decisions = decisions.recent(limit=500)
    rejected_today = sum(
        1 for d in recent_decisions if d.created_at >= today and d.action == "REJECT"
    )

    scores = [d.score for d in recent_decisions[:20]]
    risk_score = sum(scores, ZERO) / len(scores) if scores else ZERO

    status_counts = orders.counts_by_status()
    open_orders = sum(
        count
        for status, count in status_counts.items()
        if status in {"PENDING", "SUBMITTED", "PARTIALLY_FILLED"}
    )

    return OverviewOut(
        portfolio=portfolio_out(service.snapshot()),
        risk_score=risk_score,
        open_orders=open_orders,
        signals_today=signals_today,
        rejected_today=rejected_today,
        strategies=len(signals.strategy_names()),
        broker=service.settings.broker.value,
        live_trading=False,
    )


__all__ = ["router", "safe_ratio"]
