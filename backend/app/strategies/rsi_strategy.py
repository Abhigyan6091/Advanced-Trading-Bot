"""RSI mean-reversion on momentum extremes.

Buys when RSI recovers back above the oversold threshold and sells when it
falls back below overbought. Waiting for the *exit* from the extreme rather
than entering at the extreme itself avoids the classic failure of buying all
the way down a trend that keeps making new lows.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domain import Bar, SignalAction
from app.strategies.base import BaseStrategy, StrategyDecision
from app.strategies.indicators import rsi


class RsiStrategy(BaseStrategy):
    name = "rsi"

    def __init__(
        self,
        period: int = 14,
        oversold: Decimal | int = 30,
        overbought: Decimal | int = 70,
    ) -> None:
        oversold, overbought = Decimal(oversold), Decimal(overbought)
        if not 0 < oversold < overbought < 100:
            raise ValueError("thresholds must satisfy 0 < oversold < overbought < 100")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    @property
    def min_bars(self) -> int:
        # period + 1 prices for the first RSI value, plus one more for the
        # previous reading that makes a threshold crossing detectable.
        return self.period + 2

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "oversold": str(self.oversold),
            "overbought": str(self.overbought),
        }

    def _decide(self, bars: list[Bar], closes: list[Decimal]) -> StrategyDecision:
        values = rsi(closes, self.period)
        now, prev = values[-1], values[-2]
        if now is None or prev is None:
            return StrategyDecision.hold(reason="warming_up")

        features = {"rsi": str(now), "rsi_prev": str(prev)}

        if prev <= self.oversold < now:
            return StrategyDecision(
                SignalAction.BUY,
                self._strength(self.oversold - prev, self.oversold),
                {**features, "event": "exited_oversold"},
            )
        if prev >= self.overbought > now:
            return StrategyDecision(
                SignalAction.SELL,
                self._strength(prev - self.overbought, 100 - self.overbought),
                {**features, "event": "exited_overbought"},
            )

        zone = (
            "oversold"
            if now <= self.oversold
            else "overbought"
            if now >= self.overbought
            else "neutral"
        )
        return StrategyDecision.hold(**features, event="no_crossing", zone=zone)

    def _strength(self, depth: Decimal, span: Decimal | int) -> Decimal:
        """How far past the threshold the extreme reached before reverting."""
        span = Decimal(span)
        if span <= 0:
            return Decimal("1")
        return self._clamp(depth / span)
