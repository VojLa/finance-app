"""Provider-independent canonical price observations."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.db.models.enums import PriceSource


@dataclass(frozen=True, slots=True)
class PriceObservation:
    asset_id: str
    listing_id: str
    provider: PriceSource
    provider_symbol: str
    price: Decimal
    currency: str
    observed_at: datetime
