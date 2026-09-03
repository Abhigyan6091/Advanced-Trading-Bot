"""API response models.

Decimals are serialised as strings, never as JSON numbers. A JSON number is an
IEEE double in most clients, so sending 0.00000001 as a number reintroduces at
the wire exactly the precision loss the rest of the platform avoids.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(str, return_type=str)]
OptMoney = Annotated[Decimal | None, PlainSerializer(lambda v: None if v is None else str(v))]


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PositionOut(Base):
    symbol: str
    side: str
    quantity: Money
    signed_quantity: Money
    average_entry_price: Money
    mark_price: OptMoney = None
    notional: OptMoney = None
    unrealized_pnl: OptMoney = None
    realized_pnl: Money


class PortfolioOut(Base):
    equity: Money
    cash: Money
    position_value: Money
    starting_balance: Money
    realized_pnl: Money
    unrealized_pnl: Money
    total_pnl: Money
    total_return: Money
    total_commission: Money
    gross_exposure: Money
    leverage: Money
    drawdown: Money
    peak_equity: Money
    daily_pnl: Money
    open_position_count: int
    positions: list[PositionOut]
    as_of: datetime


class EquityPointOut(Base):
    timestamp: datetime
    equity: Money


class BarOut(Base):
    open_time: datetime
    close_time: datetime
    open: Money
    high: Money
    low: Money
    close: Money
    volume: Money


class MarketOut(Base):
    symbol: str
    base_asset: str
    quote_asset: str
    tick_size: Money
    step_size: Money
    min_quantity: Money
    min_notional: Money
    max_leverage: int
    last_price: OptMoney = None
    change_24h: OptMoney = None


class RiskCheckOut(Base):
    name: str
    passed: bool
    score: Money
    weight: Money
    observed: OptMoney = None
    limit: OptMoney = None
    utilisation: OptMoney = None
    reason: str = ""


class RiskDecisionOut(Base):
    id: str
    signal_id: str | None = None
    symbol: str | None = None
    strategy: str | None = None
    action: str
    score: Money
    requested_quantity: Money
    approved_quantity: Money
    reasons: list[str]
    checks: list[RiskCheckOut]
    created_at: datetime


class RiskSummaryOut(Base):
    limits: dict[str, str]
    decision_counts: dict[str, int]
    rejection_reasons: dict[str, int]
    current_score: Money
    approval_rate: Money
    recent: list[RiskDecisionOut]


class OrderOut(Base):
    id: str
    client_order_id: str
    exchange_order_id: str | None = None
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: Money
    filled_quantity: Money
    price: OptMoney = None
    average_fill_price: OptMoney = None
    risk_decision_id: str | None = None
    signal_id: str | None = None
    created_at: datetime


class FillOut(Base):
    id: str
    order_id: str
    symbol: str
    side: str
    quantity: Money
    price: Money
    commission: Money
    executed_at: datetime


class SignalOut(Base):
    id: str
    strategy: str
    symbol: str
    action: str
    strength: Money
    reference_price: Money
    bar_close_time: datetime
    created_at: datetime
    features: dict[str, Any]


class StrategyOut(Base):
    name: str
    parameters: dict[str, Any]
    signals: int
    actionable: int
    approved: int
    reduced: int
    rejected: int
    realized_pnl: Money


class PerformanceOut(Base):
    starting_equity: Money
    ending_equity: Money
    total_return: Money
    sharpe_ratio: Money
    sortino_ratio: OptMoney = None
    max_drawdown: Money
    calmar_ratio: OptMoney = None
    win_rate: Money
    profit_factor: OptMoney = None
    expectancy: Money
    average_win: Money
    average_loss: Money
    total_trades: int
    winning_trades: int
    losing_trades: int


class BacktestRequest(BaseModel):
    strategy: str = "ema_crossover"
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    bars: int = Field(default=500, ge=1, le=1500)
    starting_balance: Decimal = Field(default=Decimal("100000"), gt=0)
    parameters: dict[str, Any] = {}


class BacktestOut(Base):
    strategy: str
    symbol: str
    interval: str
    bars_processed: int
    signals: int
    executed: int
    rejected: int
    performance: PerformanceOut
    equity_curve: list[EquityPointOut]
    rejection_reasons: dict[str, int]
    open_position_pnl: Money


class OverviewOut(Base):
    portfolio: PortfolioOut
    risk_score: Money
    open_orders: int
    signals_today: int
    rejected_today: int
    strategies: int
    broker: str
    live_trading: bool
