"""MACD signal-line crossover.

Trades the histogram changing sign — the MACD line crossing its own signal
line — which is a momentum-of-momentum reading rather than a price cross.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.money import ZERO
from app.domain import Bar, SignalAction
from app.strategies.base import BaseStrategy, StrategyDecision
from app.strategies.indicators import macd


class MacdStrategy(BaseStrategy):
    name = "macd"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if fast >= slow:
            raise ValueError("fast period must be shorter than slow period")
        self.fast = fast
        self.slow = slow
        self.signal = signal

    @property
    def min_bars(self) -> int:
        # The MACD line appears at index slow-1; the signal EMA needs `signal`
        # of those values, so the histogram appears at index slow+signal-2.
        # One more bar gives the previous histogram needed to see a sign
        # change, landing on index slow+signal-1 -- that is slow+signal bars.
        return self.slow + self.signal

    @property
    def parameters(self) -> dict[str, Any]:
        return {"fast": self.fast, "slow": self.slow, "signal": self.signal}

    def _decide(self, bars: list[Bar], closes: list[Decimal]) -> StrategyDecision:
        macd_line, signal_line, histogram = macd(closes, self.fast, self.slow, self.signal)

        hist_now, hist_prev = histogram[-1], histogram[-2]
        if hist_now is None or hist_prev is None:
            return StrategyDecision.hold(reason="warming_up")

        features = {
            "macd": str(macd_line[-1]),
            "signal": str(signal_line[-1]),
            "histogram": str(hist_now),
        }

        if hist_prev <= ZERO < hist_now:
            return StrategyDecision(
                SignalAction.BUY,
                self._strength(hist_now, closes[-1]),
                {**features, "event": "bullish_crossover"},
            )
        if hist_prev >= ZERO > hist_now:
            return StrategyDecision(
                SignalAction.SELL,
                self._strength(hist_now, closes[-1]),
                {**features, "event": "bearish_crossover"},
            )

        momentum = "expanding" if abs(hist_now) > abs(hist_prev) else "contracting"
        return StrategyDecision.hold(**features, event="no_crossover", momentum=momentum)

    def _strength(self, histogram: Decimal, price: Decimal) -> Decimal:
        """Histogram size relative to price, so it is comparable across symbols."""
        if price == ZERO:
            return ZERO
        return self._clamp(abs(histogram) / price * 200)
