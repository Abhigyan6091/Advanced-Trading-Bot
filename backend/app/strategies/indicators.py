"""Technical indicators.

All of these are pure functions over a chronological price series, computed in
``Decimal`` to stay consistent with the rest of the platform.

Two conventions hold throughout:

* Every function returns a list the **same length** as its input, with ``None``
  in the warm-up positions where the indicator is not yet defined. Returning a
  shorter list would silently shift indices relative to the bar series, which
  is how off-by-one look-ahead bugs get introduced.
* Index ``i`` of a result uses only prices at indices ``<= i``. No function
  looks forward.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext

from app.core.money import PRECISION, ZERO

Series = Sequence[Decimal]
OptSeries = list[Decimal | None]


def sma(values: Series, period: int) -> OptSeries:
    """Simple moving average."""
    _check_period(period)
    out: OptSeries = [None] * len(values)
    if len(values) < period:
        return out

    with localcontext() as ctx:
        ctx.prec = PRECISION
        window = sum(values[:period])
        out[period - 1] = window / period
        for i in range(period, len(values)):
            window += values[i] - values[i - period]
            out[i] = window / period
    return out


def ema(values: Series, period: int) -> OptSeries:
    """Exponential moving average, seeded with the simple average.

    Seeding with an SMA of the first ``period`` values rather than the first
    value alone removes the long start-up bias that otherwise contaminates the
    earliest signals.
    """
    _check_period(period)
    out: OptSeries = [None] * len(values)
    if len(values) < period:
        return out

    with localcontext() as ctx:
        ctx.prec = PRECISION
        alpha = Decimal(2) / (Decimal(period) + 1)
        prev = sum(values[:period]) / period
        out[period - 1] = prev
        for i in range(period, len(values)):
            prev = alpha * values[i] + (1 - alpha) * prev
            out[i] = prev
    return out


def rsi(values: Series, period: int = 14) -> OptSeries:
    """Relative strength index using Wilder's smoothing.

    Defined from index ``period`` onward: the first value needs ``period``
    price *changes*, which requires ``period + 1`` prices.
    """
    _check_period(period)
    out: OptSeries = [None] * len(values)
    if len(values) <= period:
        return out

    with localcontext() as ctx:
        ctx.prec = PRECISION
        gains: list[Decimal] = []
        losses: list[Decimal] = []
        for i in range(1, len(values)):
            change = values[i] - values[i - 1]
            gains.append(change if change > 0 else ZERO)
            losses.append(-change if change < 0 else ZERO)

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        out[period] = _rsi_from_averages(avg_gain, avg_loss)

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            out[i + 1] = _rsi_from_averages(avg_gain, avg_loss)
    return out


def _rsi_from_averages(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
    if avg_loss == ZERO:
        # Unbroken gains: RSI is 100 by definition, and RS would divide by zero.
        return Decimal(100) if avg_gain > ZERO else Decimal(50)
    rs = avg_gain / avg_loss
    return Decimal(100) - (Decimal(100) / (1 + rs))


def macd(
    values: Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[OptSeries, OptSeries, OptSeries]:
    """Moving average convergence/divergence.

    Returns ``(macd_line, signal_line, histogram)``. The signal line is an EMA
    of the MACD line, so it is computed only over the positions where the MACD
    line exists and then mapped back onto the original indices.
    """
    if fast >= slow:
        raise ValueError("fast period must be shorter than slow period")

    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)

    macd_line: OptSeries = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_ema, slow_ema, strict=True)
    ]

    defined = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line: OptSeries = [None] * len(values)
    if len(defined) >= signal:
        signal_values = ema([v for _, v in defined], signal)
        for (idx, _), sig in zip(defined, signal_values, strict=True):
            signal_line[idx] = sig

    histogram: OptSeries = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line, strict=True)
    ]
    return macd_line, signal_line, histogram


def stddev(values: Series, period: int) -> OptSeries:
    """Rolling population standard deviation."""
    _check_period(period)
    out: OptSeries = [None] * len(values)
    if len(values) < period:
        return out

    with localcontext() as ctx:
        ctx.prec = PRECISION
        for i in range(period - 1, len(values)):
            window = values[i - period + 1 : i + 1]
            mean = sum(window) / period
            variance = sum((v - mean) ** 2 for v in window) / period
            out[i] = variance.sqrt()
    return out


def zscore(values: Series, period: int) -> OptSeries:
    """Standard scores against a rolling mean.

    ``None`` where the rolling deviation is zero: a flat window has no scale,
    so "how far from normal" is undefined rather than infinite.
    """
    means = sma(values, period)
    devs = stddev(values, period)

    out: OptSeries = [None] * len(values)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for i, (m, d) in enumerate(zip(means, devs, strict=True)):
            if m is not None and d is not None and d != ZERO:
                out[i] = (values[i] - m) / d
    return out


def true_range(highs: Series, lows: Series, closes: Series) -> OptSeries:
    """True range. Undefined at index 0, which has no previous close."""
    out: OptSeries = [None] * len(closes)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for i in range(1, len(closes)):
            prev_close = closes[i - 1]
            out[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
    return out


def atr(highs: Series, lows: Series, closes: Series, period: int = 14) -> OptSeries:
    """Average true range, Wilder-smoothed. The volatility input to risk sizing."""
    _check_period(period)
    tr = true_range(highs, lows, closes)
    out: OptSeries = [None] * len(closes)

    defined = [v for v in tr if v is not None]
    if len(defined) < period:
        return out

    with localcontext() as ctx:
        ctx.prec = PRECISION
        prev = sum(defined[:period]) / period
        out[period] = prev
        for i in range(period, len(defined)):
            prev = (prev * (period - 1) + defined[i]) / period
            out[i + 1] = prev
    return out


def realized_volatility(closes: Series, period: int) -> OptSeries:
    """Standard deviation of simple returns over a rolling window."""
    _check_period(period)
    out: OptSeries = [None] * len(closes)
    if len(closes) <= period:
        return out

    with localcontext() as ctx:
        ctx.prec = PRECISION
        returns: list[Decimal] = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            returns.append((closes[i] - prev) / prev if prev != ZERO else ZERO)

        for i in range(period - 1, len(returns)):
            window = returns[i - period + 1 : i + 1]
            mean = sum(window) / period
            variance = sum((r - mean) ** 2 for r in window) / period
            out[i + 1] = variance.sqrt()
    return out


def _check_period(period: int) -> None:
    if period < 1:
        raise ValueError("period must be at least 1")
