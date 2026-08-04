"""Provider-independent canonical exchange-rate observations."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.db.models.enums import ExchangeRateSource


@dataclass(frozen=True, slots=True)
class ExchangeRateObservation:
    from_currency: str
    to_currency: str
    provider: ExchangeRateSource
    rate: Decimal
    effective_at: datetime
