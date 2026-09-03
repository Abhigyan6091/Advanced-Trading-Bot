"""Instruments and price history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep
from app.api.schemas import BarOut, MarketOut
from app.core.money import ZERO, pct_change
from app.db.repositories import InstrumentRepository
from app.marketdata import BarRepository, validate_interval

router = APIRouter(prefix="/api/markets", tags=["markets"])


@router.get("", response_model=list[MarketOut])
def list_markets(session: SessionDep, interval: str = "1h") -> list[MarketOut]:
    instruments = InstrumentRepository(session).all_instruments()
    bars_repo = BarRepository(session)

    out: list[MarketOut] = []
    for instrument in instruments:
        bars = bars_repo.get_bars(instrument.symbol, interval, limit=25)
        last = bars[-1].close if bars else None
        change = None
        if len(bars) >= 25 and bars[-25].close != ZERO:
            change = pct_change(bars[-25].close, bars[-1].close)

        out.append(
            MarketOut(
                **instrument.model_dump(),
                last_price=last,
                change_24h=change,
            )
        )
    return out


@router.get("/{symbol}/bars", response_model=list[BarOut])
def bars(
    session: SessionDep,
    symbol: str,
    interval: str = "1h",
    limit: int = Query(default=200, ge=1, le=1500),
) -> list[BarOut]:
    try:
        validate_interval(interval)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rows = BarRepository(session).get_bars(symbol, interval, limit)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"no {interval} bars stored for {symbol.upper()}",
        )
    return [BarOut(**b.model_dump(exclude={"symbol"})) for b in rows]


@router.get("/{symbol}", response_model=MarketOut)
def market(session: SessionDep, symbol: str, interval: str = "1h") -> MarketOut:
    instrument = InstrumentRepository(session).get(symbol)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"unknown symbol {symbol.upper()}")

    bars_list = BarRepository(session).get_bars(instrument.symbol, interval, limit=25)
    last = bars_list[-1].close if bars_list else None
    change = None
    if len(bars_list) >= 25 and bars_list[-25].close != ZERO:
        change = pct_change(bars_list[-25].close, bars_list[-1].close)

    return MarketOut(**instrument.model_dump(), last_price=last, change_24h=change)
