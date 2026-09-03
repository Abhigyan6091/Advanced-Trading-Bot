"""Strategy engine.

Strategies propose; they never execute. Nothing in this package imports a
broker, an order or a portfolio, which an architectural test enforces.
"""

from app.strategies.base import BaseStrategy, InsufficientHistory, StrategyDecision
from app.strategies.ema_crossover import EmaCrossoverStrategy
from app.strategies.macd_strategy import MacdStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.registry import STRATEGIES, available, build
from app.strategies.rsi_strategy import RsiStrategy

__all__ = [
    "STRATEGIES",
    "BaseStrategy",
    "EmaCrossoverStrategy",
    "InsufficientHistory",
    "MacdStrategy",
    "MeanReversionStrategy",
    "RsiStrategy",
    "StrategyDecision",
    "available",
    "build",
]
