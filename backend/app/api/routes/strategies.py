"""Strategy catalogue and per-strategy attribution."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep
from app.api.schemas import StrategyOut
from app.auth.dependencies import require_authenticated
from app.core.money import ZERO
from app.db.models import OrderRow, RiskDecisionRow, SignalRow
from app.strategies import STRATEGIES, available, build

router = APIRouter(
    prefix="/api/strategies",
    tags=["strategies"],
    dependencies=[Depends(require_authenticated)],
)


@router.get("", response_model=list[StrategyOut])
def list_strategies(session: SessionDep) -> list[StrategyOut]:
    """Every registered strategy with how it has actually performed.

    Strategies with no activity are still listed, so the catalogue shows what
    is available rather than only what has traded.
    """
    from sqlalchemy import func, select

    signal_counts = dict(
        session.execute(
            select(SignalRow.strategy, func.count()).group_by(SignalRow.strategy)
        ).all()
    )
    actionable_counts = dict(
        session.execute(
            select(SignalRow.strategy, func.count())
            .where(SignalRow.action != "HOLD")
            .group_by(SignalRow.strategy)
        ).all()
    )
    decision_counts = dict(
        session.execute(
            select(
                SignalRow.strategy,
                func.count().filter(RiskDecisionRow.action == "APPROVE"),
            )
            .join(RiskDecisionRow, RiskDecisionRow.signal_id == SignalRow.id)
            .group_by(SignalRow.strategy)
        ).all()
    )
    reduced_counts = dict(
        session.execute(
            select(
                SignalRow.strategy,
                func.count().filter(RiskDecisionRow.action == "REDUCE"),
            )
            .join(RiskDecisionRow, RiskDecisionRow.signal_id == SignalRow.id)
            .group_by(SignalRow.strategy)
        ).all()
    )
    rejected_counts = dict(
        session.execute(
            select(
                SignalRow.strategy,
                func.count().filter(RiskDecisionRow.action == "REJECT"),
            )
            .join(RiskDecisionRow, RiskDecisionRow.signal_id == SignalRow.id)
            .group_by(SignalRow.strategy)
        ).all()
    )

    out: list[StrategyOut] = []
    for name in available():
        instance = build(name)
        out.append(
            StrategyOut(
                name=name,
                parameters=instance.parameters,
                signals=signal_counts.get(name, 0),
                actionable=actionable_counts.get(name, 0),
                approved=decision_counts.get(name, 0) or 0,
                reduced=reduced_counts.get(name, 0) or 0,
                rejected=rejected_counts.get(name, 0) or 0,
                realized_pnl=_strategy_pnl(session, name),
            )
        )
    return out


@router.get("/catalogue")
def catalogue() -> dict[str, dict]:
    """Available strategies and their default parameters."""
    return {
        name: {
            "parameters": build(name).parameters,
            "min_bars": build(name).min_bars,
            "class": cls.__name__,
        }
        for name, cls in STRATEGIES.items()
    }


def _strategy_pnl(session, strategy: str) -> Decimal:
    """Realised P&L attributed to a strategy, via signal -> order -> fills.

    Attribution follows the provenance chain each order carries, which is why
    orders record the signal that produced them.
    """
    from sqlalchemy import select

    from app.db.models import FillRow
    from app.domain import Position

    order_ids = list(
        session.execute(
            select(OrderRow.id)
            .join(SignalRow, SignalRow.id == OrderRow.signal_id)
            .where(SignalRow.strategy == strategy)
        ).scalars()
    )
    if not order_ids:
        return ZERO

    rows = list(
        session.execute(
            select(FillRow)
            .where(FillRow.order_id.in_(order_ids))
            .order_by(FillRow.executed_at.asc())
        ).scalars()
    )
    if not rows:
        return ZERO

    from app.db.repositories import FillRepository

    total = ZERO
    by_symbol: dict[str, Position] = {}
    for row in rows:
        fill = FillRepository.to_domain(row)
        position = by_symbol.get(fill.symbol) or Position.flat(fill.symbol)
        before = position.realized_pnl
        position = position.apply_fill(fill)
        by_symbol[fill.symbol] = position
        total += position.realized_pnl - before - fill.commission
    return total
