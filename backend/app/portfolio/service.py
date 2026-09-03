"""Portfolio state, derived from fills.

Positions, cash and P&L are computed by folding the fill ledger, never stored
as independent counters that could drift out of agreement with it. Rebuilding
from fills always reproduces the current state, which is what makes the
numbers auditable.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.money import ZERO, D
from app.domain import Fill, Position
from app.risk import AccountSnapshot


class PortfolioSnapshot(BaseModel):
    """The portfolio as of one instant, for the dashboard and the risk engine."""

    model_config = ConfigDict(frozen=True)

    cash: Decimal
    positions: tuple[Position, ...] = ()
    mark_prices: dict[str, Decimal] = Field(default_factory=dict)

    realized_pnl: Decimal = ZERO
    total_commission: Decimal = ZERO
    starting_balance: Decimal = ZERO
    peak_equity: Decimal = ZERO
    daily_pnl: Decimal = ZERO
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def unrealized_pnl(self) -> Decimal:
        total = ZERO
        for p in self.positions:
            mark = self.mark_prices.get(p.symbol)
            if mark is not None:
                total += p.unrealized_pnl(mark)
        return total

    @property
    def position_value(self) -> Decimal:
        """Signed market value of open positions."""
        total = ZERO
        for p in self.positions:
            mark = self.mark_prices.get(p.symbol)
            if mark is not None:
                total += p.signed_quantity * mark
        return total

    @property
    def equity(self) -> Decimal:
        """Cash plus the market value of open positions."""
        return self.cash + self.position_value

    @property
    def gross_exposure(self) -> Decimal:
        total = ZERO
        for p in self.positions:
            mark = self.mark_prices.get(p.symbol)
            if mark is not None:
                total += p.notional_value(mark)
        return total

    @property
    def leverage(self) -> Decimal:
        equity = self.equity
        return self.gross_exposure / equity if equity > ZERO else ZERO

    @property
    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def total_return(self) -> Decimal:
        if self.starting_balance <= ZERO:
            return ZERO
        return (self.equity - self.starting_balance) / self.starting_balance

    @property
    def drawdown(self) -> Decimal:
        peak = max(self.peak_equity, self.equity)
        if peak <= ZERO or self.equity >= peak:
            return ZERO
        return (peak - self.equity) / peak

    @property
    def open_positions(self) -> tuple[Position, ...]:
        return tuple(p for p in self.positions if not p.is_flat)

    def to_account(self, volatility: Decimal | None = None) -> AccountSnapshot:
        """Adapt to the input the risk engine expects.

        Keeping this conversion explicit means the risk engine depends on a
        small value object rather than on the portfolio service.
        """
        return AccountSnapshot(
            equity=max(self.equity, D("0.01")),
            cash=max(self.cash, ZERO),
            positions=self.open_positions,
            mark_prices=self.mark_prices,
            daily_pnl=self.daily_pnl,
            peak_equity=max(self.peak_equity, self.equity),
            volatility=volatility,
        )


class Portfolio:
    """Mutable portfolio built by applying fills in order."""

    def __init__(self, starting_balance: Decimal | str = "100000") -> None:
        self.starting_balance = D(starting_balance)
        self.cash = self.starting_balance
        self.realized_pnl = ZERO
        self.total_commission = ZERO
        self.peak_equity = self.starting_balance

        self._positions: dict[str, Position] = {}
        self._marks: dict[str, Decimal] = {}
        self._daily: dict[date, Decimal] = {}

    # --- state ---------------------------------------------------------

    def set_mark(self, symbol: str, price: Decimal | str) -> None:
        self._marks[symbol] = D(price)
        # Marking to market can set a new equity high, which the drawdown
        # calculation depends on.
        self.peak_equity = max(self.peak_equity, self.equity)

    def position(self, symbol: str) -> Position:
        return self._positions.get(symbol) or Position.flat(symbol)

    @property
    def positions(self) -> tuple[Position, ...]:
        return tuple(p for p in self._positions.values() if not p.is_flat)

    @property
    def equity(self) -> Decimal:
        value = ZERO
        for p in self._positions.values():
            mark = self._marks.get(p.symbol)
            if mark is not None:
                value += p.signed_quantity * mark
        return self.cash + value

    # --- ledger --------------------------------------------------------

    def apply_fill(self, fill: Fill) -> None:
        """Fold one execution into the portfolio.

        Cash moves by the fill's signed value; realised P&L is whatever the
        position accounting recognised on the closed portion.
        """
        before = self.position(fill.symbol)
        after = before.apply_fill(fill)
        self._positions[fill.symbol] = after

        realized_delta = after.realized_pnl - before.realized_pnl
        self.realized_pnl += realized_delta
        self.total_commission += fill.commission

        self.cash += fill.net_value
        self._marks.setdefault(fill.symbol, fill.price)

        day = fill.executed_at.date()
        self._daily[day] = self._daily.get(day, ZERO) + realized_delta - fill.commission

        self.peak_equity = max(self.peak_equity, self.equity)

    def apply_fills(self, fills: list[Fill]) -> None:
        for fill in sorted(fills, key=lambda f: f.executed_at):
            self.apply_fill(fill)

    def daily_pnl(self, day: date | None = None) -> Decimal:
        """Realised P&L for a day, net of commission."""
        day = day or datetime.now(timezone.utc).date()
        return self._daily.get(day, ZERO)

    # --- output --------------------------------------------------------

    def snapshot(self, day: date | None = None) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            cash=self.cash,
            positions=self.positions,
            mark_prices=dict(self._marks),
            realized_pnl=self.realized_pnl,
            total_commission=self.total_commission,
            starting_balance=self.starting_balance,
            peak_equity=self.peak_equity,
            daily_pnl=self.daily_pnl(day),
        )

    @classmethod
    def from_fills(
        cls, fills: list[Fill], starting_balance: Decimal | str = "100000"
    ) -> Portfolio:
        """Rebuild a portfolio by replaying its ledger."""
        portfolio = cls(starting_balance)
        portfolio.apply_fills(fills)
        return portfolio
