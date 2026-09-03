"""Average-cost position accounting across all four fill cases."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain import Position, PositionSide, Side
from tests.conftest import T0, make_fill

OID = uuid.uuid4()


@pytest.fixture
def flat() -> Position:
    return Position.flat("BTCUSDT")


class TestOpenAndIncrease:
    def test_opening_long_sets_entry_price(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "1", "60000"))
        assert p.side is PositionSide.LONG
        assert p.signed_quantity == Decimal("1")
        assert p.average_entry_price == Decimal("60000")
        assert p.realized_pnl == 0

    def test_opening_short_is_negative_quantity(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.SELL, "2", "60000"))
        assert p.side is PositionSide.SHORT
        assert p.signed_quantity == Decimal("-2")
        assert p.quantity == Decimal("2")

    def test_increasing_reweights_the_average(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "1", "60000"))
        p = p.apply_fill(make_fill(OID, Side.BUY, "1", "62000"))
        assert p.signed_quantity == Decimal("2")
        assert p.average_entry_price == Decimal("61000")
        assert p.realized_pnl == 0


class TestReduceAndClose:
    def test_partial_close_realises_proportionally(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "2", "60000"))
        p = p.apply_fill(make_fill(OID, Side.SELL, "1", "61000"))
        assert p.signed_quantity == Decimal("1")
        assert p.realized_pnl == Decimal("1000")
        # Average entry is untouched by a reduction.
        assert p.average_entry_price == Decimal("60000")

    def test_full_close_goes_flat(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "1", "60000"))
        p = p.apply_fill(make_fill(OID, Side.SELL, "1", "61500"))
        assert p.is_flat
        assert p.side is PositionSide.FLAT
        assert p.realized_pnl == Decimal("1500")
        assert p.average_entry_price == 0

    def test_short_profits_when_price_falls(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.SELL, "1", "60000"))
        p = p.apply_fill(make_fill(OID, Side.BUY, "1", "58000"))
        assert p.is_flat
        assert p.realized_pnl == Decimal("2000")

    def test_long_loses_when_price_falls(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "1", "60000"))
        p = p.apply_fill(make_fill(OID, Side.SELL, "1", "58000"))
        assert p.realized_pnl == Decimal("-2000")


class TestReversal:
    def test_flipping_long_to_short_realises_then_reopens(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "1", "60000"))
        # Sell 3: closes the 1 long (+1000) and opens 2 short at 61000.
        p = p.apply_fill(make_fill(OID, Side.SELL, "3", "61000"))
        assert p.side is PositionSide.SHORT
        assert p.signed_quantity == Decimal("-2")
        assert p.realized_pnl == Decimal("1000")
        assert p.average_entry_price == Decimal("61000")


class TestUnrealised:
    def test_unrealised_is_signed_correctly(self, flat):
        long_p = flat.apply_fill(make_fill(OID, Side.BUY, "1", "60000"))
        assert long_p.unrealized_pnl(Decimal("61000")) == Decimal("1000")
        assert long_p.unrealized_pnl(Decimal("59000")) == Decimal("-1000")

        short_p = flat.apply_fill(make_fill(OID, Side.SELL, "1", "60000"))
        assert short_p.unrealized_pnl(Decimal("59000")) == Decimal("1000")
        assert short_p.unrealized_pnl(Decimal("61000")) == Decimal("-1000")

    def test_flat_position_has_no_unrealised(self, flat):
        assert flat.unrealized_pnl(Decimal("60000")) == 0

    def test_total_pnl_combines_both(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "2", "60000"))
        p = p.apply_fill(make_fill(OID, Side.SELL, "1", "61000"))
        assert p.total_pnl(Decimal("62000")) == Decimal("3000")  # 1000 realised + 2000 open

    def test_notional_uses_absolute_size(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.SELL, "2", "60000"))
        assert p.notional_value(Decimal("60000")) == Decimal("120000")


class TestReplay:
    def test_rebuilding_from_fills_matches_incremental_application(self):
        fills = [
            make_fill(OID, Side.BUY, "1", "60000", at=T0),
            make_fill(OID, Side.BUY, "1", "62000", at=T0 + timedelta(minutes=1)),
            make_fill(OID, Side.SELL, "1", "63000", at=T0 + timedelta(minutes=2)),
        ]
        replayed = Position.from_fills("BTCUSDT", fills)

        incremental = Position.flat("BTCUSDT")
        for f in fills:
            incremental = incremental.apply_fill(f)

        assert replayed.signed_quantity == incremental.signed_quantity
        assert replayed.realized_pnl == incremental.realized_pnl == Decimal("2000")

    def test_commission_accumulates(self, flat):
        p = flat.apply_fill(make_fill(OID, Side.BUY, "1", "60000", commission="24"))
        p = p.apply_fill(make_fill(OID, Side.SELL, "1", "61000", commission="24.4"))
        assert p.total_commission == Decimal("48.4")

    def test_fill_for_a_different_symbol_is_refused(self, flat):
        wrong = make_fill(OID, Side.BUY, "1", "3000").model_copy(update={"symbol": "ETHUSDT"})
        with pytest.raises(ValueError, match="cannot be applied"):
            flat.apply_fill(wrong)
