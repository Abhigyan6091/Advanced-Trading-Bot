"""Performance metrics.

Shared by the live portfolio and the backtester, so a strategy's reported
Sharpe means the same thing in both places. Everything is computed from an
equity curve and a trade list — the same inputs either source can produce.

All returns are simple (arithmetic), not logarithmic, and all figures are
``Decimal``.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import NamedTuple

from app.core.money import PRECISION, ZERO, D

#: Bars per year, used to annualise. A trading strategy on hourly crypto bars
#: runs continuously, so there are no market holidays to discount.
PERIODS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "30m": 17_520,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


class TradeRecord(NamedTuple):
    """One round trip, for win-rate and profit-factor statistics."""

    symbol: str
    pnl: Decimal


def returns(equity_curve: list[Decimal]) -> list[Decimal]:
    """Period-over-period simple returns."""
    out: list[Decimal] = []
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for i in range(1, len(equity_curve)):
            previous = equity_curve[i - 1]
            out.append((equity_curve[i] - previous) / previous if previous != ZERO else ZERO)
    return out


def total_return(equity_curve: list[Decimal]) -> Decimal:
    if len(equity_curve) < 2 or equity_curve[0] == ZERO:
        return ZERO
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (equity_curve[-1] - equity_curve[0]) / equity_curve[0]


def max_drawdown(equity_curve: list[Decimal]) -> Decimal:
    """Largest peak-to-trough decline, as a positive fraction.

    Measured on the running peak rather than the starting value: a strategy
    that doubles and then halves has a 50% drawdown, not none.
    """
    if not equity_curve:
        return ZERO
    peak = equity_curve[0]
    worst = ZERO
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for value in equity_curve:
            peak = max(peak, value)
            if peak > ZERO:
                worst = max(worst, (peak - value) / peak)
    return worst


def sharpe_ratio(
    equity_curve: list[Decimal],
    interval: str = "1h",
    risk_free_rate: Decimal = ZERO,
) -> Decimal:
    """Annualised Sharpe ratio.

    Zero when there is no variation in returns: a flat curve has no risk to
    reward, and dividing by zero deviation would report infinite skill.
    """
    series = returns(equity_curve)
    if len(series) < 2:
        return ZERO

    periods = PERIODS_PER_YEAR.get(interval, 8_760)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        periodic_rf = risk_free_rate / periods
        excess = [r - periodic_rf for r in series]

        mean = sum(excess) / len(excess)
        variance = sum((r - mean) ** 2 for r in excess) / len(excess)
        if variance <= ZERO:
            return ZERO

        return (mean / variance.sqrt()) * Decimal(periods).sqrt()


def sortino_ratio(
    equity_curve: list[Decimal], interval: str = "1h", risk_free_rate: Decimal = ZERO
) -> Decimal:
    """Sharpe's downside-only counterpart: upside volatility is not a risk."""
    series = returns(equity_curve)
    if len(series) < 2:
        return ZERO

    periods = PERIODS_PER_YEAR.get(interval, 8_760)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        periodic_rf = risk_free_rate / periods
        excess = [r - periodic_rf for r in series]
        mean = sum(excess) / len(excess)

        downside = [r for r in excess if r < ZERO]
        if not downside:
            return ZERO
        deviation = (sum(r**2 for r in downside) / len(excess)).sqrt()
        if deviation <= ZERO:
            return ZERO
        return (mean / deviation) * Decimal(periods).sqrt()


def win_rate(trades: list[TradeRecord]) -> Decimal:
    """Fraction of round trips that made money. Break-even counts as a loss."""
    if not trades:
        return ZERO
    wins = sum(1 for t in trades if t.pnl > ZERO)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return Decimal(wins) / Decimal(len(trades))


def profit_factor(trades: list[TradeRecord]) -> Decimal | None:
    """Gross profit divided by gross loss.

    ``None`` when there are no losses: the ratio is undefined rather than
    infinite, and reporting a number there would be misleading.
    """
    gross_profit = sum((t.pnl for t in trades if t.pnl > ZERO), ZERO)
    gross_loss = sum((-t.pnl for t in trades if t.pnl < ZERO), ZERO)
    if gross_loss == ZERO:
        return None
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return gross_profit / gross_loss


def average_win_loss(trades: list[TradeRecord]) -> tuple[Decimal, Decimal]:
    wins = [t.pnl for t in trades if t.pnl > ZERO]
    losses = [-t.pnl for t in trades if t.pnl < ZERO]
    with localcontext() as ctx:
        ctx.prec = PRECISION
        avg_win = sum(wins) / len(wins) if wins else ZERO
        avg_loss = sum(losses) / len(losses) if losses else ZERO
    return avg_win, avg_loss


def expectancy(trades: list[TradeRecord]) -> Decimal:
    """Average P&L per trade — the figure that decides whether to keep going."""
    if not trades:
        return ZERO
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return sum((t.pnl for t in trades), ZERO) / len(trades)


def calmar_ratio(equity_curve: list[Decimal]) -> Decimal | None:
    """Total return over maximum drawdown. ``None`` when there is no drawdown."""
    drawdown = max_drawdown(equity_curve)
    if drawdown == ZERO:
        return None
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return total_return(equity_curve) / drawdown


class PerformanceReport(NamedTuple):
    """The full metric set, computed once from a curve and its trades."""

    starting_equity: Decimal
    ending_equity: Decimal
    total_return: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    max_drawdown: Decimal
    calmar_ratio: Decimal | None
    win_rate: Decimal
    profit_factor: Decimal | None
    expectancy: Decimal
    average_win: Decimal
    average_loss: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int

    def summary(self) -> str:
        def pct(value: Decimal) -> str:
            return f"{value * 100:.2f}%"

        def num(value: Decimal | None) -> str:
            return "n/a" if value is None else f"{value:.2f}"

        return "\n".join(
            [
                f"Total return    : {pct(self.total_return)}",
                f"Sharpe ratio    : {num(self.sharpe_ratio)}",
                f"Sortino ratio   : {num(self.sortino_ratio)}",
                f"Max drawdown    : {pct(self.max_drawdown)}",
                f"Calmar ratio    : {num(self.calmar_ratio)}",
                f"Win rate        : {pct(self.win_rate)}",
                f"Profit factor   : {num(self.profit_factor)}",
                f"Expectancy      : {num(self.expectancy)}",
                f"Trades          : {self.total_trades} "
                f"({self.winning_trades}W / {self.losing_trades}L)",
            ]
        )


def build_report(
    equity_curve: list[Decimal],
    trades: list[TradeRecord],
    interval: str = "1h",
) -> PerformanceReport:
    """Compute every metric from one curve and its trade list."""
    curve = [D(v) for v in equity_curve] or [ZERO]
    avg_win, avg_loss = average_win_loss(trades)

    return PerformanceReport(
        starting_equity=curve[0],
        ending_equity=curve[-1],
        total_return=total_return(curve),
        sharpe_ratio=sharpe_ratio(curve, interval),
        sortino_ratio=sortino_ratio(curve, interval),
        max_drawdown=max_drawdown(curve),
        calmar_ratio=calmar_ratio(curve),
        win_rate=win_rate(trades),
        profit_factor=profit_factor(trades),
        expectancy=expectancy(trades),
        average_win=avg_win,
        average_loss=avg_loss,
        total_trades=len(trades),
        winning_trades=sum(1 for t in trades if t.pnl > ZERO),
        losing_trades=sum(1 for t in trades if t.pnl < ZERO),
    )
