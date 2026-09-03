"""Exact decimal arithmetic for prices, quantities and money.

Rules enforced here, applied everywhere else in the platform:

* Money and quantities are ``Decimal``. ``float`` never crosses a boundary.
  Binary floating point cannot represent exchange tick sizes such as 0.1
  exactly, and the error accumulates through a P&L series.
* Prices snap to an instrument's ``tick_size``; quantities snap to its
  ``step_size``.
* Quantities always round *down*. Rounding a quantity up can request more size
  than the account can fund, so the conservative direction is the only safe one.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

# PEP 604 union; a runtime alias rather than a deferred annotation.
Numeric = Decimal | int | str | float

#: Working precision. Generous enough for 8-decimal crypto quantities
#: multiplied by 8-decimal prices without intermediate loss.
PRECISION = 28

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")


def D(value: Numeric) -> Decimal:
    """Construct a ``Decimal`` from any numeric input.

    ``float`` is routed through ``str`` so that ``D(0.1)`` is ``Decimal("0.1")``
    rather than the exact binary expansion. Passing a float is tolerated at the
    edges of the system (third-party payloads) but should never originate in
    our own code.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"cannot interpret {value!r} as a decimal") from exc


def quantize_price(price: Numeric, tick_size: Numeric) -> Decimal:
    """Snap a price to the instrument's tick size (banker's rounding)."""
    tick = D(tick_size)
    if tick <= ZERO:
        raise ValueError("tick_size must be positive")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (D(price) / tick).quantize(ONE, rounding=ROUND_HALF_EVEN) * tick


def quantize_quantity(quantity: Numeric, step_size: Numeric) -> Decimal:
    """Snap a quantity down to the instrument's step size.

    Always rounds toward zero: never request more size than was intended.
    """
    step = D(step_size)
    if step <= ZERO:
        raise ValueError("step_size must be positive")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (D(quantity) / step).quantize(ONE, rounding=ROUND_DOWN) * step


def notional(quantity: Numeric, price: Numeric) -> Decimal:
    """Gross value of a position or order leg."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return D(quantity) * D(price)


def apply_bps(value: Numeric, basis_points: Numeric) -> Decimal:
    """Return ``value`` adjusted by ``basis_points`` (1 bp = 0.01%)."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return D(value) * (ONE + D(basis_points) / BPS)


def pct_change(start: Numeric, end: Numeric) -> Decimal:
    """Fractional change from ``start`` to ``end``. ``0.05`` means +5%."""
    s = D(start)
    if s == ZERO:
        raise ValueError("cannot compute percentage change from zero")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (D(end) - s) / s
