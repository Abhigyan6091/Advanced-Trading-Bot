"""Backtesting endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import SessionDep
from app.api.presenters import performance_out
from app.api.schemas import BacktestOut, BacktestRequest, EquityPointOut
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.backtest import Backtester
from app.db.repositories import InstrumentRepository
from app.marketdata import BarRepository
from app.strategies import available, build

router = APIRouter(
    prefix="/api/backtest",
    tags=["backtesting"],
    # Compute-heavy: gated at trader, not just viewer.
    dependencies=[Depends(require_role(Role.TRADER))],
)


@router.post("", response_model=BacktestOut)
def run_backtest(session: SessionDep, request: BacktestRequest) -> BacktestOut:
    """Replay a strategy over stored history.

    Runs against the local bar store rather than a live fetch, so a backtest is
    reproducible: the same request returns the same numbers.
    """
    if request.strategy not in available():
        raise HTTPException(
            status_code=400,
            detail=f"unknown strategy '{request.strategy}'; available: {available()}",
        )

    try:
        strategy = build(request.strategy, **request.parameters)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid parameters: {exc}") from exc

    bars = BarRepository(session).get_bars(
        request.symbol, request.interval, limit=request.bars
    )
    if len(bars) < strategy.min_bars + 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{request.strategy} needs at least {strategy.min_bars + 1} bars; "
                f"only {len(bars)} stored for {request.symbol.upper()} "
                f"at {request.interval}"
            ),
        )

    instrument = InstrumentRepository(session).get(request.symbol)
    result = Backtester(
        strategy=strategy,
        starting_balance=request.starting_balance,
        instrument=instrument,
        interval=request.interval,
    ).run(bars)

    return BacktestOut(
        strategy=result.strategy,
        symbol=result.symbol,
        interval=result.interval,
        bars_processed=result.bars_processed,
        signals=result.signals_generated,
        executed=len(result.fills),
        rejected=len(result.rejections),
        performance=performance_out(result.report),
        equity_curve=[
            EquityPointOut(timestamp=t, equity=e)
            for t, e in zip(result.timestamps, result.equity_curve, strict=True)
        ],
        rejection_reasons=result.rejection_reasons(),
        open_position_pnl=result.open_position_pnl,
    )
