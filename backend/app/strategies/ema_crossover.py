"""EMA crossover — the trend-following baseline.

Fires only on the bar where the fast EMA crosses the slow EMA, not on every
bar where they happen to be ordered a certain way. Separation between the two
averages at the moment of the cross sets the signal's strength.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.money import ZERO
from app.domain import Bar, SignalAction
from app.strategies.base import BaseStrategy, StrategyDecision
from app.strategies.indicators import ema


class EmaCrossoverStrategy(BaseStrategy):
    name = "ema_crossover"

    def __init__(self, fast: int = 9, slow: int = 21) -> None:
        if fast >= slow:
            raise ValueError("fast period must be shorter than slow period")
        self.fast = fast
        self.slow = slow

    @property
    def min_bars(self) -> int:
        # One extra bar so the previous relationship exists and a cross can be
        # distinguished from a state.
        return self.slow + 1

    @property
    def parameters(self) -> dict[str, Any]:
        return {"fast": self.fast, "slow": self.slow}

    def _decide(self, bars: list[Bar], closes: list[Decimal]) -> StrategyDecision:
        fast_ema = ema(closes, self.fast)
        slow_ema = ema(closes, self.slow)

        f_now, f_prev = fast_ema[-1], fast_ema[-2]
        s_now, s_prev = slow_ema[-1], slow_ema[-2]
        if None in (f_now, f_prev, s_now, s_prev):
            return StrategyDecision.hold(reason="warming_up")

        assert f_now is not None and f_prev is not None  # noqa: S101 - narrowed above
        assert s_now is not None and s_prev is not None  # noqa: S101

        features = {
            "ema_fast": str(f_now),
            "ema_slow": str(s_now),
            "separation": str(self._separation(f_now, s_now)),
        }

        if self._crossed_up(f_prev, s_prev, f_now, s_now):
            return StrategyDecision(
                SignalAction.BUY,
                self._strength(f_now, s_now),
                {**features, "event": "golden_cross"},
            )
        if self._crossed_down(f_prev, s_prev, f_now, s_now):
            return StrategyDecision(
                SignalAction.SELL,
                self._strength(f_now, s_now),
                {**features, "event": "death_cross"},
            )

        trend = "up" if f_now > s_now else "down" if f_now < s_now else "flat"
        return StrategyDecision.hold(**features, event="no_cross", trend=trend)

    @staticmethod
    def _separation(fast: Decimal, slow: Decimal) -> Decimal:
        return abs(fast - slow) / slow if slow != ZERO else ZERO

    def _strength(self, fast: Decimal, slow: Decimal) -> Decimal:
        """Wider separation at the cross means a more decisive signal.

        Scaled so a 1% gap reads as full confidence; beyond that it saturates.
        """
        return self._clamp(self._separation(fast, slow) * 100)
