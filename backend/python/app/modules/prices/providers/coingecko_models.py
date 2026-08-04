"""Internal CoinGecko transport and parser values."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CoinGeckoHttpResponse:
    status_code: int
    content_type: str
    body: bytes


@dataclass(frozen=True, slots=True)
class CoinGeckoSimplePrice:
    price: Decimal
    last_updated_at: int
