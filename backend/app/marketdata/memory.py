"""In-memory market data.

Used by tests and by the backtester's replay loop. Because it honours
``end_time`` the same way the live provider does, a strategy cannot see beyond
the simulated present.
"""

from __future__ import annotations

from datetime import datetime

from app.domain import Bar
from app.marketdata.base import validate_interval


class InMemoryMarketData:
    """Serves a fixed set of bars, filtered as a real provider would."""

    def __init__(self, bars: list[Bar], interval: str = "1h") -> None:
        self.interval = validate_interval(interval)
        self._bars = sorted(bars, key=lambda b: b.open_time)

    def get_bars(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        end_time: datetime | None = None,
    ) -> list[Bar]:
        bars = [b for b in self._bars if b.symbol == symbol]
        if end_time is not None:
            # Strictly closed at or before end_time: a bar still forming at
            # end_time is not yet knowable.
            bars = [b for b in bars if b.close_time <= end_time]
        return bars[-limit:] if limit else bars

    def __len__(self) -> int:
        return len(self._bars)
