"""Adverse-outcome labeling for training.

Used only to build a training set from historical bars -- never in the live
or backtest pipeline, where the actual outcome of a trade is not yet known.
Looking forward here is not a leak: this is exactly what a label is.

**Triple barrier.** From an entry at ``bars[i]``'s close, look forward up to
``horizon`` bars for two barriers: a stop (adverse) and a target (favourable),
both scaled by ATR at entry so the barrier width adapts to the instrument's
own volatility rather than a fixed price distance. Whichever barrier is
touched first decides the label:

* stop touched first, or the horizon expires underwater  -> adverse (1)
* target touched first, or the horizon expires ahead      -> not adverse (0)

This is a standard event-labeling method (de Prado's triple-barrier) chosen
over a fixed-horizon return threshold because it matches how a real position
would actually be managed -- exited on a stop or a target, not held blindly
to a fixed bar count.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO
from app.domain import Bar, Side
from app.strategies.indicators import atr


@dataclass(frozen=True)
class LabelConfig:
    horizon: int = 24
    stop_atr_multiple: Decimal = Decimal("1.5")
    target_atr_multiple: Decimal = Decimal("2.0")
    atr_period: int = 14


@dataclass(frozen=True)
class LabeledExample:
    index: int
    side: Side
    adverse: bool
    bars_to_resolution: int


def label_series(
    bars: list[Bar], side: Side, config: LabelConfig | None = None
) -> list[LabeledExample | None]:
    """Label every index in ``bars`` as adverse or not for a trade in ``side``.

    Returns one entry per bar, ``None`` where ATR is not yet defined or the
    horizon runs past the end of the data (an unresolved trade contributes no
    training signal, so it is dropped rather than mislabeled).
    """
    config = config or LabelConfig()
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    atr_series = atr(highs, lows, closes, config.atr_period)

    out: list[LabeledExample | None] = [None] * len(bars)
    for i, entry_atr in enumerate(atr_series):
        if entry_atr is None or entry_atr <= ZERO:
            continue
        if i + config.horizon >= len(bars):
            continue

        entry_price = closes[i]
        stop_distance = entry_atr * config.stop_atr_multiple
        target_distance = entry_atr * config.target_atr_multiple

        if side is Side.BUY:
            stop_price = entry_price - stop_distance
            target_price = entry_price + target_distance
        else:
            stop_price = entry_price + stop_distance
            target_price = entry_price - target_distance

        out[i] = _resolve(bars, i, side, stop_price, target_price, config.horizon)
    return out


def _resolve(
    bars: list[Bar],
    entry_index: int,
    side: Side,
    stop_price: Decimal,
    target_price: Decimal,
    horizon: int,
) -> LabeledExample:
    for offset in range(1, horizon + 1):
        bar = bars[entry_index + offset]
        stop_hit = bar.low <= stop_price if side is Side.BUY else bar.high >= stop_price
        target_hit = (
            bar.high >= target_price if side is Side.BUY else bar.low <= target_price
        )

        # A bar can touch both within its range; the stop is assumed to bind
        # first. This is conservative -- it never under-counts adverse
        # outcomes -- and is the standard assumption absent intrabar data.
        if stop_hit:
            return LabeledExample(entry_index, side, adverse=True, bars_to_resolution=offset)
        if target_hit:
            return LabeledExample(entry_index, side, adverse=False, bars_to_resolution=offset)

    # Horizon exhausted with neither barrier touched: resolve by which side of
    # entry the price ended on.
    final_close = bars[entry_index + horizon].close
    if side is Side.BUY:
        adverse = final_close < bars[entry_index].close
    else:
        adverse = final_close > bars[entry_index].close
    return LabeledExample(entry_index, side, adverse=adverse, bars_to_resolution=horizon)
