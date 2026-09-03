"""Portfolio, positions and the equity curve."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ServiceDep, SessionDep
from app.api.presenters import fill_out, portfolio_out
from app.api.schemas import EquityPointOut, FillOut, PortfolioOut
from app.core.money import ZERO
from app.db.repositories import FillRepository
from app.portfolio import Portfolio

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
def get_portfolio(service: ServiceDep) -> PortfolioOut:
    return portfolio_out(service.snapshot())


@router.get("/equity-curve", response_model=list[EquityPointOut])
def equity_curve(session: SessionDep, service: ServiceDep) -> list[EquityPointOut]:
    """Equity after each fill, rebuilt by replaying the ledger.

    Derived rather than stored: the curve can never disagree with the trades
    that produced it.
    """
    fills = FillRepository(session).all_fills()
    if not fills:
        snapshot = service.snapshot()
        return [
            EquityPointOut(timestamp=snapshot.as_of, equity=snapshot.starting_balance)
        ]

    portfolio = Portfolio(service.settings.paper_starting_balance)
    points: list[EquityPointOut] = [
        EquityPointOut(
            timestamp=fills[0].executed_at, equity=service.settings.paper_starting_balance
        )
    ]
    for fill in fills:
        portfolio.apply_fill(fill)
        portfolio.set_mark(fill.symbol, fill.price)
        points.append(
            EquityPointOut(timestamp=fill.executed_at, equity=portfolio.equity)
        )
    return points


@router.get("/fills", response_model=list[FillOut])
def recent_fills(session: SessionDep, limit: int = 50) -> list[FillOut]:
    return [fill_out(r) for r in FillRepository(session).recent(limit)]


@router.get("/allocation")
def allocation(service: ServiceDep) -> dict[str, str]:
    """Share of gross exposure by symbol, for the portfolio breakdown."""
    snapshot = service.snapshot()
    total = snapshot.gross_exposure
    if total <= ZERO:
        return {}
    out: dict[str, str] = {}
    for position in snapshot.open_positions:
        mark = snapshot.mark_prices.get(position.symbol)
        if mark is not None:
            out[position.symbol] = str(position.notional_value(mark) / total)
    return out
