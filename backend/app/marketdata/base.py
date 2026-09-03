"""The market data contract.

One protocol, several implementations: live Binance klines, a database-backed
cache, and an in-memory series for tests and backtests. Strategies depend on
this interface rather than on an exchange, which is what allows the same
strategy object to run against historical and live data unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain import Bar

#: Supported candle intervals, with their duration in seconds.
INTERVALS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def validate_interval(interval: str) -> str:
    if interval not in INTERVALS:
        raise ValueError(
            f"unsupported interval {interval!r}; expected one of {', '.join(INTERVALS)}"
        )
    return interval


@runtime_checkable
class MarketDataProvider(Protocol):
    """Source of closed OHLCV bars.

    Implementations must return bars in ascending time order and must never
    include a bar that has not closed. A partially formed candle is the most
    common source of accidental look-ahead in a trading system.
    """

    def get_bars(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        end_time: datetime | None = None,
    ) -> list[Bar]:
        """Return up to ``limit`` closed bars ending at or before ``end_time``."""
        ...
