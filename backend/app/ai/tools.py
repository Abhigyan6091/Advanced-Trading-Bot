"""Read-only tools for the AI Analyst.

Every function here reads from the platform's own stored records and returns
plain JSON-serialisable data -- Decimals as strings, timestamps as ISO text.
None of them construct an Order, a RiskDecision, or reach a broker; that
absence is what an architecture test enforces (see
tests/test_architecture.py::TestAIAnalystIsolation), which is what makes "the
analyst cannot bypass the risk engine" a structural fact rather than a prompt
instruction it could be argued out of.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.money import ZERO
from app.db.repositories import (
    FillRepository,
    OrderRepository,
    RiskDecisionRepository,
    SignalRepository,
)
from app.services.trading_service import TradingService


def get_portfolio(session: Session, settings) -> dict[str, Any]:
    """Current balances, positions, exposure and P&L."""
    service = TradingService(session=session, settings=settings)
    snapshot = service.snapshot()
    return {
        "equity": str(snapshot.equity),
        "cash": str(snapshot.cash),
        "realized_pnl": str(snapshot.realized_pnl),
        "unrealized_pnl": str(snapshot.unrealized_pnl),
        "total_pnl": str(snapshot.total_pnl),
        "total_return": str(snapshot.total_return),
        "gross_exposure": str(snapshot.gross_exposure),
        "leverage": str(snapshot.leverage),
        "drawdown": str(snapshot.drawdown),
        "daily_pnl": str(snapshot.daily_pnl),
        "positions": [
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": str(p.quantity),
                "average_entry_price": str(p.average_entry_price),
                "mark_price": str(snapshot.mark_prices.get(p.symbol, ""))
                or None,
                "realized_pnl": str(p.realized_pnl),
            }
            for p in snapshot.open_positions
        ],
    }


def get_positions(session: Session, settings) -> dict[str, Any]:
    """Open positions ranked by notional, for "which are my riskiest".

    A separate tool from get_portfolio because the question it answers is
    different -- not "what is my overall state" but "which specific
    positions carry the most risk right now" -- and giving the model a
    narrower, pre-sorted answer is more reliable than asking it to sort a
    bigger payload itself.
    """
    service = TradingService(session=session, settings=settings)
    snapshot = service.snapshot()

    rows = []
    for p in snapshot.open_positions:
        mark = snapshot.mark_prices.get(p.symbol)
        notional = p.notional_value(mark) if mark is not None else ZERO
        rows.append(
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": str(p.quantity),
                "notional": str(notional),
                "pct_of_equity": (
                    str(notional / snapshot.equity) if snapshot.equity > ZERO else "0"
                ),
                "unrealized_pnl": (
                    str(p.unrealized_pnl(mark)) if mark is not None else None
                ),
            }
        )
    rows.sort(key=lambda r: float(r["notional"]), reverse=True)
    return {"positions": rows}


def get_risk_decisions(
    session: Session,
    *,
    symbol: str | None = None,
    action: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Recent risk decisions with their full check breakdown.

    ``action`` filters to APPROVE, REDUCE or REJECT -- pass REJECT to answer
    "why was my trade rejected?".
    """
    repo = RiskDecisionRepository(session)
    rows = repo.recent(limit=limit, action=action)
    if symbol:
        rows = [r for r in rows if r.signal and r.signal.symbol == symbol.upper()]

    return {
        "decisions": [
            {
                "symbol": row.signal.symbol if row.signal else None,
                "strategy": row.signal.strategy if row.signal else None,
                "action": row.action,
                "score": str(row.score),
                "requested_quantity": str(row.requested_quantity),
                "approved_quantity": str(row.approved_quantity),
                "created_at": row.created_at.isoformat(),
                "checks": [
                    {
                        "name": c.get("name"),
                        "passed": c.get("passed"),
                        "observed": c.get("observed"),
                        "limit": c.get("limit"),
                        "reason": c.get("reason"),
                    }
                    for c in (row.checks or [])
                ],
            }
            for row in rows
        ]
    }


def get_strategy_performance(session: Session) -> dict[str, Any]:
    """Per-strategy signal counts, verdict mix and attributed realised P&L."""
    from app.api.routes.strategies import _strategy_pnl
    from app.strategies import available

    signals = SignalRepository(session)
    decisions = RiskDecisionRepository(session)

    rows = []
    for name in available():
        strategy_signals = signals.recent(limit=1000, strategy=name)
        actionable = [s for s in strategy_signals if s.action != "HOLD"]

        rows.append(
            {
                "strategy": name,
                "total_signals": len(strategy_signals),
                "actionable_signals": len(actionable),
                "realized_pnl": str(_strategy_pnl(session, name)),
            }
        )

    rows.sort(key=lambda r: float(r["realized_pnl"]), reverse=True)
    return {
        "strategies": rows,
        "overall_decision_mix": decisions.counts_by_action(),
    }


def get_trades(
    session: Session, *, symbol: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """Recent orders and their fills."""
    orders = OrderRepository(session).recent(limit=limit, symbol=symbol)
    fills_repo = FillRepository(session)

    rows = []
    for order in orders:
        order_fills = [f for f in fills_repo.recent(500) if f.order_id == order.id]
        rows.append(
            {
                "symbol": order.symbol,
                "side": order.side,
                "status": order.status,
                "quantity": str(order.quantity),
                "filled_quantity": str(order.filled_quantity),
                "average_fill_price": (
                    str(order.average_fill_price) if order.average_fill_price else None
                ),
                "created_at": order.created_at.isoformat(),
                "fill_count": len(order_fills),
            }
        )
    return {"trades": rows}


__all__ = [
    "get_portfolio",
    "get_positions",
    "get_risk_decisions",
    "get_strategy_performance",
    "get_trades",
]
