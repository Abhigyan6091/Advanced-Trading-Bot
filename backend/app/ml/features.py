"""Feature engineering for the adverse-outcome model.

Every feature is computed from a bar window ``bars[0..i]`` and account state
known at that same instant -- nothing here may look forward. This is the same
discipline strategies are held to (see ``app.strategies.base``): a feature
that leaked future information would make the model's backtested accuracy
unachievable in live trading.

Features split into two groups, deliberately:

* **Market features** -- volatility, momentum, volume, returns, spread -- come
  only from the bar window and are computed once per decision, before the
  final trade size is known.
* **``position_pct``** depends on the specific quantity being risked. It is
  computed the same way ``PositionSizeCheck`` computes its own ratio: fresh,
  at the moment the risk engine evaluates a concrete quantity. This avoids a
  chicken-and-egg problem -- the caller supplying market context does not need
  to already know the size the risk engine has not yet approved.

"Spread" has no real order-book source in OHLCV data, so it is proxied by the
most recent bar's high-low range as a fraction of price -- a standard stand-in
when quote data is unavailable, and one that is at least drawn from the same
bar the other features use, not fabricated.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.money import ZERO
from app.domain import Bar, Position, Side
from app.strategies.indicators import realized_volatility, rsi, sma

#: Fixed order. The model is trained and served against this exact ordering;
#: changing it invalidates every model file already saved to disk.
FEATURE_NAMES: tuple[str, ...] = (
    "volatility",
    "momentum",
    "volume_zscore",
    "return_1",
    "return_5",
    "spread",
    "position_pct",
    "drawdown",
)

#: Bars needed before every market feature is defined.
MIN_BARS = 27


def compute_market_features(bars: list[Bar]) -> dict[str, Decimal] | None:
    """The bars-only features: everything except ``position_pct``.

    Returns ``None`` while the window is too short for every feature to be
    defined -- callers treat that exactly like a model that has not been
    trained: a neutral pass, not a crash.
    """
    if len(bars) < MIN_BARS:
        return None

    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]

    volatility = realized_volatility(closes, 24)[-1]
    if volatility is None:
        return None

    momentum = rsi(closes, 14)[-1]
    if momentum is None:
        return None

    vol_mean = sma(volumes, 20)[-1]
    vol_std = _stddev(volumes[-20:])
    volume_zscore = (
        (volumes[-1] - vol_mean) / vol_std if vol_std and vol_std != ZERO else ZERO
    )

    last = bars[-1]
    spread = (last.high - last.low) / last.close if last.close != ZERO else ZERO

    return {
        "volatility": volatility,
        "momentum": momentum / Decimal(100),  # normalise RSI's 0-100 to 0-1
        "volume_zscore": volume_zscore,
        "return_1": _simple_return(closes, 1),
        "return_5": _simple_return(closes, 5),
        "spread": spread,
    }


def position_pct(
    existing: Position, side: Side, quantity: Decimal, price: Decimal, equity: Decimal
) -> Decimal:
    """Resulting position size as a fraction of equity.

    The same computation ``PositionSizeCheck`` performs: it is the resulting
    position that matters, not just the incremental order, since adding to an
    existing holding is what actually changes the account's exposure.
    """
    delta = side.sign * quantity
    resulting = abs(existing.signed_quantity + delta)
    return (resulting * price) / equity if equity > ZERO else ZERO


def compute_features(
    bars: list[Bar],
    *,
    existing_position: Position,
    side: Side,
    quantity: Decimal,
    price: Decimal,
    drawdown: Decimal,
    equity: Decimal,
) -> dict[str, Decimal] | None:
    """The full feature vector, for offline dataset construction.

    Live and backtest callers do not use this directly -- see the module
    docstring for why ``position_pct`` is computed separately there. This
    convenience wrapper exists for training, where the trade size is a
    deliberately chosen synthetic value rather than something awaited from the
    risk engine.
    """
    market = compute_market_features(bars)
    if market is None:
        return None
    return {
        **market,
        "position_pct": position_pct(existing_position, side, quantity, price, equity),
        "drawdown": drawdown,
    }


def _simple_return(closes: list[Decimal], lookback: int) -> Decimal:
    if len(closes) <= lookback or closes[-1 - lookback] == ZERO:
        return ZERO
    return (closes[-1] - closes[-1 - lookback]) / closes[-1 - lookback]


def _stddev(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance.sqrt()


def features_to_vector(features: dict[str, Decimal]) -> list[float]:
    """Order a feature dict into the fixed vector the model expects."""
    return [float(features[name]) for name in FEATURE_NAMES]
