"""Market data.

A single ``MarketDataProvider`` protocol with three implementations: live
Binance testnet klines, a PostgreSQL-backed cache, and an in-memory series for
tests and backtests.
"""

from app.marketdata.base import INTERVALS, MarketDataProvider, validate_interval
from app.marketdata.binance import BinanceMarketData, MarketDataUnavailable
from app.marketdata.memory import InMemoryMarketData
from app.marketdata.repository import BarRepository, CachingMarketData

__all__ = [
    "INTERVALS",
    "BarRepository",
    "BinanceMarketData",
    "CachingMarketData",
    "InMemoryMarketData",
    "MarketDataProvider",
    "MarketDataUnavailable",
    "validate_interval",
]
