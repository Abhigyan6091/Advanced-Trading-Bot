"""Database-backed bar storage and caching.

Wraps another provider: bars already stored are served from PostgreSQL, and
only the gap is fetched from the venue. This keeps backtests reproducible —
they run against a fixed local history rather than whatever the exchange
returns today — and stops the dashboard re-querying Binance on every render.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import BarRow
from app.domain import Bar
from app.marketdata.base import MarketDataProvider, validate_interval

log = get_logger(__name__)


class BarRepository:
    """Reads and writes bars in PostgreSQL."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_bars(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        end_time: datetime | None = None,
    ) -> list[Bar]:
        validate_interval(interval)
        stmt = (
            select(BarRow)
            .where(BarRow.symbol == symbol.upper(), BarRow.interval == interval)
            .order_by(BarRow.close_time.desc())
            .limit(limit)
        )
        if end_time is not None:
            stmt = stmt.where(BarRow.close_time <= end_time)

        rows = list(self.session.execute(stmt).scalars())
        return [self._to_domain(r) for r in reversed(rows)]

    def save(self, bars: list[Bar], interval: str) -> int:
        """Upsert bars, ignoring ones already stored.

        Re-fetching an overlapping window is normal, so a repeated bar is not
        an error. The unique constraint on (symbol, interval, open_time) makes
        the operation idempotent at the database.
        """
        if not bars:
            return 0
        validate_interval(interval)

        payload = [
            {
                "symbol": b.symbol,
                "interval": interval,
                "open_time": b.open_time,
                "close_time": b.close_time,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ]
        stmt = insert(BarRow).values(payload).on_conflict_do_nothing(
            constraint="uq_bar_symbol_interval_open"
        )
        result = self.session.execute(stmt)
        return result.rowcount or 0

    @staticmethod
    def _to_domain(row: BarRow) -> Bar:
        return Bar(
            symbol=row.symbol,
            open_time=row.open_time,
            close_time=row.close_time,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )


class CachingMarketData:
    """Serves bars from the database, backfilling from ``upstream`` on a miss."""

    def __init__(
        self,
        repository: BarRepository,
        upstream: MarketDataProvider,
        interval: str = "1h",
    ) -> None:
        self.repository = repository
        self.upstream = upstream
        self.interval = validate_interval(interval)

    def get_bars(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        end_time: datetime | None = None,
    ) -> list[Bar]:
        cached = self.repository.get_bars(symbol, interval, limit, end_time)
        if len(cached) >= limit:
            return cached

        log.info(
            "marketdata.backfill",
            symbol=symbol,
            interval=interval,
            cached=len(cached),
            requested=limit,
        )
        fetched = self.upstream.get_bars(symbol, interval, limit, end_time)
        if fetched:
            self.repository.save(fetched, interval)
        return fetched or cached
