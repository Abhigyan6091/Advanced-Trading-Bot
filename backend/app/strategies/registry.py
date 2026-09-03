"""Strategy registry.

Strategies are looked up by name so the API, backtester and CLI can all
instantiate one from configuration without importing each class directly.
"""

from __future__ import annotations

from typing import Any

from app.strategies.base import BaseStrategy
from app.strategies.ema_crossover import EmaCrossoverStrategy
from app.strategies.macd_strategy import MacdStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.rsi_strategy import RsiStrategy

STRATEGIES: dict[str, type[BaseStrategy]] = {
    EmaCrossoverStrategy.name: EmaCrossoverStrategy,
    RsiStrategy.name: RsiStrategy,
    MacdStrategy.name: MacdStrategy,
    MeanReversionStrategy.name: MeanReversionStrategy,
}


def available() -> list[str]:
    return sorted(STRATEGIES)


def build(name: str, **params: Any) -> BaseStrategy:
    """Instantiate a strategy by name."""
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r}; available: {', '.join(available())}"
        ) from None
    return cls(**params)
