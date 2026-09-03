"""Mean reversion on a rolling z-score.

Fades displacement from a rolling mean: buy when price is unusually far below
it, sell when unusually far above. Deliberately the opposite stance to the
trend strategies, so a portfolio running several of these is not simply
holding the same position four times.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domain import Bar, SignalAction
from app.strategies.base import BaseStrategy, StrategyDecision
from app.strategies.indicators import sma, zscore


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, period: int = 20, entry_z: Decimal | str = "2.0") -> None:
        entry_z = Decimal(entry_z)
        if entry_z <= 0:
            raise ValueError("entry_z must be positive")
        if period < 2:
            raise ValueError("period must be at least 2")
        self.period = period
        self.entry_z = entry_z

    @property
    def min_bars(self) -> int:
        return self.period + 1

    @property
    def parameters(self) -> dict[str, Any]:
        return {"period": self.period, "entry_z": str(self.entry_z)}

    def _decide(self, bars: list[Bar], closes: list[Decimal]) -> StrategyDecision:
        scores = zscore(closes, self.period)
        means = sma(closes, self.period)

        z, z_prev = scores[-1], scores[-2]
        if z is None:
            # A flat window has no scale; "unusually far" is undefined.
            return StrategyDecision.hold(reason="no_dispersion")

        features = {
            "zscore": str(z),
            "mean": str(means[-1]),
            "price": str(closes[-1]),
        }

        # Require the move to be newly extreme, so the strategy does not
        # re-enter on every bar while price sits outside the band.
        newly_extreme = z_prev is None or abs(z_prev) < self.entry_z

        if z <= -self.entry_z and newly_extreme:
            return StrategyDecision(
                SignalAction.BUY,
                self._strength(z),
                {**features, "event": "below_band"},
            )
        if z >= self.entry_z and newly_extreme:
            return StrategyDecision(
                SignalAction.SELL,
                self._strength(z),
                {**features, "event": "above_band"},
            )

        return StrategyDecision.hold(**features, event="within_band")

    def _strength(self, z: Decimal) -> Decimal:
        """Scaled so the entry threshold is half confidence and 2x is full."""
        return self._clamp(abs(z) / (self.entry_z * 2))
