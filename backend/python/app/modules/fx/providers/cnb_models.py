"""Immutable CNB transport and parsing models."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CnbFxHttpResponse:
    status_code: int
    content_type: str | None
    body: bytes


@dataclass(frozen=True, slots=True)
class CnbPublishedRate:
    currency_code: str
    amount: Decimal
    czk_value: Decimal


@dataclass(frozen=True, slots=True)
class CnbDailyRates:
    publication_date: date
    rates: tuple[CnbPublishedRate, ...]
