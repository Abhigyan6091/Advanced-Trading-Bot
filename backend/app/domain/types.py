"""Reusable constrained field types.

Centralising these keeps validation identical across every model instead of
re-deriving the constraint at each declaration site.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer

#: A price or notional. Must be strictly positive.
Price = Annotated[Decimal, Field(gt=0)]

#: A traded quantity. Must be strictly positive.
Quantity = Annotated[Decimal, Field(gt=0)]

#: A quantity that may legitimately be zero (e.g. a rejected order's approved size).
NonNegQuantity = Annotated[Decimal, Field(ge=0)]

#: A signed money amount — P&L, which may be negative.
Money = Annotated[Decimal, Field()]

#: Normalised confidence in [0, 1].
Strength = Annotated[Decimal, Field(ge=0, le=1)]

#: Risk score in [0, 100]. Higher means riskier.
RiskScore = Annotated[Decimal, Field(ge=0, le=100)]

#: Serialises Decimal as a JSON string to avoid float coercion on the wire.
DecimalStr = Annotated[Decimal, PlainSerializer(str, return_type=str)]
