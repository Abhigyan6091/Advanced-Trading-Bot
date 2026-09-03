"""Orders and signals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import SessionDep
from app.api.presenters import order_out, signal_out
from app.api.schemas import OrderOut, SignalOut
from app.auth.dependencies import require_authenticated
from app.db.repositories import OrderRepository, SignalRepository

router = APIRouter(
    prefix="/api", tags=["orders"], dependencies=[Depends(require_authenticated)]
)


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=500),
    symbol: str | None = None,
) -> list[OrderOut]:
    return [order_out(r) for r in OrderRepository(session).recent(limit, symbol)]


@router.get("/orders/stats")
def order_stats(session: SessionDep) -> dict[str, int]:
    return OrderRepository(session).counts_by_status()


@router.get("/orders/{client_order_id}", response_model=OrderOut)
def get_order(session: SessionDep, client_order_id: str) -> OrderOut:
    row = OrderRepository(session).by_client_id(client_order_id)
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order_out(row)


@router.get("/signals", response_model=list[SignalOut])
def list_signals(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=500),
    strategy: str | None = None,
) -> list[SignalOut]:
    return [signal_out(r) for r in SignalRepository(session).recent(limit, strategy)]
