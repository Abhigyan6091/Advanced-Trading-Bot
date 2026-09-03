"""The no-floats rule and exchange rounding."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import D, apply_bps, notional, pct_change, quantize_price, quantize_quantity


class TestDecimalConstruction:
    def test_float_is_routed_through_str(self):
        # The whole point: Decimal(0.1) would be 0.1000000000000000055511151231257827
        assert D(0.1) == Decimal("0.1")
        assert D(0.1) + D(0.2) == D(0.3)

    def test_accepts_str_int_and_decimal(self):
        assert D("1.5") == Decimal("1.5")
        assert D(3) == Decimal("3")
        assert D(Decimal("2.25")) == Decimal("2.25")

    def test_rejects_nonsense(self):
        with pytest.raises(ValueError):
            D("not-a-number")


class TestPriceRounding:
    @pytest.mark.parametrize(
        ("price", "tick", "expected"),
        [
            ("123.4567", "0.10", "123.5"),
            ("123.4400", "0.10", "123.4"),
            ("60000.00", "0.10", "60000.0"),
            ("0.000123456", "0.00000001", "0.00012346"),
        ],
    )
    def test_snaps_to_tick(self, price, tick, expected):
        assert quantize_price(price, tick) == Decimal(expected)

    def test_rejects_non_positive_tick(self):
        with pytest.raises(ValueError):
            quantize_price("100", "0")


class TestQuantityRounding:
    @pytest.mark.parametrize(
        ("qty", "step", "expected"),
        [
            ("0.0019", "0.001", "0.001"),
            ("0.0010", "0.001", "0.001"),
            ("0.0009", "0.001", "0"),
            ("1.999999", "0.001", "1.999"),
        ],
    )
    def test_always_rounds_down(self, qty, step, expected):
        assert quantize_quantity(qty, step) == Decimal(expected)

    def test_never_rounds_up_even_when_nearer(self):
        # 0.00099 is nearer to 0.001 than to 0, but rounding a quantity up can
        # request more size than the account can fund.
        assert quantize_quantity("0.00099", "0.001") == Decimal("0")


class TestArithmetic:
    def test_notional_is_exact(self):
        assert notional("0.001", "60000") == Decimal("60")

    def test_bps_adjustment(self):
        assert apply_bps("100", "2") == Decimal("100.02")
        assert apply_bps("100", "-2") == Decimal("99.98")

    def test_pct_change(self):
        assert pct_change("100", "105") == Decimal("0.05")
        assert pct_change("100", "95") == Decimal("-0.05")

    def test_pct_change_from_zero_is_an_error(self):
        with pytest.raises(ValueError):
            pct_change("0", "5")
