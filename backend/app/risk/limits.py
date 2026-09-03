"""Risk limits and the account snapshot they are evaluated against.

Limits are configuration, not code. Keeping them in one validated object means
the same numbers drive the live engine, the backtester and the dashboard, and
that a limit change is a data change rather than an edit to a check.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.money import ZERO
from app.domain import Position


class RiskLimits(BaseModel):
    """The account's risk budget.

    Defaults are deliberately conservative: a misconfigured platform should
    refuse trades, not permit them.
    """

    model_config = ConfigDict(frozen=True)

    #: Largest single position as a fraction of account equity.
    max_position_pct: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)

    #: Largest combined gross exposure as a fraction of equity.
    max_portfolio_exposure_pct: Decimal = Field(default=Decimal("0.60"), gt=0, le=5)

    #: Gross exposure divided by equity.
    max_leverage: Decimal = Field(default=Decimal("3"), ge=1, le=125)

    #: Realised + unrealised loss allowed in a day, as a fraction of equity.
    max_daily_loss_pct: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)

    #: Peak-to-trough equity decline before trading stops.
    max_drawdown_pct: Decimal = Field(default=Decimal("0.20"), gt=0, le=1)

    #: Annualised realised volatility above which size is cut.
    max_volatility: Decimal = Field(default=Decimal("1.50"), gt=0)

    #: Hard ceiling on a single order's notional, in quote currency.
    max_order_value: Decimal = Field(default=Decimal("50000"), gt=0)

    #: Utilisation beyond which a breach is treated as an error rather than
    #: an intention. A request 10x past a limit is far more likely a mistake
    #: than a deliberate position, and silently filling 10% of it is worse
    #: than refusing it.
    gross_breach_multiple: Decimal = Field(default=Decimal("10"), gt=1)

    #: Score at or above which a trade is refused outright.
    reject_score: Decimal = Field(default=Decimal("75"), gt=0, le=100)

    #: Score at or above which a trade is allowed but resized.
    reduce_score: Decimal = Field(default=Decimal("45"), gt=0, le=100)

    @model_validator(mode="after")
    def _thresholds_are_ordered(self) -> RiskLimits:
        if self.reduce_score >= self.reject_score:
            raise ValueError("reduce_score must be below reject_score")
        return self


class AccountSnapshot(BaseModel):
    """The account state a decision is evaluated against.

    A snapshot rather than a live handle: every check in one decision sees the
    same numbers, so a decision is reproducible from what was stored with it.
    """

    model_config = ConfigDict(frozen=True)

    equity: Decimal = Field(gt=0)
    cash: Decimal = Field(ge=0)

    positions: tuple[Position, ...] = ()
    mark_prices: dict[str, Decimal] = Field(default_factory=dict)

    #: Realised + unrealised P&L so far today. Negative is a loss.
    daily_pnl: Decimal = ZERO

    #: Highest equity reached, used for the drawdown check.
    peak_equity: Decimal | None = None

    #: Annualised realised volatility of the symbol being traded.
    volatility: Decimal | None = None

    def mark(self, symbol: str) -> Decimal | None:
        return self.mark_prices.get(symbol)

    def position(self, symbol: str) -> Position:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return Position.flat(symbol)

    @property
    def gross_exposure(self) -> Decimal:
        """Total absolute notional across all positions.

        Gross rather than net: a long and a short of equal size are two
        positions that can each move against you, not a flat book.
        """
        total = ZERO
        for p in self.positions:
            mark = self.mark_prices.get(p.symbol)
            if mark is not None:
                total += p.notional_value(mark)
        return total

    @property
    def leverage(self) -> Decimal:
        return self.gross_exposure / self.equity if self.equity > ZERO else ZERO

    @property
    def drawdown(self) -> Decimal:
        """Fractional decline from peak equity. Zero when at a high."""
        peak = self.peak_equity if self.peak_equity is not None else self.equity
        if peak <= ZERO or self.equity >= peak:
            return ZERO
        return (peak - self.equity) / peak

    @property
    def daily_loss_pct(self) -> Decimal:
        """Today's loss as a positive fraction of equity. Zero when profitable."""
        if self.daily_pnl >= ZERO or self.equity <= ZERO:
            return ZERO
        return -self.daily_pnl / self.equity
