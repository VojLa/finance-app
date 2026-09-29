"""Immutable Twelve Data FX transport and parser models."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TwelveDataFxHttpResponse:
    status_code: int
    content_type: str
    body: bytes


@dataclass(frozen=True, slots=True)
class TwelveDataFxPoint:
    symbol: str
    effective_at: datetime
    rate: Decimal
