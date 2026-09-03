"""Market data providers.

The load-bearing property here is that a provider never reveals a bar that has
not closed, and never reveals anything past a requested ``end_time``. Both are
how look-ahead leaks into a backtest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.marketdata import (
    INTERVALS,
    InMemoryMarketData,
    MarketDataProvider,
    validate_interval,
)
from app.marketdata.binance import BinanceMarketData
from tests.conftest import T0, make_bars


class TestIntervals:
    def test_known_intervals_pass_through(self):
        assert validate_interval("1h") == "1h"

    def test_unknown_interval_lists_the_supported_set(self):
        with pytest.raises(ValueError, match="unsupported interval '3s'"):
            validate_interval("3s")

    def test_durations_are_consistent(self):
        assert INTERVALS["1m"] == 60
        assert INTERVALS["1h"] == 3600
        assert INTERVALS["1d"] == 24 * INTERVALS["1h"]


class TestInMemoryProvider:
    @pytest.fixture
    def provider(self) -> InMemoryMarketData:
        return InMemoryMarketData(make_bars(list(range(100, 120))))

    def test_satisfies_the_protocol(self, provider):
        assert isinstance(provider, MarketDataProvider)

    def test_returns_bars_in_ascending_order(self, provider):
        bars = provider.get_bars("BTCUSDT", limit=10)
        times = [b.open_time for b in bars]
        assert times == sorted(times)

    def test_limit_takes_the_most_recent(self, provider):
        bars = provider.get_bars("BTCUSDT", limit=5)
        assert len(bars) == 5
        assert bars[-1].close == Decimal("119")

    def test_unsorted_input_is_normalised(self):
        bars = make_bars(list(range(100, 110)))
        provider = InMemoryMarketData(list(reversed(bars)))
        times = [b.open_time for b in provider.get_bars("BTCUSDT")]
        assert times == sorted(times)

    def test_filters_by_symbol(self, provider):
        assert provider.get_bars("ETHUSDT") == []

    def test_end_time_excludes_later_bars(self, provider):
        cutoff = T0 + timedelta(hours=5)
        bars = provider.get_bars("BTCUSDT", end_time=cutoff)
        assert bars, "expected some bars before the cutoff"
        assert all(b.close_time <= cutoff for b in bars)

    def test_end_time_excludes_a_bar_still_forming(self, provider):
        """A bar closing one second after the cutoff is not yet knowable."""
        all_bars = provider.get_bars("BTCUSDT")
        boundary = all_bars[3].close_time
        visible = provider.get_bars("BTCUSDT", end_time=boundary - timedelta(seconds=1))
        assert all_bars[3] not in visible
        assert len(visible) == 3


class TestBinanceNormalisation:
    """Kline parsing, exercised without touching the network."""

    #  [open_ms, open, high, low, close, volume, close_ms, ...]
    ROW = [
        1_767_225_600_000,
        "60000.10",
        "60500.00",
        "59800.50",
        "60200.30",
        "12.345",
        1_767_229_199_999,
        "740000.0",
        1234,
    ]

    def test_strings_become_exact_decimals(self):
        bar = BinanceMarketData._to_bar("BTCUSDT", self.ROW)
        assert bar.open == Decimal("60000.10")
        assert bar.close == Decimal("60200.30")
        assert bar.volume == Decimal("12.345")
        assert all(isinstance(v, Decimal) for v in (bar.open, bar.high, bar.low, bar.close))

    def test_close_time_is_the_next_open(self):
        """Binance close times end one millisecond early; we normalise that.

        Leaving the off-by-one in place makes bars non-contiguous, and any
        `close_time <= cutoff` comparison then behaves inconsistently at
        interval boundaries.
        """
        bar = BinanceMarketData._to_bar("BTCUSDT", self.ROW)
        assert bar.close_time == datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
        assert bar.open_time == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert bar.close_time - bar.open_time == timedelta(hours=1)

    def test_timestamps_are_timezone_aware_utc(self):
        bar = BinanceMarketData._to_bar("BTCUSDT", self.ROW)
        assert bar.open_time.tzinfo is not None
        assert bar.open_time.utcoffset() == timedelta(0)

    def test_ohlc_invariants_are_enforced_on_parse(self):
        bad = list(self.ROW)
        bad[2] = "100.0"  # high below low
        with pytest.raises(ValueError):
            BinanceMarketData._to_bar("BTCUSDT", bad)

    def test_unclosed_trailing_bar_is_dropped(self):
        """Binance returns the in-progress candle; a strategy must not see it."""
        now = datetime.now(timezone.utc)
        closed = make_bars([100, 101], start=now - timedelta(hours=3))
        forming = make_bars([102], start=now + timedelta(hours=1))
        kept = BinanceMarketData._drop_unclosed(closed + forming)
        assert len(kept) == 2
        assert all(b.close_time <= now for b in kept)
