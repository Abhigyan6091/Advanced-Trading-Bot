"""Binance USDT-M Futures market data.

Constructed with ``testnet=True`` rather than by overwriting a URL attribute
after the fact. The previous implementation assigned ``client.FUTURES_URL``
post-construction, which bypasses the library's supported switch and leaves the
routing dependent on internal URL templating — a client that silently falls
back to production is the worst failure mode this project has.

Market data endpoints are public, so no credentials are required for reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import get_logger
from app.core.money import D
from app.domain import Bar
from app.marketdata.base import validate_interval

log = get_logger(__name__)


class MarketDataUnavailable(RuntimeError):
    """The venue could not be reached or returned an unusable response."""


class BinanceMarketData:
    """Reads closed klines from the Binance Futures **testnet**."""

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        from binance.client import Client

        # testnet=True is the supported switch. Never rewrite URL attributes.
        self._client = Client(api_key or "", api_secret or "", testnet=True)

    @retry(
        retry=retry_if_exception_type(MarketDataUnavailable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    def get_bars(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        end_time: datetime | None = None,
    ) -> list[Bar]:
        validate_interval(interval)
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1500),
        }
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)

        try:
            raw = self._client.futures_klines(**params)
        except Exception as exc:  # noqa: BLE001 - normalised and retried
            log.warning("marketdata.fetch_failed", symbol=symbol, error=str(exc))
            raise MarketDataUnavailable(f"could not fetch klines for {symbol}") from exc

        bars = [self._to_bar(symbol.upper(), row) for row in raw]
        return self._drop_unclosed(bars)

    @staticmethod
    def _to_bar(symbol: str, row: list[Any]) -> Bar:
        """Normalise one kline row.

        Binance returns numbers as strings; they are fed straight into Decimal
        so no float ever exists in the path.
        """
        open_ms, o, h, low, c, volume, close_ms = row[:7]
        return Bar(
            symbol=symbol,
            open_time=_from_ms(open_ms),
            # Binance close times end one millisecond before the next open.
            close_time=_from_ms(close_ms + 1),
            open=D(o),
            high=D(h),
            low=D(low),
            close=D(c),
            volume=D(volume),
        )

    @staticmethod
    def _drop_unclosed(bars: list[Bar]) -> list[Bar]:
        """Discard a trailing bar that has not finished forming.

        Binance includes the in-progress candle. Handing it to a strategy would
        mean acting on a close price that is still moving.
        """
        now = datetime.now(timezone.utc)
        return [b for b in bars if b.close_time <= now]


def _from_ms(milliseconds: int) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
