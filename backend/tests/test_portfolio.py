"""Portfolio accounting: cash, positions, P&L and exposure."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain import Fill, Side
from app.portfolio import Portfolio
from tests.conftest import T0

OID = uuid.uuid4()


def fill(side: Side, qty: str, price: str, *, commission: str = "0", at=T0, symbol="BTCUSDT"):
    return Fill(
        order_id=OID,
        symbol=symbol,
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        commission=Decimal(commission),
        executed_at=at,
    )


@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio("100000")


class TestCashAccounting:
    def test_buying_reduces_cash_by_notional_plus_commission(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000", commission="24"))
        assert portfolio.cash == Decimal("100000") - Decimal("60000") - Decimal("24")

    def test_selling_increases_cash(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.apply_fill(fill(Side.SELL, "1", "61000"))
        assert portfolio.cash == Decimal("101000")

    def test_commission_accumulates_separately(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000", commission="24"))
        portfolio.apply_fill(fill(Side.SELL, "1", "61000", commission="24.4"))
        assert portfolio.total_commission == Decimal("48.4")


class TestEquity:
    def test_equity_starts_at_the_opening_balance(self, portfolio):
        assert portfolio.equity == Decimal("100000")

    def test_equity_is_unchanged_by_a_flat_trade(self, portfolio):
        """Buying at the mark converts cash into position value, nothing more."""
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "60000")
        assert portfolio.equity == Decimal("100000")

    def test_equity_tracks_the_mark(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "65000")
        assert portfolio.equity == Decimal("105000")

    def test_short_equity_rises_when_price_falls(self, portfolio):
        portfolio.apply_fill(fill(Side.SELL, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "55000")
        assert portfolio.equity == Decimal("105000")


class TestPnl:
    def test_realised_pnl_is_recognised_on_close(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        assert portfolio.realized_pnl == 0
        portfolio.apply_fill(fill(Side.SELL, "1", "62000"))
        assert portfolio.realized_pnl == Decimal("2000")

    def test_unrealised_pnl_is_reported_while_open(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "63000")
        snapshot = portfolio.snapshot()
        assert snapshot.unrealized_pnl == Decimal("3000")
        assert snapshot.realized_pnl == 0

    def test_total_pnl_combines_both(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "2", "60000"))
        portfolio.apply_fill(fill(Side.SELL, "1", "62000"))
        portfolio.set_mark("BTCUSDT", "63000")
        snapshot = portfolio.snapshot()
        assert snapshot.realized_pnl == Decimal("2000")
        assert snapshot.unrealized_pnl == Decimal("3000")
        assert snapshot.total_pnl == Decimal("5000")

    def test_daily_pnl_is_net_of_commission(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000", commission="24"))
        portfolio.apply_fill(fill(Side.SELL, "1", "62000", commission="24.8"))
        assert portfolio.daily_pnl(T0.date()) == Decimal("2000") - Decimal("48.8")

    def test_daily_pnl_is_partitioned_by_day(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000", at=T0))
        portfolio.apply_fill(fill(Side.SELL, "1", "62000", at=T0 + timedelta(days=1)))
        assert portfolio.daily_pnl(T0.date()) == 0
        assert portfolio.daily_pnl((T0 + timedelta(days=1)).date()) == Decimal("2000")


class TestExposure:
    def test_gross_exposure_counts_both_directions(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000", symbol="BTCUSDT"))
        portfolio.apply_fill(fill(Side.SELL, "10", "3000", symbol="ETHUSDT"))
        portfolio.set_mark("BTCUSDT", "60000")
        portfolio.set_mark("ETHUSDT", "3000")
        assert portfolio.snapshot().gross_exposure == Decimal("90000")

    def test_leverage_is_exposure_over_equity(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "60000")
        snapshot = portfolio.snapshot()
        assert snapshot.leverage == Decimal("0.6")

    def test_flat_positions_are_excluded(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.apply_fill(fill(Side.SELL, "1", "61000"))
        assert portfolio.positions == ()
        assert portfolio.snapshot().open_positions == ()


class TestDrawdown:
    def test_no_drawdown_at_a_new_high(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "70000")
        assert portfolio.snapshot().drawdown == 0

    def test_drawdown_measured_from_the_peak(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "80000")   # equity 120,000, a new peak
        portfolio.set_mark("BTCUSDT", "50000")   # equity 90,000
        snapshot = portfolio.snapshot()
        assert snapshot.peak_equity == Decimal("120000")
        assert snapshot.drawdown == Decimal("0.25")


class TestReplay:
    def test_rebuilding_from_fills_reproduces_the_state(self):
        """Positions and P&L are a fold over fills, never independent counters."""
        fills = [
            fill(Side.BUY, "1", "60000", commission="24", at=T0),
            fill(Side.BUY, "1", "62000", commission="24.8", at=T0 + timedelta(hours=1)),
            fill(Side.SELL, "1", "65000", commission="26", at=T0 + timedelta(hours=2)),
        ]
        incremental = Portfolio("100000")
        for f in fills:
            incremental.apply_fill(f)

        replayed = Portfolio.from_fills(fills, "100000")

        assert replayed.cash == incremental.cash
        assert replayed.realized_pnl == incremental.realized_pnl
        assert replayed.total_commission == incremental.total_commission
        assert replayed.position("BTCUSDT").signed_quantity == Decimal("1")

    def test_out_of_order_fills_are_sequenced(self):
        fills = [
            fill(Side.SELL, "1", "65000", at=T0 + timedelta(hours=2)),
            fill(Side.BUY, "1", "60000", at=T0),
        ]
        portfolio = Portfolio.from_fills(fills, "100000")
        assert portfolio.realized_pnl == Decimal("5000")


class TestRiskAdapter:
    def test_snapshot_converts_to_an_account_for_the_risk_engine(self, portfolio):
        portfolio.apply_fill(fill(Side.BUY, "1", "60000"))
        portfolio.set_mark("BTCUSDT", "60000")

        account = portfolio.snapshot().to_account(volatility=Decimal("0.5"))
        assert account.equity == Decimal("100000")
        assert account.gross_exposure == Decimal("60000")
        assert account.volatility == Decimal("0.5")
        assert account.position("BTCUSDT").signed_quantity == Decimal("1")

    def test_a_wiped_out_account_still_produces_a_valid_snapshot(self):
        """Equity must stay positive for the risk engine's ratios to be defined."""
        portfolio = Portfolio("1000")
        portfolio.apply_fill(fill(Side.BUY, "1", "1000"))
        portfolio.set_mark("BTCUSDT", "0.01")
        account = portfolio.snapshot().to_account()
        assert account.equity > 0
