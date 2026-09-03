"""Tradeable instruments and the market data bars they produce."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.money import quantize_price, quantize_quantity
from app.domain.types import Price, Quantity


class Instrument(BaseModel):
    """Exchange trading rules for one symbol.

    These constraints come from the venue, not from us. Every order is snapped
    to them before submission, which removes an entire class of exchange
    rejections.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=3, max_length=20)
    base_asset: str
    quote_asset: str

    tick_size: Price
    step_size: Quantity
    min_quantity: Quantity
    min_notional: Price
    max_leverage: int = Field(default=1, ge=1, le=125)

    def round_price(self, price: Decimal) -> Decimal:
        return quantize_price(price, self.tick_size)

    def round_quantity(self, quantity: Decimal) -> Decimal:
        return quantize_quantity(quantity, self.step_size)

    def is_tradeable(self, quantity: Decimal, price: Decimal) -> bool:
        """True when the leg clears both the size and notional floors."""
        return quantity >= self.min_quantity and quantity * price >= self.min_notional


class Bar(BaseModel):
    """One OHLCV candle.

    ``close_time`` is the instant the bar became final. A strategy may only use
    bars whose ``close_time`` is at or before the decision point — this field is
    what makes that rule checkable rather than assumed.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    open_time: datetime
    close_time: datetime

    open: Price
    high: Price
    low: Price
    close: Price
    volume: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _check_ohlc(self) -> Bar:
        if self.high < self.low:
            raise ValueError("high cannot be below low")
        if not (self.low <= self.open <= self.high):
            raise ValueError("open must lie within [low, high]")
        if not (self.low <= self.close <= self.high):
            raise ValueError("close must lie within [low, high]")
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        return self

    @property
    def typical_price(self) -> Decimal:
        return (self.high + self.low + self.close) / 3

    @property
    def range(self) -> Decimal:
        return self.high - self.low
