"""Instrument rules and bar integrity."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import Bar, Signal, SignalAction
from tests.conftest import T0


class TestInstrumentRounding:
    def test_price_snaps_to_tick(self, btc):
        assert btc.round_price(Decimal("60000.07")) == Decimal("60000.1")

    def test_quantity_snaps_down_to_step(self, btc):
        assert btc.round_quantity(Decimal("0.0019")) == Decimal("0.001")

    def test_tradeable_requires_both_floors(self, btc):
        assert btc.is_tradeable(Decimal("0.01"), Decimal("60000"))
        # Clears min_quantity but the notional is only $60 against a $100 floor.
        assert not btc.is_tradeable(Decimal("0.001"), Decimal("60000"))
        # Clears notional but is below min_quantity.
        assert not btc.is_tradeable(Decimal("0.0005"), Decimal("600000"))


class TestBarIntegrity:
    def test_valid_bar(self, bar):
        assert bar.range == Decimal("700")
        assert bar.typical_price == (bar.high + bar.low + bar.close) / 3

    def test_high_below_low_is_rejected(self):
        with pytest.raises(ValidationError, match="high cannot be below low"):
            Bar(
                symbol="BTCUSDT",
                open_time=T0,
                close_time=T0 + timedelta(minutes=1),
                open=Decimal("100"),
                high=Decimal("90"),
                low=Decimal("110"),
                close=Decimal("100"),
                volume=Decimal("1"),
            )

    def test_close_outside_range_is_rejected(self):
        with pytest.raises(ValidationError, match="close must lie within"):
            Bar(
                symbol="BTCUSDT",
                open_time=T0,
                close_time=T0 + timedelta(minutes=1),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("120"),
                volume=Decimal("1"),
            )

    def test_close_time_must_follow_open_time(self):
        with pytest.raises(ValidationError, match="close_time must be after"):
            Bar(
                symbol="BTCUSDT",
                open_time=T0,
                close_time=T0,
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("100"),
                volume=Decimal("1"),
            )


class TestSignal:
    def test_carries_the_bar_it_was_computed_from(self, buy_signal, bar):
        # This field is what makes the anti-look-ahead check possible in Phase 5.
        assert buy_signal.bar_close_time == bar.close_time
        assert buy_signal.is_actionable

    def test_hold_is_not_actionable(self, bar):
        s = Signal(
            strategy="rsi",
            symbol="BTCUSDT",
            action=SignalAction.HOLD,
            strength=Decimal("0"),
            reference_price=bar.close,
            bar_close_time=bar.close_time,
        )
        assert not s.is_actionable
        with pytest.raises(ValueError, match="does not map to an order side"):
            s.action.to_side()

    def test_hold_with_strength_is_rejected(self, bar):
        with pytest.raises(ValidationError, match="HOLD signal must have strength 0"):
            Signal(
                strategy="rsi",
                symbol="BTCUSDT",
                action=SignalAction.HOLD,
                strength=Decimal("0.5"),
                reference_price=bar.close,
                bar_close_time=bar.close_time,
            )

    def test_strength_is_bounded(self, bar):
        with pytest.raises(ValidationError):
            Signal(
                strategy="rsi",
                symbol="BTCUSDT",
                action=SignalAction.BUY,
                strength=Decimal("1.5"),
                reference_price=bar.close,
                bar_close_time=bar.close_time,
            )
