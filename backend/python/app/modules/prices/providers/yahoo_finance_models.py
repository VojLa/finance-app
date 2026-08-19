"""Internal values for the bounded Yahoo Finance chart endpoint."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class YahooFinanceHttpResponse:
    status_code: int
    content_type: str
    body: bytes


@dataclass(frozen=True, slots=True)
class YahooFinanceChartPoint:
    observed_at: datetime
    close: Decimal


@dataclass(frozen=True, slots=True)
class YahooFinanceChart:
    symbol: str
    currency: str
    points: tuple[YahooFinanceChartPoint, ...]


__all__ = ["YahooFinanceChart", "YahooFinanceChartPoint", "YahooFinanceHttpResponse"]
