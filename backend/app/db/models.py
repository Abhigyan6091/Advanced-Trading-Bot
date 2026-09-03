"""Persistence models.

Deliberately separate from the domain models in ``app.domain``. The domain
layer expresses business rules and stays free of SQLAlchemy; this layer
expresses storage. Keeping them apart is what lets the backtester run the same
domain logic with no database at all.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Money, OptMoney, Symbol, Timestamp, UUIDPk, utcnow


class InstrumentRow(Base):
    """Exchange trading rules, refreshed from the venue."""

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    base_asset: Mapped[str] = mapped_column(String(20))
    quote_asset: Mapped[str] = mapped_column(String(20))

    tick_size: Mapped[Money]
    step_size: Mapped[Money]
    min_quantity: Mapped[Money]
    min_notional: Mapped[Money]
    max_leverage: Mapped[int] = mapped_column(Integer, default=1)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[Timestamp] = mapped_column(default=utcnow)


class BarRow(Base):
    """Historical OHLCV, the input to both strategies and backtests."""

    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "open_time", name="uq_bar_symbol_interval_open"),
        Index("ix_bars_symbol_interval_close", "symbol", "interval", "close_time"),
    )

    id: Mapped[UUIDPk]
    symbol: Mapped[Symbol]
    interval: Mapped[str] = mapped_column(String(10))

    open_time: Mapped[Timestamp]
    close_time: Mapped[Timestamp]

    open: Mapped[Money]
    high: Mapped[Money]
    low: Mapped[Money]
    close: Mapped[Money]
    volume: Mapped[Money]


class SignalRow(Base):
    """Every signal a strategy emitted, actionable or not.

    HOLD signals are stored too: strategy behaviour cannot be evaluated from
    its trades alone.
    """

    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_strategy_created", "strategy", "created_at"),)

    id: Mapped[UUIDPk]
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[Symbol]

    action: Mapped[str] = mapped_column(String(8))
    strength: Mapped[Money]
    reference_price: Mapped[Money]

    bar_close_time: Mapped[Timestamp]
    created_at: Mapped[Timestamp] = mapped_column(default=utcnow, index=True)

    features: Mapped[dict] = mapped_column(JSONB, default=dict)

    decisions: Mapped[list[RiskDecisionRow]] = relationship(back_populates="signal")


class RiskDecisionRow(Base):
    """A risk verdict, stored whether or not it produced an order.

    This table is what makes "why was my BTC trade rejected?" answerable from
    data instead of from inference.
    """

    __tablename__ = "risk_decisions"
    __table_args__ = (Index("ix_risk_decisions_action_created", "action", "created_at"),)

    id: Mapped[UUIDPk]
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(8))
    score: Mapped[Money]

    requested_quantity: Mapped[Money]
    approved_quantity: Mapped[Money]

    #: Full per-check breakdown: name, passed, score, weight, observed, limit,
    #: reason. Stored as a document because it is read as a whole and its shape
    #: evolves as checks are added.
    checks: Mapped[list] = mapped_column(JSONB, default=list)

    created_at: Mapped[Timestamp] = mapped_column(default=utcnow, index=True)

    signal: Mapped[SignalRow | None] = relationship(back_populates="decisions")
    orders: Mapped[list[OrderRow]] = relationship(back_populates="risk_decision")


class OrderRow(Base):
    """Orders. ``client_order_id`` is unique — that is the idempotency guard."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
        Index("ix_orders_symbol_status", "symbol", "status"),
    )

    id: Mapped[UUIDPk]
    client_order_id: Mapped[str] = mapped_column(String(64))
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True
    )
    risk_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_decisions.id", ondelete="SET NULL"), nullable=True
    )

    symbol: Mapped[Symbol]
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(16))
    time_in_force: Mapped[str] = mapped_column(String(4), default="GTC")

    quantity: Mapped[Money]
    price: Mapped[OptMoney]
    stop_price: Mapped[OptMoney]

    status: Mapped[str] = mapped_column(String(20), index=True)
    filled_quantity: Mapped[Money] = mapped_column(default=Decimal("0"))
    average_fill_price: Mapped[OptMoney]

    created_at: Mapped[Timestamp] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[Timestamp] = mapped_column(default=utcnow, onupdate=utcnow)

    risk_decision: Mapped[RiskDecisionRow | None] = relationship(back_populates="orders")
    fills: Mapped[list[FillRow]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class FillRow(Base):
    """Executions. The ledger every position and P&L figure is derived from."""

    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("exchange_trade_id", name="uq_fills_exchange_trade_id"),
        Index("ix_fills_symbol_executed", "symbol", "executed_at"),
    )

    id: Mapped[UUIDPk]
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )

    symbol: Mapped[Symbol]
    side: Mapped[str] = mapped_column(String(4))

    quantity: Mapped[Money]
    price: Mapped[Money]
    commission: Mapped[Money] = mapped_column(default=Decimal("0"))
    commission_asset: Mapped[str] = mapped_column(String(10), default="USDT")

    #: Nullable but unique: duplicate venue execution reports are discarded.
    exchange_trade_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    executed_at: Mapped[Timestamp] = mapped_column(default=utcnow, index=True)

    order: Mapped[OrderRow] = relationship(back_populates="fills")


class AuditLogRow(Base):
    """Append-only record of every state-changing action.

    Written on the same transaction as the change it describes, so the log
    cannot disagree with the data.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity_created", "entity_type", "entity_id", "created_at"),)

    id: Mapped[UUIDPk]
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)

    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[Timestamp] = mapped_column(default=utcnow, index=True)


__all__ = [
    "AuditLogRow",
    "BarRow",
    "FillRow",
    "InstrumentRow",
    "OrderRow",
    "RiskDecisionRow",
    "SignalRow",
]
