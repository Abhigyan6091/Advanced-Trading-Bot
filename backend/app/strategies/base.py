"""The strategy contract.

A strategy is a pure function from a window of closed bars to a proposal. It
has no access to a broker, a portfolio or a database, and it cannot size a
position — sizing belongs to the risk engine. That restriction is what lets the
identical object run in a backtest and in live trading.

``BaseStrategy`` owns the parts that must not vary between implementations:

* bars are validated as chronological, same-symbol and duplicate-free;
* the warm-up requirement is enforced before any indicator is read;
* the emitted ``Signal`` always carries the **last** bar's close time.

That last point is the anti-look-ahead guarantee. A subclass decides *what* to
propose; it never decides which instant the proposal belongs to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from app.domain import Bar, Signal, SignalAction


class InsufficientHistory(ValueError):
    """Raised when a strategy is evaluated on fewer bars than it needs."""


class StrategyDecision:
    """A subclass's answer, before it is wrapped into a Signal."""

    __slots__ = ("action", "strength", "features")

    def __init__(
        self,
        action: SignalAction,
        strength: Decimal = Decimal("0"),
        features: dict[str, Any] | None = None,
    ) -> None:
        if action is SignalAction.HOLD:
            strength = Decimal("0")
        self.action = action
        self.strength = strength
        self.features = features or {}

    @classmethod
    def hold(cls, **features: Any) -> StrategyDecision:
        return cls(SignalAction.HOLD, features=features)


class BaseStrategy(ABC):
    """Base class for all strategies."""

    #: Stable identifier, stored on every signal and used for attribution.
    name: str = "base"

    @property
    @abstractmethod
    def min_bars(self) -> int:
        """Bars required before the strategy can produce a decision."""

    @property
    def parameters(self) -> dict[str, Any]:
        """Configuration, recorded alongside signals for reproducibility."""
        return {}

    @abstractmethod
    def _decide(self, bars: list[Bar], closes: list[Decimal]) -> StrategyDecision:
        """Subclass hook. ``closes[i]`` corresponds to ``bars[i]``."""

    # --- public API ----------------------------------------------------

    def evaluate(self, bars: list[Bar]) -> Signal | None:
        """Evaluate the window and return a proposal.

        Returns ``None`` while warming up — that is "cannot yet decide", which
        is different from ``HOLD``, meaning "decided not to act".
        """
        if len(bars) < self.min_bars:
            return None

        self._validate(bars)
        closes = [b.close for b in bars]
        decision = self._decide(bars, closes)

        last = bars[-1]
        return Signal(
            strategy=self.name,
            symbol=last.symbol,
            action=decision.action,
            strength=decision.strength,
            reference_price=last.close,
            # Always the last closed bar. A subclass cannot influence this.
            bar_close_time=last.close_time,
            features={**self.parameters, **decision.features},
        )

    def evaluate_strict(self, bars: list[Bar]) -> Signal:
        """As ``evaluate``, but raises rather than returning ``None``."""
        signal = self.evaluate(bars)
        if signal is None:
            raise InsufficientHistory(
                f"{self.name} needs {self.min_bars} bars, got {len(bars)}"
            )
        return signal

    # --- helpers -------------------------------------------------------

    @staticmethod
    def _validate(bars: list[Bar]) -> None:
        symbol = bars[0].symbol
        previous = bars[0]
        for bar in bars[1:]:
            if bar.symbol != symbol:
                raise ValueError(
                    f"bar window mixes symbols: {symbol} and {bar.symbol}"
                )
            if bar.open_time <= previous.open_time:
                raise ValueError(
                    "bars must be strictly chronological; "
                    f"{bar.open_time} does not follow {previous.open_time}"
                )
            previous = bar

    @staticmethod
    def _crossed_up(prev_a: Decimal, prev_b: Decimal, a: Decimal, b: Decimal) -> bool:
        """True when series A crosses above series B on this bar.

        A cross is an event, not a state: requiring the previous bar to be on
        the other side stops a strategy re-firing on every bar of a trend.
        """
        return prev_a <= prev_b and a > b

    @staticmethod
    def _crossed_down(prev_a: Decimal, prev_b: Decimal, a: Decimal, b: Decimal) -> bool:
        return prev_a >= prev_b and a < b

    @staticmethod
    def _clamp(
        value: Decimal, low: Decimal = Decimal("0"), high: Decimal = Decimal("1")
    ) -> Decimal:
        return max(low, min(high, value))

    def __repr__(self) -> str:
        params = ", ".join(f"{k}={v}" for k, v in self.parameters.items())
        return f"{type(self).__name__}({params})"
