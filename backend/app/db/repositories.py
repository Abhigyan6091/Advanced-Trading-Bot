"""Repositories: the boundary between domain objects and stored rows.

Translation lives here rather than on the models so the domain layer stays free
of persistence concerns and the ORM stays free of business rules.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import ZERO
from app.db.base import utcnow
from app.db.models import (
    AuditLogRow,
    FillRow,
    InstrumentRow,
    OrderRow,
    RiskDecisionRow,
    SignalRow,
    UserRow,
)
from app.domain import (
    Fill,
    Instrument,
    Order,
    OrderStatus,
    OrderType,
    RiskAction,
    RiskCheckResult,
    RiskDecision,
    Side,
    Signal,
    SignalAction,
    TimeInForce,
)


class SignalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, signal: Signal) -> SignalRow:
        row = SignalRow(
            id=signal.id,
            strategy=signal.strategy,
            symbol=signal.symbol,
            action=signal.action.value,
            strength=signal.strength,
            reference_price=signal.reference_price,
            bar_close_time=signal.bar_close_time,
            created_at=signal.created_at,
            features={k: str(v) for k, v in signal.features.items()},
        )
        self.session.add(row)
        return row

    def recent(self, limit: int = 50, strategy: str | None = None) -> list[SignalRow]:
        stmt = select(SignalRow).order_by(SignalRow.created_at.desc()).limit(limit)
        if strategy:
            stmt = stmt.where(SignalRow.strategy == strategy)
        return list(self.session.execute(stmt).scalars())

    def strategy_names(self) -> list[str]:
        return list(self.session.execute(select(SignalRow.strategy).distinct()).scalars())


class RiskDecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, decision: RiskDecision) -> RiskDecisionRow:
        row = RiskDecisionRow(
            id=decision.id,
            signal_id=decision.signal_id,
            action=decision.action.value,
            score=decision.score,
            requested_quantity=decision.requested_quantity,
            approved_quantity=decision.approved_quantity,
            checks=[c.model_dump(mode="json") for c in decision.checks],
            created_at=decision.created_at,
        )
        self.session.add(row)
        return row

    def recent(self, limit: int = 50, action: str | None = None) -> list[RiskDecisionRow]:
        stmt = (
            select(RiskDecisionRow).order_by(RiskDecisionRow.created_at.desc()).limit(limit)
        )
        if action:
            stmt = stmt.where(RiskDecisionRow.action == action)
        return list(self.session.execute(stmt).scalars())

    def rejections(self, limit: int = 50) -> list[RiskDecisionRow]:
        return self.recent(limit=limit, action=RiskAction.REJECT.value)

    def counts_by_action(self) -> dict[str, int]:
        stmt = select(RiskDecisionRow.action, func.count()).group_by(RiskDecisionRow.action)
        return {action: count for action, count in self.session.execute(stmt)}

    def rejection_reasons(self, limit: int = 200) -> dict[str, int]:
        """Tally which checks are refusing trades, most frequent first."""
        counts: dict[str, int] = {}
        for row in self.recent(limit=limit):
            for check in row.checks or []:
                if not check.get("passed", True):
                    name = check.get("name", "unknown")
                    counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    @staticmethod
    def to_domain(row: RiskDecisionRow) -> RiskDecision:
        return RiskDecision(
            id=row.id,
            signal_id=row.signal_id or uuid.uuid4(),
            action=RiskAction(row.action),
            score=row.score,
            requested_quantity=row.requested_quantity,
            approved_quantity=row.approved_quantity,
            checks=tuple(RiskCheckResult.model_validate(c) for c in (row.checks or [])),
            created_at=row.created_at,
        )


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, order: Order) -> OrderRow:
        row = OrderRow(
            id=order.id,
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
            signal_id=order.signal_id,
            risk_decision_id=order.risk_decision_id,
            symbol=order.symbol,
            side=order.side.value,
            order_type=order.order_type.value,
            time_in_force=order.time_in_force.value,
            quantity=order.quantity,
            price=order.price,
            stop_price=order.stop_price,
            status=order.status.value,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )
        self.session.add(row)
        return row

    def by_client_id(self, client_order_id: str) -> OrderRow | None:
        return self.session.execute(
            select(OrderRow).where(OrderRow.client_order_id == client_order_id)
        ).scalar_one_or_none()

    def recent(self, limit: int = 50, symbol: str | None = None) -> list[OrderRow]:
        stmt = select(OrderRow).order_by(OrderRow.created_at.desc()).limit(limit)
        if symbol:
            stmt = stmt.where(OrderRow.symbol == symbol.upper())
        return list(self.session.execute(stmt).scalars())

    def counts_by_status(self) -> dict[str, int]:
        stmt = select(OrderRow.status, func.count()).group_by(OrderRow.status)
        return {status: count for status, count in self.session.execute(stmt)}

    @staticmethod
    def to_domain(row: OrderRow) -> Order:
        return Order(
            id=row.id,
            client_order_id=row.client_order_id,
            exchange_order_id=row.exchange_order_id,
            signal_id=row.signal_id,
            risk_decision_id=row.risk_decision_id,
            symbol=row.symbol,
            side=Side(row.side),
            order_type=OrderType(row.order_type),
            time_in_force=TimeInForce(row.time_in_force),
            quantity=row.quantity,
            price=row.price,
            stop_price=row.stop_price,
            status=OrderStatus(row.status),
            filled_quantity=row.filled_quantity,
            average_fill_price=row.average_fill_price,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class FillRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, fill: Fill) -> FillRow:
        row = FillRow(
            id=fill.id,
            order_id=fill.order_id,
            symbol=fill.symbol,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            commission=fill.commission,
            commission_asset=fill.commission_asset,
            exchange_trade_id=fill.exchange_trade_id,
            executed_at=fill.executed_at,
        )
        self.session.add(row)
        return row

    def all_fills(self, symbol: str | None = None) -> list[Fill]:
        """Every fill, oldest first — the ledger the portfolio folds over."""
        stmt = select(FillRow).order_by(FillRow.executed_at.asc())
        if symbol:
            stmt = stmt.where(FillRow.symbol == symbol.upper())
        return [self.to_domain(r) for r in self.session.execute(stmt).scalars()]

    def recent(self, limit: int = 50) -> list[FillRow]:
        stmt = select(FillRow).order_by(FillRow.executed_at.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars())

    def total_commission(self) -> Decimal:
        value = self.session.execute(select(func.sum(FillRow.commission))).scalar()
        return value if value is not None else ZERO

    @staticmethod
    def to_domain(row: FillRow) -> Fill:
        return Fill(
            id=row.id,
            order_id=row.order_id,
            symbol=row.symbol,
            side=Side(row.side),
            quantity=row.quantity,
            price=row.price,
            commission=row.commission,
            commission_asset=row.commission_asset,
            exchange_trade_id=row.exchange_trade_id,
            executed_at=row.executed_at,
        )


class InstrumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, instrument: Instrument) -> None:
        row = self.session.get(InstrumentRow, instrument.symbol)
        values = dict(
            base_asset=instrument.base_asset,
            quote_asset=instrument.quote_asset,
            tick_size=instrument.tick_size,
            step_size=instrument.step_size,
            min_quantity=instrument.min_quantity,
            min_notional=instrument.min_notional,
            max_leverage=instrument.max_leverage,
            updated_at=datetime.now(timezone.utc),
        )
        if row is None:
            self.session.add(InstrumentRow(symbol=instrument.symbol, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)

    def all_instruments(self) -> list[Instrument]:
        rows = self.session.execute(
            select(InstrumentRow).where(InstrumentRow.is_active.is_(True))
        ).scalars()
        return [self.to_domain(r) for r in rows]

    def get(self, symbol: str) -> Instrument | None:
        row = self.session.get(InstrumentRow, symbol.upper())
        return self.to_domain(row) if row else None

    @staticmethod
    def to_domain(row: InstrumentRow) -> Instrument:
        return Instrument(
            symbol=row.symbol,
            base_asset=row.base_asset,
            quote_asset=row.quote_asset,
            tick_size=row.tick_size,
            step_size=row.step_size,
            min_quantity=row.min_quantity,
            min_notional=row.min_notional,
            max_leverage=row.max_leverage,
        )


class AuditRepository:
    """Append-only record of state-changing actions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        actor: str = "system",
        detail: dict | None = None,
        note: str | None = None,
    ) -> None:
        self.session.add(
            AuditLogRow(
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                detail=detail or {},
                note=note,
            )
        )

    def recent(self, limit: int = 100) -> list[AuditLogRow]:
        stmt = select(AuditLogRow).order_by(AuditLogRow.created_at.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars())


def utc_day_start(when: datetime | None = None) -> datetime:
    when = when or datetime.now(timezone.utc)
    return when.replace(hour=0, minute=0, second=0, microsecond=0)


def utc_days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


__all__ = [
    "AuditRepository",
    "UserRepository",
    "FillRepository",
    "InstrumentRepository",
    "OrderRepository",
    "RiskDecisionRepository",
    "SignalAction",
    "SignalRepository",
    "utc_day_start",
    "utc_days_ago",
]


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_username(self, username: str) -> UserRow | None:
        return self.session.execute(
            select(UserRow).where(UserRow.username == username)
        ).scalar_one_or_none()

    def create(self, username: str, password_hash: str, role: str) -> UserRow:
        row = UserRow(username=username, password_hash=password_hash, role=role)
        self.session.add(row)
        self.session.flush()
        return row

    def record_login(self, user: UserRow) -> None:
        user.last_login_at = utcnow()

    def any_exist(self) -> bool:
        return self.session.execute(select(UserRow.id).limit(1)).first() is not None
