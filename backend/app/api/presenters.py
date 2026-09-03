"""Conversion from domain and database objects into API responses.

Kept apart from the routes so the shape of a response is defined once and the
routes stay thin.
"""

from __future__ import annotations

from decimal import Decimal

from app.analytics import PerformanceReport
from app.api.schemas import (
    FillOut,
    OrderOut,
    PerformanceOut,
    PortfolioOut,
    PositionOut,
    RiskCheckOut,
    RiskDecisionOut,
    SignalOut,
)
from app.core.money import ZERO
from app.db.models import FillRow, OrderRow, RiskDecisionRow, SignalRow
from app.portfolio import PortfolioSnapshot


def position_out(snapshot: PortfolioSnapshot, position) -> PositionOut:
    mark = snapshot.mark_prices.get(position.symbol)
    return PositionOut(
        symbol=position.symbol,
        side=position.side.value,
        quantity=position.quantity,
        signed_quantity=position.signed_quantity,
        average_entry_price=position.average_entry_price,
        mark_price=mark,
        notional=position.notional_value(mark) if mark is not None else None,
        unrealized_pnl=position.unrealized_pnl(mark) if mark is not None else None,
        realized_pnl=position.realized_pnl,
    )


def portfolio_out(snapshot: PortfolioSnapshot) -> PortfolioOut:
    positions = [position_out(snapshot, p) for p in snapshot.open_positions]
    return PortfolioOut(
        equity=snapshot.equity,
        cash=snapshot.cash,
        position_value=snapshot.position_value,
        starting_balance=snapshot.starting_balance,
        realized_pnl=snapshot.realized_pnl,
        unrealized_pnl=snapshot.unrealized_pnl,
        total_pnl=snapshot.total_pnl,
        total_return=snapshot.total_return,
        total_commission=snapshot.total_commission,
        gross_exposure=snapshot.gross_exposure,
        leverage=snapshot.leverage,
        drawdown=snapshot.drawdown,
        peak_equity=snapshot.peak_equity,
        daily_pnl=snapshot.daily_pnl,
        open_position_count=len(positions),
        positions=positions,
        as_of=snapshot.as_of,
    )


def risk_check_out(check: dict) -> RiskCheckOut:
    observed = check.get("observed")
    limit = check.get("limit")
    utilisation = None
    if observed is not None and limit not in (None, "0"):
        try:
            utilisation = Decimal(str(observed)) / Decimal(str(limit))
        except (ArithmeticError, ValueError):
            utilisation = None
    return RiskCheckOut(
        name=check.get("name", "unknown"),
        passed=bool(check.get("passed", True)),
        score=Decimal(str(check.get("score", "0"))),
        weight=Decimal(str(check.get("weight", "1"))),
        observed=Decimal(str(observed)) if observed is not None else None,
        limit=Decimal(str(limit)) if limit is not None else None,
        utilisation=utilisation,
        reason=check.get("reason", "") or "",
    )


def risk_decision_out(row: RiskDecisionRow) -> RiskDecisionOut:
    checks = [risk_check_out(c) for c in (row.checks or [])]
    return RiskDecisionOut(
        id=str(row.id),
        signal_id=str(row.signal_id) if row.signal_id else None,
        symbol=row.signal.symbol if row.signal else None,
        strategy=row.signal.strategy if row.signal else None,
        action=row.action,
        score=row.score,
        requested_quantity=row.requested_quantity,
        approved_quantity=row.approved_quantity,
        reasons=[c.reason for c in checks if not c.passed and c.reason],
        checks=checks,
        created_at=row.created_at,
    )


def order_out(row: OrderRow) -> OrderOut:
    return OrderOut(
        id=str(row.id),
        client_order_id=row.client_order_id,
        exchange_order_id=row.exchange_order_id,
        symbol=row.symbol,
        side=row.side,
        order_type=row.order_type,
        status=row.status,
        quantity=row.quantity,
        filled_quantity=row.filled_quantity,
        price=row.price,
        average_fill_price=row.average_fill_price,
        risk_decision_id=str(row.risk_decision_id) if row.risk_decision_id else None,
        signal_id=str(row.signal_id) if row.signal_id else None,
        created_at=row.created_at,
    )


def fill_out(row: FillRow) -> FillOut:
    return FillOut(
        id=str(row.id),
        order_id=str(row.order_id),
        symbol=row.symbol,
        side=row.side,
        quantity=row.quantity,
        price=row.price,
        commission=row.commission,
        executed_at=row.executed_at,
    )


def signal_out(row: SignalRow) -> SignalOut:
    return SignalOut(
        id=str(row.id),
        strategy=row.strategy,
        symbol=row.symbol,
        action=row.action,
        strength=row.strength,
        reference_price=row.reference_price,
        bar_close_time=row.bar_close_time,
        created_at=row.created_at,
        features=row.features or {},
    )


def performance_out(report: PerformanceReport) -> PerformanceOut:
    return PerformanceOut(
        starting_equity=report.starting_equity,
        ending_equity=report.ending_equity,
        total_return=report.total_return,
        sharpe_ratio=report.sharpe_ratio,
        sortino_ratio=report.sortino_ratio,
        max_drawdown=report.max_drawdown,
        calmar_ratio=report.calmar_ratio,
        win_rate=report.win_rate,
        profit_factor=report.profit_factor,
        expectancy=report.expectancy,
        average_win=report.average_win,
        average_loss=report.average_loss,
        total_trades=report.total_trades,
        winning_trades=report.winning_trades,
        losing_trades=report.losing_trades,
    )


def safe_ratio(numerator: int, denominator: int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator) if denominator else ZERO
