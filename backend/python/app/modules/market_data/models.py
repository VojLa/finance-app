"""Immutable market-evidence requirements and orchestration results."""

from dataclasses import dataclass
from datetime import datetime

from app.db.models.enums import ExchangeRateSource, PriceSource


class MarketEvidenceStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Market evidence is unavailable.")


class MarketEvidenceConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Market evidence conflicts with persisted state.")


@dataclass(frozen=True, slots=True)
class PriceRequirement:
    account_id: str
    asset_id: str
    listing_id: str
    listing_currency: str
    provider: PriceSource
    provider_symbol: str
    through: datetime


@dataclass(frozen=True, slots=True)
class ExchangeRateRequirement:
    from_currency: str
    to_currency: str
    through: datetime
    provider: ExchangeRateSource


@dataclass(frozen=True, slots=True)
class MarketEvidenceRefreshPlan:
    user_id: str
    output_currency: str
    snapshot_timestamp: datetime
    price_requirements: tuple[PriceRequirement, ...]
    fx_requirements: tuple[ExchangeRateRequirement, ...]


@dataclass(frozen=True, slots=True)
class MarketEvidenceRefreshResult:
    user_id: str
    snapshot_timestamp: datetime
    output_currency: str
    required_price_count: int
    required_fx_count: int
    price_ids: tuple[str, ...]
    exchange_rate_ids: tuple[str, ...]
    prices_created: int
    prices_replayed: int
    rates_created: int
    rates_replayed: int
