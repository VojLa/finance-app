"""Internal Twelve Data transport and parser values."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TwelveDataHttpResponse:
    status_code: int
    content_type: str
    body: bytes
    retry_after: str | None = None


@dataclass(frozen=True, slots=True)
class TwelveDataQuote:
    symbol: str
    mic_code: str
    currency: str
    close: Decimal
    timestamp: int
    last_quote_at: int
    last_quote_at_utc: datetime
